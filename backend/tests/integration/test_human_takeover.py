"""Phase 52 stage 2 — human takeover: while a staff member owns a conversation the AI must NOT answer.

Safety-critical, so the adversarial case comes first: a staff member claims the conversation WHILE the AI's LLM call is
in flight (the stubbed ChatProvider commits the takeover from a separate DB session at that exact moment). The AI's draft
must be discarded — no AGENT message, nothing sent to the channel, and none of the turn's side effects (handoff row, contact
update). Then the simple cases (already active / released / expired / sliding), every channel's webhook, the widget, the
takeover/release endpoints (roles + tenant isolation) and "resolving a handoff hands the conversation back".

Stubbed Chat/Embedding providers (no API cost); real signatures, real DB, real orchestrator, real webhook handlers.
"""

import hashlib
import hmac
import json as jsonlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.db.models.business import Business, BusinessUser, BusinessUserRole
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.db.models.customer import Customer
from app.db.models.handoff import HumanHandoff
from app.db.models.integration import Integration
from app.main import app
from app.services import takeover_service

client = TestClient(app)

PNID, PAGE_ID, IG_ID = "pnid-takeover", "page-takeover", "ig-takeover"


class _Chat:
    """Stub ChatProvider. `calls` counts LLM turns; `during_call` runs INSIDE chat() — i.e. mid-LLM-call."""

    def __init__(self):
        self.calls = 0
        self.during_call = None
        self.payload = {"intent": "general_question", "response": "Thanks for messaging us!"}

    def chat(self, messages):
        self.calls += 1
        if self.during_call is not None:
            self.during_call()
        return jsonlib.dumps(self.payload)


class _Embed:
    def embed(self, texts):
        return [[0.01] * 1536 for _ in texts]


@pytest.fixture
def llm(monkeypatch):
    import app.services.conversation.intent as intent_module
    import app.services.conversation.orchestrator as orchestrator_module

    chat = _Chat()
    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: chat)
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _Embed())
    return chat


def _email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(name: str) -> tuple[uuid.UUID, str]:
    email = _email("tk")
    resp = client.post(
        "/api/v1/auth/register",
        json={"business_name": name, "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    assert resp.status_code == 201, resp.text
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"}).json()["access_token"]
    return uuid.UUID(resp.json()["business_id"]), token


@pytest.fixture
def biz():
    """Tenant A (all three Meta integrations wired, no tokens -> sends are simulated), an owner token, a STAFF token, and an
    unrelated tenant B."""
    business_id, owner_token = _register("Takeover Test A")
    other_id, other_token = _register("Takeover Test B")
    with SessionLocal() as db:
        db.add_all(
            [
                Integration(business_id=business_id, type="whatsapp", config={"phone_number_id": PNID}, enabled=True),
                Integration(business_id=business_id, type="messenger", config={"page_id": PAGE_ID}, enabled=True),
                Integration(business_id=business_id, type="instagram", config={"ig_account_id": IG_ID}, enabled=True),
            ]
        )
        staff = BusinessUser(
            business_id=business_id, email=_email("tk-staff"), hashed_password="unused", role=BusinessUserRole.STAFF
        )
        db.add(staff)
        db.commit()
        db.refresh(staff)
        staff_token = create_access_token(user_id=staff.id, business_id=business_id, role="staff")
        staff_id = staff.id
    yield {
        "business_id": business_id,
        "owner_token": owner_token,
        "staff_token": staff_token,
        "staff_id": staff_id,
        "other_token": other_token,
    }
    with SessionLocal() as db:
        for bid in (business_id, other_id):
            b = db.get(Business, bid)
            if b is not None:
                db.delete(b)
        db.commit()


# ---------------------------------------------------------------------------- helpers


def _new_conversation(business_id: uuid.UUID, channel: str = "sms") -> uuid.UUID:
    with SessionLocal() as db:
        customer = Customer(business_id=business_id, name="Takeover Customer")
        db.add(customer)
        db.flush()
        conversation = Conversation(business_id=business_id, customer_id=customer.id, channel=channel, status="open")
        db.add(conversation)
        db.commit()
        return conversation.id


def _set_takeover(conversation_id: uuid.UUID, *, seconds_from_now: float | None, by: uuid.UUID | None = None) -> None:
    """What a staff reply does, done from a SEPARATE session — exactly as it would land mid-LLM-call."""
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        conversation.human_takeover_until = (
            None if seconds_from_now is None else datetime.now(timezone.utc) + timedelta(seconds=seconds_from_now)
        )
        conversation.human_takeover_by = by
        db.commit()


def _messages(conversation_id: uuid.UUID) -> list[Message]:
    with SessionLocal() as db:
        return list(
            db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.created_at).all()
        )


def _count(conversation_id: uuid.UUID, sender: MessageSenderType) -> int:
    return sum(1 for m in _messages(conversation_id) if m.sender_type == sender)


def _post(conversation_id: uuid.UUID, token: str, content: str = "hello there") -> dict:
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json={"content": content}, headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------- 1. the adversarial case


def test_staff_takeover_landing_mid_llm_call_discards_the_ai_draft_and_all_its_side_effects(biz, llm):
    conversation_id = _new_conversation(biz["business_id"])
    with SessionLocal() as db:
        customer_id = db.get(Conversation, conversation_id).customer_id

    # The AI would (a) escalate to a human -> a real HumanHandoff row + addendum, and (b) save the customer's phone number.
    llm.payload = {
        "intent": "human_handoff",
        "response": "Sure, I'll connect you with the team!",
        "contact_info_update": {"name": None, "email": None, "phone": "+9779800000000"},
    }
    # ...but a staff member replies while the LLM call is still running.
    llm.during_call = lambda: _set_takeover(conversation_id, seconds_from_now=7200, by=biz["staff_id"])

    body = _post(conversation_id, biz["owner_token"], "I need to talk to someone")

    assert llm.calls == 1  # the call really happened: this is the mid-turn case, not the "already active" one
    assert body["response"] is None and body["agent_message_id"] is None
    assert _count(conversation_id, MessageSenderType.AGENT) == 0  # the AI draft was discarded, not stored
    customer_msgs = [m for m in _messages(conversation_id) if m.sender_type == MessageSenderType.CUSTOMER]
    assert [m.content for m in customer_msgs] == ["I need to talk to someone"]  # the customer's words are NOT lost
    assert customer_msgs[0].detected_intent == "human_handoff"  # the classification that already happened is kept
    with SessionLocal() as db:
        assert db.query(HumanHandoff).filter(HumanHandoff.conversation_id == conversation_id).count() == 0
        assert db.get(Customer, customer_id).phone is None  # the contact update was NOT applied


def test_control_same_turn_without_the_mid_call_takeover_does_reply_and_apply_side_effects(biz, llm):
    """Proves the adversarial test above is measuring the guard, not a stub that never replies."""
    conversation_id = _new_conversation(biz["business_id"])
    with SessionLocal() as db:
        customer_id = db.get(Conversation, conversation_id).customer_id
    llm.payload = {
        "intent": "human_handoff",
        "response": "Sure, I'll connect you with the team!",
        "contact_info_update": {"name": None, "email": None, "phone": "+9779800000000"},
    }
    body = _post(conversation_id, biz["owner_token"], "I need to talk to someone")
    assert body["response"] and body["agent_message_id"]
    assert _count(conversation_id, MessageSenderType.AGENT) == 1
    with SessionLocal() as db:
        assert db.query(HumanHandoff).filter(HumanHandoff.conversation_id == conversation_id).count() == 1
        assert db.get(Customer, customer_id).phone is not None


# ---------------------------------------------------------------------------- 2. the simple cases


def test_active_takeover_stores_the_message_and_never_calls_the_llm(biz, llm):
    conversation_id = _new_conversation(biz["business_id"])
    assert _post(conversation_id, biz["owner_token"])["response"]  # baseline: the AI answers
    assert llm.calls == 1

    _set_takeover(conversation_id, seconds_from_now=7200, by=biz["staff_id"])
    body = _post(conversation_id, biz["owner_token"], "are you still there?")

    assert body["response"] is None and body["agent_message_id"] is None and body["intent"] is None
    assert llm.calls == 1  # zero LLM cost while a human owns it
    msgs = _messages(conversation_id)
    assert msgs[-1].sender_type == MessageSenderType.CUSTOMER and msgs[-1].content == "are you still there?"
    assert msgs[-1].detected_intent is None
    assert _count(conversation_id, MessageSenderType.AGENT) == 1  # still only the pre-takeover reply


def test_release_hands_the_conversation_back_to_the_ai(biz, llm):
    conversation_id = _new_conversation(biz["business_id"])
    _set_takeover(conversation_id, seconds_from_now=7200, by=biz["staff_id"])
    assert _post(conversation_id, biz["owner_token"])["response"] is None

    resp = client.post(f"/api/v1/inbox/conversations/{conversation_id}/release", headers=_auth(biz["owner_token"]))
    assert resp.status_code == 200 and resp.json()["active"] is False

    assert _post(conversation_id, biz["owner_token"])["response"]
    assert llm.calls == 1


def test_an_expired_takeover_hands_control_back_with_no_action_needed(biz, llm):
    conversation_id = _new_conversation(biz["business_id"])
    _set_takeover(conversation_id, seconds_from_now=-60, by=biz["staff_id"])  # ran out a minute ago
    assert _post(conversation_id, biz["owner_token"])["response"]
    assert llm.calls == 1


def test_takeover_window_is_sliding_and_uses_the_configured_length(biz, monkeypatch):
    monkeypatch.setattr(settings, "human_takeover_seconds", 100)
    conversation_id = _new_conversation(biz["business_id"])
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        first = takeover_service.start_or_extend(db, conversation, user_id=biz["staff_id"]).human_takeover_until
        monkeypatch.setattr(settings, "human_takeover_seconds", 500)
        second = takeover_service.start_or_extend(db, conversation, user_id=biz["staff_id"]).human_takeover_until
    now = datetime.now(timezone.utc)
    assert timedelta(seconds=90) < first - now <= timedelta(seconds=100)
    assert second > first  # a second staff reply pushed the expiry out
    assert takeover_service.is_active(SessionLocal(), conversation_id=conversation_id)
    assert settings.human_takeover_seconds == 500  # (monkeypatched; the real default is asserted below)


def test_default_window_is_two_hours():
    assert type(settings).model_fields["human_takeover_seconds"].default == 7200


def test_resolving_a_handoff_releases_the_takeover(biz, llm):
    conversation_id = _new_conversation(biz["business_id"])
    _set_takeover(conversation_id, seconds_from_now=7200, by=biz["staff_id"])
    with SessionLocal() as db:
        handoff = HumanHandoff(
            business_id=biz["business_id"], conversation_id=conversation_id, reason="test", status="open"
        )
        db.add(handoff)
        db.commit()
        handoff_id = handoff.id

    resp = client.patch(
        f"/api/v1/handoffs/{handoff_id}", json={"status": "resolved"}, headers=_auth(biz["staff_token"])
    )
    assert resp.status_code == 200, resp.text
    with SessionLocal() as db:
        c = db.get(Conversation, conversation_id)
        assert c.human_takeover_until is None and c.human_takeover_by is None
    assert _post(conversation_id, biz["owner_token"])["response"]  # the AI is back


# ---------------------------------------------------------------------------- 3. endpoints: roles + tenancy


@pytest.mark.parametrize("role_token", ["owner_token", "staff_token"])
def test_owner_and_staff_can_take_over_and_release(biz, role_token):
    conversation_id = _new_conversation(biz["business_id"])
    resp = client.post(f"/api/v1/inbox/conversations/{conversation_id}/takeover", headers=_auth(biz[role_token]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["active"] is True and body["taken_over_by"] and body["until"]
    resp = client.post(f"/api/v1/inbox/conversations/{conversation_id}/release", headers=_auth(biz[role_token]))
    assert resp.status_code == 200 and resp.json() == {"active": False, "until": None, "taken_over_by": None}


def test_admin_role_is_allowed_too(biz):
    with SessionLocal() as db:
        admin = BusinessUser(
            business_id=biz["business_id"], email=_email("tk-admin"), hashed_password="x", role=BusinessUserRole.ADMIN
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        token = create_access_token(user_id=admin.id, business_id=biz["business_id"], role="admin")
    conversation_id = _new_conversation(biz["business_id"])
    assert client.post(f"/api/v1/inbox/conversations/{conversation_id}/takeover", headers=_auth(token)).status_code == 200


def test_takeover_endpoints_require_authentication_and_are_tenant_isolated(biz):
    conversation_id = _new_conversation(biz["business_id"])
    for action in ("takeover", "release"):
        url = f"/api/v1/inbox/conversations/{conversation_id}/{action}"
        assert client.post(url).status_code == 401
        # another business's token must not even learn the conversation exists
        assert client.post(url, headers=_auth(biz["other_token"])).status_code == 404
    assert client.post(
        f"/api/v1/inbox/conversations/{uuid.uuid4()}/takeover", headers=_auth(biz["owner_token"])
    ).status_code == 404
    with SessionLocal() as db:
        assert db.get(Conversation, conversation_id).human_takeover_until is None  # the cross-tenant attempt changed nothing


# ---------------------------------------------------------------------------- 4. every channel's webhook


def _sign(raw: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _wa_payload(wa_id: str, mid: str, text: str) -> tuple[str, dict]:
    return "whatsapp", {
        "object": "whatsapp_business_account",
        "entry": [{"id": "W", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "1", "phone_number_id": PNID},
            "contacts": [{"profile": {"name": "T"}, "wa_id": wa_id}],
            "messages": [{"from": wa_id, "id": mid, "timestamp": "1", "text": {"body": text}, "type": "text"}],
        }}]}],
    }


def _meta_payload(obj: str, account_id: str, sender: str, mid: str, text: str) -> dict:
    return {"object": obj, "entry": [{"id": account_id, "time": 1, "messaging": [
        {"sender": {"id": sender}, "recipient": {"id": account_id}, "timestamp": 1, "message": {"mid": mid, "text": text}}
    ]}]}


CHANNELS = {
    # channel: (webhook path, app-secret setting, external contact ref, payload builder, module holding the adapter)
    "whatsapp": ("whatsapp", "whatsapp_app_secret", "9779811111111",
                 lambda ref, mid, text: _wa_payload(ref, mid, text)[1], "whatsapp_webhook"),
    "messenger": ("messenger", "messenger_app_secret", "psid-takeover",
                  lambda ref, mid, text: _meta_payload("page", PAGE_ID, ref, mid, text), "messenger_webhook"),
    "instagram": ("instagram", "instagram_app_secret", "igsid-takeover",
                  lambda ref, mid, text: _meta_payload("instagram", IG_ID, ref, mid, text), "instagram_webhook"),
}


def _webhook(channel: str, text: str) -> dict:
    path, secret_attr, ref, build, _ = CHANNELS[channel]
    raw = jsonlib.dumps(build(ref, f"mid-{uuid.uuid4().hex}", text)).encode()
    resp = client.post(
        f"/api/v1/webhooks/{path}", content=raw,
        headers={"content-type": "application/json", "x-hub-signature-256": _sign(raw, getattr(settings, secret_attr))},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _channel_conversation(business_id: uuid.UUID, channel: str) -> uuid.UUID:
    ref = CHANNELS[channel][2]
    with SessionLocal() as db:
        identity = db.query(ChannelIdentity).filter_by(business_id=business_id, channel=channel, external_ref=ref).one()
        return (
            db.query(Conversation)
            .filter_by(business_id=business_id, customer_id=identity.customer_id, channel=channel)
            .order_by(Conversation.created_at.desc())
            .first()
            .id
        )


@pytest.fixture
def sends(monkeypatch):
    """Record every outbound send/typing call. Patched on the adapter CLASSES, never on the webhook modules' instances:
    monkeypatch can't cleanly undo an instance patch (it leaves the old bound method behind as an instance attribute,
    which then shadows later tests' class-level patches)."""
    from app.services.channels.instagram import InstagramChannelAdapter
    from app.services.channels.messenger import MessengerChannelAdapter
    from app.services.channels.whatsapp import WhatsAppChannelAdapter

    log = {"send": [], "typing": []}
    for name, cls in (("whatsapp", WhatsAppChannelAdapter), ("messenger", MessengerChannelAdapter),
                      ("instagram", InstagramChannelAdapter)):
        monkeypatch.setattr(cls, "send_message", lambda self, _n=name, **kw: log["send"].append((_n, kw["text"])) or "sent")
    monkeypatch.setattr(
        WhatsAppChannelAdapter, "send_typing_indicator", lambda self, **kw: log["typing"].append(kw["message_id"]) or "sent"
    )
    return log


@pytest.mark.parametrize("channel", ["whatsapp", "messenger", "instagram"])
def test_webhook_channel_sends_nothing_during_takeover_and_resumes_after_release(biz, llm, sends, channel):
    business_id = biz["business_id"]
    _webhook(channel, "hi")  # 1) the AI answers the first message
    assert [c for c, _ in sends["send"]] == [channel]
    conversation_id = _channel_conversation(business_id, channel)

    _set_takeover(conversation_id, seconds_from_now=7200, by=biz["staff_id"])
    typing_before = len(sends["typing"])
    _webhook(channel, "hello? anyone?")  # 2) a human owns it now
    assert [c for c, _ in sends["send"]] == [channel]  # nothing new was sent to the customer
    assert len(sends["typing"]) == typing_before  # and no "typing…" indicator on WhatsApp
    assert llm.calls == 1
    assert [m.content for m in _messages(conversation_id) if m.sender_type == MessageSenderType.CUSTOMER] == [
        "hi", "hello? anyone?",
    ]
    assert _count(conversation_id, MessageSenderType.AGENT) == 1

    _set_takeover(conversation_id, seconds_from_now=None)  # 3) handed back
    _webhook(channel, "thanks")
    assert [c for c, _ in sends["send"]] == [channel, channel]
    assert llm.calls == 2


@pytest.mark.parametrize("channel", ["whatsapp", "messenger", "instagram"])
def test_webhook_channel_mid_llm_takeover_sends_nothing(biz, llm, sends, channel):
    """The adversarial case again, end to end through each real webhook handler: nothing may reach the customer."""
    business_id = biz["business_id"]
    _webhook(channel, "hi")
    conversation_id = _channel_conversation(business_id, channel)
    sends["send"].clear()

    llm.during_call = lambda: _set_takeover(conversation_id, seconds_from_now=7200, by=biz["staff_id"])
    _webhook(channel, "what time do you open?")

    assert llm.calls == 2  # the LLM was called for the second message (takeover only landed inside it)
    assert sends["send"] == []  # NOTHING was sent
    assert _count(conversation_id, MessageSenderType.AGENT) == 1  # only the first (pre-takeover) reply exists
    assert _messages(conversation_id)[-1].content == "what time do you open?"


# ---------------------------------------------------------------------------- 5. the website widget


def test_widget_gets_a_null_reply_during_takeover(biz, llm):
    business_id = biz["business_id"]
    url = f"/api/v1/widget/{business_id}/messages"
    first = client.post(url, json={"content": "hi"})
    assert first.status_code == 200, first.text
    token = first.json()["session_token"]
    assert first.json()["response"]

    with SessionLocal() as db:
        conversation = (
            db.query(Conversation).filter_by(business_id=business_id, channel="website")
            .order_by(Conversation.created_at.desc()).first()
        )
        conversation_id = conversation.id
    _set_takeover(conversation_id, seconds_from_now=7200, by=biz["staff_id"])

    resp = client.post(url, json={"content": "anyone there?", "session_token": token})
    assert resp.status_code == 200, resp.text
    assert resp.json()["response"] is None and resp.json()["intent"] is None
    assert resp.json()["session_token"] == token
    assert _messages(conversation_id)[-1].content == "anyone there?"
    assert _count(conversation_id, MessageSenderType.AGENT) == 1


def _post_raw_ig(payload: dict):
    raw = jsonlib.dumps(payload).encode()
    return client.post(
        "/api/v1/webhooks/instagram", content=raw,
        headers={"content-type": "application/json", "x-hub-signature-256": _sign(raw, settings.instagram_app_secret)},
    )
