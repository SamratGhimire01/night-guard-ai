"""Phase 52 stage 3 — the staff reply (POST /inbox/conversations/{id}/reply) on all four channels, the 24-hour window, the
delivery-status columns (staff replies AND AI replies), the thread/header reads, the widget receiving staff messages, and the
non-text placeholders.

The outbound HTTP to Meta is captured at `urllib.request.urlopen` — i.e. the REAL adapter code builds the REAL request (URL,
auth, body shape) and only the wire is faked — so each test asserts what would actually be sent to Meta. Real DB, real
orchestrator, real webhook handlers; stubbed Chat/Embedding providers.
"""

import io
import json as jsonlib
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models.audit_log import AuditLog
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.db.models.customer import Customer
from app.db.models.integration import Integration
from app.services import inbox_service
from app.services.channels import delivery

from tests.integration.test_human_takeover import (  # noqa: F401
    IG_ID, PAGE_ID, PNID, _auth, _count, _email, _messages, _new_conversation, _webhook, biz, client, llm,
)

REF = {"whatsapp": "9779822222222", "messenger": "psid-send", "instagram": "igsid-send"}


# ------------------------------------------------------------------------------------------------ fixtures / helpers


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return jsonlib.dumps(self._payload).encode()


@pytest.fixture
def graph(monkeypatch):
    """Capture every urllib request the channel adapters make; `graph.fail = 400` makes Meta reject them."""
    from app.services.channels.whatsapp import WhatsAppChannelAdapter

    class Graph:
        calls: list = []
        fail: int | None = None

    Graph.calls = []
    Graph.fail = None

    def fake_urlopen(request, timeout=None):
        url = request.full_url
        Graph.calls.append({"url": url, "body": jsonlib.loads(request.data), "headers": {k.lower(): v for k, v in request.header_items()}})
        if Graph.fail:
            raise urllib.error.HTTPError(url, Graph.fail, "rejected", {}, io.BytesIO(b'{"error":"secret provider detail"}'))
        if "/me/messages" in url or f"/{IG_ID}/messages" in url:
            return _Resp({"message_id": "m_FAKE"})
        return _Resp({"messages": [{"id": "wamid.FAKE"}]})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(WhatsAppChannelAdapter, "send_typing_indicator", lambda self, **kw: "sent")
    return Graph


@pytest.fixture
def wired(biz):
    """`biz` with a (fake) access token on every channel integration, so sends are real-shaped instead of simulated."""
    with SessionLocal() as db:
        for row in db.query(Integration).filter(Integration.business_id == biz["business_id"]):
            row.config = {
                "whatsapp": {"phone_number_id": PNID, "access_token": "tok-wa"},
                "messenger": {"page_id": PAGE_ID, "page_access_token": "tok-ms"},
                "instagram": {"ig_account_id": IG_ID, "access_token": "tok-ig"},
            }[row.type]
        db.commit()
    return biz


def _seed(business_id, channel, *, hours_since_customer_msg: float = 0.1) -> uuid.UUID:
    """A conversation on `channel` for a customer with a real ChannelIdentity and one CUSTOMER message."""
    ref = REF.get(channel, "x-" + uuid.uuid4().hex[:8])
    with SessionLocal() as db:
        customer = Customer(business_id=business_id, name="Send Customer")
        db.add(customer)
        db.flush()
        db.add(ChannelIdentity(business_id=business_id, channel=channel, external_ref=ref + uuid.uuid4().hex[:6], customer_id=customer.id))
        conversation = Conversation(business_id=business_id, customer_id=customer.id, channel=channel, status="open")
        db.add(conversation)
        db.flush()
        db.add(Message(conversation_id=conversation.id, sender_type=MessageSenderType.CUSTOMER, content="hello"))
        db.commit()
        cid = conversation.id
    _age_messages(cid, hours_since_customer_msg)
    return cid


def _age_messages(cid, hours: float) -> None:
    with SessionLocal() as db:
        db.execute(text("UPDATE messages SET created_at = localtimestamp - make_interval(secs => :s) WHERE conversation_id = :c"),
                   {"s": hours * 3600, "c": cid})
        db.commit()


def _reply(cid, token, content="Hi, this is the clinic.", client_msg_id=None):
    body = {"content": content}
    if client_msg_id:
        body["client_msg_id"] = client_msg_id
    return client.post(f"/api/v1/inbox/conversations/{cid}/reply", json=body, headers=_auth(token))


def _detail(cid, token):
    resp = client.get(f"/api/v1/inbox/conversations/{cid}", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


# ------------------------------------------------------------------------------------------------ 1. a staff reply reaches each channel


def _assert_wa(call, text_):
    assert call["url"].endswith(f"/{PNID}/messages")
    assert call["headers"]["authorization"] == "Bearer tok-wa"
    assert call["body"]["type"] == "text" and call["body"]["text"]["body"] == text_
    assert call["body"]["to"].startswith(REF["whatsapp"])


def _assert_ms(call, text_):
    assert "/me/messages?access_token=tok-ms" in call["url"]
    assert call["body"]["message"] == {"text": text_} and call["body"]["recipient"]["id"].startswith(REF["messenger"])


def _assert_ig(call, text_):
    assert f"/{IG_ID}/messages?access_token=tok-ig" in call["url"]
    assert call["body"]["message"] == {"text": text_} and call["body"]["recipient"]["id"].startswith(REF["instagram"])


@pytest.mark.parametrize(
    ("channel", "check", "detail_prefix"),
    [("whatsapp", _assert_wa, "sent wamid="), ("messenger", _assert_ms, "sent mid="), ("instagram", _assert_ig, "sent mid=")],
)
def test_staff_reply_is_sent_on_the_customers_real_channel(wired, graph, llm, channel, check, detail_prefix):
    cid = _seed(wired["business_id"], channel)
    resp = _reply(cid, wired["staff_token"], "Yes, we open at 9.")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["sender_type"] == "staff" and body["delivery_status"] == "sent"
    assert body["delivery_detail"].startswith(detail_prefix)
    assert body["sent_by_email"] and body["sent_by_user_id"]
    assert len(graph.calls) == 1
    check(graph.calls[0], "Yes, we open at 9.")  # the real request that would go to Meta
    # stored, authored, audited, and the AI is now silent for this conversation
    stored = [m for m in _messages(cid) if m.sender_type == MessageSenderType.STAFF]
    assert len(stored) == 1 and stored[0].sent_by_user_id == uuid.UUID(body["sent_by_user_id"])
    detail = _detail(cid, wired["staff_token"])
    assert detail["takeover"]["active"] is True and detail["takeover_by_email"]  # "who is handling this"
    with SessionLocal() as db:
        audit = db.query(AuditLog).filter_by(action="inbox_reply", resource_id=str(cid)).one()
        assert audit.result == "sent" and audit.actor == body["sent_by_user_id"]


@pytest.mark.parametrize("channel", ["whatsapp", "messenger", "instagram"])
def test_after_a_staff_reply_the_ai_stays_silent_on_that_channel(wired, graph, llm, channel):
    _webhook(channel, "hi")  # the customer talks to the AI first (real webhook -> conversation + AI reply)
    from tests.integration.test_human_takeover import _channel_conversation

    cid = _channel_conversation(wired["business_id"], channel)
    assert _reply(cid, wired["owner_token"]).status_code == 201
    graph.calls.clear()
    llm_calls = llm.calls
    _webhook(channel, "thanks! and another question")
    assert graph.calls == [] and llm.calls == llm_calls  # no AI reply, no LLM call
    assert _messages(cid)[-1].content == "thanks! and another question"


def test_website_staff_reply_reaches_the_widget_through_its_poll(wired, llm):
    url = f"/api/v1/widget/{wired['business_id']}/messages"
    first = client.post(url, json={"content": "hi"}).json()
    token, cursor = first["session_token"], first["agent_message_id"]
    with SessionLocal() as db:
        cid = db.query(Conversation).filter_by(business_id=wired["business_id"], channel="website").one().id

    resp = _reply(cid, wired["staff_token"], "Hello from the team!")
    assert resp.status_code == 201 and resp.json()["delivery_status"] == "sent"
    assert resp.json()["delivery_detail"] == "recorded for widget poll"

    poll = client.get(f"/api/v1/widget/{wired['business_id']}/updates", params={"session_token": token, "after": cursor})
    assert [m["content"] for m in poll.json()["messages"]] == ["Hello from the team!"]  # a STAFF message is now delivered

    # the visitor answers while the human owns it: no AI reply, but the response carries the polling cursor
    second = client.post(url, json={"content": "thanks!", "session_token": token}).json()
    assert second["response"] is None and second["customer_message_id"]
    assert client.get(f"/api/v1/widget/{wired['business_id']}/updates",
                      params={"session_token": token, "after": second["customer_message_id"]}).json()["messages"] == []
    assert _reply(cid, wired["staff_token"], "Anything else?").status_code == 201
    after = client.get(f"/api/v1/widget/{wired['business_id']}/updates",
                       params={"session_token": token, "after": second["customer_message_id"]}).json()["messages"]
    assert [m["content"] for m in after] == ["Anything else?"]  # the customer-message id worked as the cursor


def test_a_session_token_of_another_business_never_sees_staff_messages(wired, llm):
    cid = _seed(wired["business_id"], "website")
    assert _reply(cid, wired["staff_token"]).status_code == 201
    other = client.get(f"/api/v1/widget/{wired['business_id']}/updates", params={"session_token": "nope", "after": str(uuid.uuid4())})
    assert other.json() == {"messages": []}


# ------------------------------------------------------------------------------------------------ 2. delivery failure / simulation


def test_a_send_meta_rejects_is_stored_as_failed_with_a_safe_reason(wired, graph):
    graph.fail = 400
    cid = _seed(wired["business_id"], "whatsapp")
    resp = _reply(cid, wired["owner_token"])
    assert resp.status_code == 201  # the message exists (and is visible/retryable); delivery is what failed
    assert resp.json()["delivery_status"] == "failed" and resp.json()["delivery_detail"] == "failed: HTTP 400"
    assert "secret provider detail" not in resp.text  # never the raw provider response body
    assert _detail(cid, wired["owner_token"])["takeover"]["active"] is True  # a human still owns it


def test_no_token_configured_is_recorded_as_simulated(biz, llm, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_access_token", "")  # no platform token either -> the adapter simulates
    cid = _seed(biz["business_id"], "whatsapp")
    resp = _reply(cid, biz["owner_token"])
    assert resp.status_code == 201 and resp.json()["delivery_status"] == "simulated"


# ------------------------------------------------------------------------------------------------ 3. the 24-hour window


@pytest.mark.parametrize("channel", ["whatsapp", "messenger", "instagram"])
def test_old_conversation_shows_cant_reply_and_a_reply_is_refused_without_sending_or_claiming(wired, graph, llm, channel):
    cid = _seed(wired["business_id"], channel, hours_since_customer_msg=30)
    info = _detail(cid, wired["staff_token"])
    label = {"whatsapp": "WhatsApp", "messenger": "Messenger", "instagram": "Instagram"}[channel]
    assert info["reply"]["can_reply"] is False
    assert f"24-hour {label} reply window closed" in info["reply"]["reason"] and "30 hours" in info["reply"]["reason"]

    resp = _reply(cid, wired["staff_token"])
    assert resp.status_code == 409 and "24-hour" in resp.json()["error"]["message"]
    assert graph.calls == []  # nothing reached the wire
    assert _count(cid, MessageSenderType.STAFF) == 0  # nothing stored
    assert _detail(cid, wired["staff_token"])["takeover"]["active"] is False  # and the AI was NOT silenced by a failed attempt


def test_window_boundary_23h59_open_24h01_closed(wired):
    cid = _seed(wired["business_id"], "whatsapp", hours_since_customer_msg=0)
    with SessionLocal() as db:
        conversation = db.get(Conversation, cid)
        last = inbox_service.last_customer_message_at(db, cid)
        assert inbox_service.reply_state(db, conversation, now=last + timedelta(hours=23, minutes=59)).can_reply is True
        closed = inbox_service.reply_state(db, conversation, now=last + timedelta(hours=24, minutes=1))
        assert closed.can_reply is False and closed.window_closes_at == last + timedelta(hours=24)


def test_a_new_customer_message_reopens_the_window(wired, graph, llm):
    cid = _seed(wired["business_id"], "whatsapp", hours_since_customer_msg=30)
    assert _reply(cid, wired["staff_token"]).status_code == 409
    with SessionLocal() as db:
        db.add(Message(conversation_id=cid, sender_type=MessageSenderType.CUSTOMER, content="are you there?"))
        db.commit()
    assert _detail(cid, wired["staff_token"])["reply"]["can_reply"] is True
    assert _reply(cid, wired["staff_token"]).status_code == 201


def test_website_has_no_window(wired):
    cid = _seed(wired["business_id"], "website", hours_since_customer_msg=24 * 20)
    assert _detail(cid, wired["staff_token"])["reply"]["can_reply"] is True
    assert _reply(cid, wired["staff_token"]).status_code == 201


def test_unsupported_channel_and_disconnected_channel_cant_reply(wired, biz):
    sms = _seed(wired["business_id"], "sms")
    info = _detail(sms, wired["staff_token"])
    assert info["reply"]["can_reply"] is False and "'sms' channel" in info["reply"]["reason"]
    assert _reply(sms, wired["staff_token"]).status_code == 409

    cid = _seed(wired["business_id"], "whatsapp")
    with SessionLocal() as db:
        db.query(Integration).filter_by(business_id=wired["business_id"], type="whatsapp").update({"enabled": False})
        db.commit()
    info = _detail(cid, wired["staff_token"])
    assert info["reply"]["can_reply"] is False and "isn't connected" in info["reply"]["reason"]


# ------------------------------------------------------------------------------------------------ 4. idempotency, validation, RBAC, tenancy


def test_same_client_msg_id_sends_once_and_returns_the_original(wired, graph):
    cid = _seed(wired["business_id"], "whatsapp")
    key = uuid.uuid4().hex
    first, second = _reply(cid, wired["staff_token"], "One", key), _reply(cid, wired["staff_token"], "One", key)
    assert first.status_code == second.status_code == 201 and first.json()["id"] == second.json()["id"]
    assert len(graph.calls) == 1 and _count(cid, MessageSenderType.STAFF) == 1
    third = _reply(cid, wired["staff_token"], "One", uuid.uuid4().hex)  # a different key is a different reply
    assert third.json()["id"] != first.json()["id"] and len(graph.calls) == 2


@pytest.mark.parametrize(
    ("channel", "content", "ok"),
    [("whatsapp", "x" * 4096, True), ("whatsapp", "x" * 4097, False), ("messenger", "x" * 2001, False),
     ("instagram", "x" * 1000, True), ("instagram", "न" * 400, False)],  # 400 Devanagari chars = 1200 bytes
)
def test_length_limits_per_channel(wired, graph, channel, content, ok):
    cid = _seed(wired["business_id"], channel)
    assert (_reply(cid, wired["staff_token"], content).status_code == 201) is ok


def test_blank_reply_is_rejected(wired, graph):
    cid = _seed(wired["business_id"], "whatsapp")
    assert _reply(cid, wired["staff_token"], "   ").status_code == 422
    assert graph.calls == []


def test_roles_auth_and_tenant_isolation(wired, graph):
    cid = _seed(wired["business_id"], "whatsapp")
    for method, path in (("post", f"/reply"), ("get", ""), ("get", "/messages")):
        url = f"/api/v1/inbox/conversations/{cid}{path}"
        kwargs = {"json": {"content": "x"}} if method == "post" else {}
        assert getattr(client, method)(url, **kwargs).status_code == 401
        assert getattr(client, method)(url, headers=_auth(wired["other_token"]), **kwargs).status_code == 404
    for token in ("staff_token", "owner_token"):
        assert _reply(cid, wired[token], f"from {token}").status_code == 201
    assert graph.calls and all("tok-wa" in c["headers"]["authorization"] for c in graph.calls)
    assert _reply(uuid.uuid4(), wired["owner_token"]).status_code == 404


# ------------------------------------------------------------------------------------------------ 5. the thread (one query, every channel)


def test_thread_shows_customer_ai_and_staff_with_delivery_status_and_supports_a_cursor(wired, graph, llm):
    _webhook("whatsapp", "hi")
    from tests.integration.test_human_takeover import _channel_conversation

    cid = _channel_conversation(wired["business_id"], "whatsapp")
    assert _reply(cid, wired["staff_token"], "Staff here").status_code == 201
    thread = client.get(f"/api/v1/inbox/conversations/{cid}/messages", headers=_auth(wired["staff_token"])).json()
    assert [(m["sender_type"], m["delivery_status"]) for m in thread] == [("customer", None), ("agent", "sent"), ("staff", "sent")]
    assert thread[2]["sent_by_email"] and thread[2]["content"] == "Staff here"
    newer = client.get(f"/api/v1/inbox/conversations/{cid}/messages", params={"after": thread[1]["id"]}, headers=_auth(wired["staff_token"]))
    assert [m["content"] for m in newer.json()] == ["Staff here"]
    assert client.get(f"/api/v1/inbox/conversations/{cid}/messages", params={"after": str(uuid.uuid4())},
                      headers=_auth(wired["staff_token"])).status_code == 404


# ------------------------------------------------------------------------------------------------ 6. AI replies now record delivery too (was: only logged)


@pytest.mark.parametrize("channel", ["whatsapp", "messenger", "instagram"])
def test_ai_reply_delivery_is_recorded_sent_and_failed(wired, graph, llm, channel):
    _webhook(channel, "hi")
    graph.fail = 400
    _webhook(channel, "hello again")
    from tests.integration.test_human_takeover import _channel_conversation

    agent = [m for m in _messages(_channel_conversation(wired["business_id"], channel)) if m.sender_type == MessageSenderType.AGENT]
    assert [m.delivery_status for m in agent] == ["sent", "failed"]
    assert agent[0].delivery_detail.startswith("sent ") and agent[1].delivery_detail == "failed: HTTP 400"


def test_system_messages_record_delivery_too(wired, graph):
    from app.services.channels.proactive import send_to_conversation

    cid = _seed(wired["business_id"], "messenger")
    with SessionLocal() as db:
        detail = send_to_conversation(db, conversation=db.get(Conversation, cid), text="Payment received")
    assert detail.startswith("sent mid=")
    agent = [m for m in _messages(cid) if m.sender_type == MessageSenderType.AGENT]
    assert agent[0].delivery_status == "sent" and agent[0].content == "Payment received"


def test_delivery_status_mapping():
    s = delivery.status_from_detail
    assert (s("sent wamid=x"), s("sent mid=y"), s("recorded for widget poll")) == ("sent",) * 3
    assert s("simulated — no real WhatsApp access token configured") == "simulated"
    assert (s("failed: HTTP 400"), s("recorded; push failed"), s("recorded; no connected channel to push to")) == ("failed",) * 3


# ------------------------------------------------------------------------------------------------ 7. non-text placeholders


def _wa_media(message: dict) -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"id": "W", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "1", "phone_number_id": PNID},
        "contacts": [{"profile": {"name": "M"}, "wa_id": "9779833333333"}],
        "messages": [{"from": "9779833333333", "id": f"wamid.{uuid.uuid4().hex}", "timestamp": "1", **message}]}}]}]}


def _post_raw(path: str, secret: str, payload: dict):
    import hashlib, hmac

    raw = jsonlib.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(f"/api/v1/webhooks/{path}", content=raw, headers={"content-type": "application/json", "x-hub-signature-256": sig})


def _wa_thread(business_id):
    with SessionLocal() as db:
        c = db.query(Conversation).filter_by(business_id=business_id, channel="whatsapp").one()
        return [(m.sender_type, m.content, m.detected_intent) for m in db.query(Message).filter_by(conversation_id=c.id).order_by(Message.created_at)]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ({"type": "image", "image": {"id": "1"}}, "[Customer sent an image]"),
        ({"type": "audio", "audio": {"id": "1", "voice": True}}, "[Customer sent a voice note]"),
        ({"type": "audio", "audio": {"id": "1", "voice": False}}, "[Customer sent an audio file]"),
        ({"type": "video", "video": {"id": "1"}}, "[Customer sent a video]"),
        ({"type": "document", "document": {"id": "1"}}, "[Customer sent a document]"),
        ({"type": "sticker", "sticker": {"id": "1"}}, "[Customer sent a sticker]"),
        ({"type": "location", "location": {"latitude": 1, "longitude": 2}}, "[Customer shared a location]"),
        ({"type": "contacts", "contacts": [{}]}, "[Customer shared a contact]"),
        ({"type": "order", "order": {}}, "[Customer sent a message this channel can't show]"),
    ],
)
def test_whatsapp_non_text_is_stored_as_a_placeholder_and_the_ai_stays_out_of_it(wired, graph, llm, message, expected):
    resp = _post_raw("whatsapp", settings.whatsapp_app_secret, _wa_media(message))
    assert resp.status_code == 200
    assert _wa_thread(wired["business_id"]) == [(MessageSenderType.CUSTOMER, expected, None)]
    assert llm.calls == 0 and graph.calls == []  # no AI turn, nothing sent (as before, but now it is VISIBLE)


@pytest.mark.parametrize("ignored", [{"type": "reaction", "reaction": {"emoji": "👍"}}, {"type": "system", "system": {}}])
def test_whatsapp_reactions_and_system_notices_are_not_recorded(wired, graph, llm, ignored):
    assert _post_raw("whatsapp", settings.whatsapp_app_secret, _wa_media(ignored)).status_code == 200
    with SessionLocal() as db:
        assert db.query(Conversation).filter_by(business_id=wired["business_id"]).count() == 0


def test_placeholder_redelivery_is_idempotent_and_it_opens_the_reply_window(wired, graph, llm):
    payload = _wa_media({"type": "image", "image": {"id": "1"}})
    for _ in range(2):
        assert _post_raw("whatsapp", settings.whatsapp_app_secret, payload).status_code == 200
    thread = _wa_thread(wired["business_id"])
    assert len(thread) == 1  # the same wamid delivered twice -> one message
    with SessionLocal() as db:
        cid = db.query(Conversation).filter_by(business_id=wired["business_id"]).one().id
    assert _detail(cid, wired["staff_token"])["reply"]["can_reply"] is True  # the customer just messaged: window open
    assert _reply(cid, wired["staff_token"], "Thanks for the photo, looking now").status_code == 201


def test_a_placeholder_during_takeover_is_stored_too(wired, graph, llm):
    _webhook("whatsapp", "hi")
    from tests.integration.test_human_takeover import _channel_conversation

    cid = _channel_conversation(wired["business_id"], "whatsapp")
    assert _reply(cid, wired["staff_token"]).status_code == 201
    from tests.integration.test_human_takeover import CHANNELS

    contact = CHANNELS["whatsapp"][2]  # the same WhatsApp contact `_webhook` used, so it lands in the same conversation
    payload = _wa_media({"type": "image", "image": {"id": "1"}})
    value = payload["entry"][0]["changes"][0]["value"]
    value["messages"][0]["from"] = value["contacts"][0]["wa_id"] = contact
    assert _post_raw("whatsapp", settings.whatsapp_app_secret, payload).status_code == 200
    assert _messages(cid)[-1].content == "[Customer sent an image]"


@pytest.mark.parametrize(
    ("channel", "path", "secret_attr", "object_", "account"),
    [("messenger", "messenger", "messenger_app_secret", "page", PAGE_ID), ("instagram", "instagram", "instagram_app_secret", "instagram", IG_ID)],
)
@pytest.mark.parametrize(
    ("attachment", "expected"),
    [({"type": "image"}, "[Customer sent an image]"), ({"type": "audio"}, "[Customer sent a voice note]"),
     ({"type": "video"}, "[Customer sent a video]"), ({"type": "file"}, "[Customer sent a document]"),
     ({"type": "share"}, "[Customer shared a post]"), ({"type": "fallback"}, "[Customer sent a message this channel can't show]")],
)
def test_messenger_and_instagram_attachments_become_placeholders(wired, graph, llm, channel, path, secret_attr, object_, account, attachment, expected):
    payload = {"object": object_, "entry": [{"id": account, "time": 1, "messaging": [
        {"sender": {"id": "psid-att"}, "recipient": {"id": account}, "timestamp": 1,
         "message": {"mid": f"mid.{uuid.uuid4().hex}", "attachments": [attachment]}}]}]}
    assert _post_raw(path, getattr(settings, secret_attr), payload).status_code == 200
    with SessionLocal() as db:
        c = db.query(Conversation).filter_by(business_id=wired["business_id"], channel=channel).one()
        assert [(m.sender_type, m.content) for m in db.query(Message).filter_by(conversation_id=c.id)] == [(MessageSenderType.CUSTOMER, expected)]
    assert llm.calls == 0 and graph.calls == []


def test_a_message_with_text_and_an_attachment_takes_the_text_path_once(wired, graph, llm):
    payload = {"object": "page", "entry": [{"id": PAGE_ID, "time": 1, "messaging": [
        {"sender": {"id": "psid-both"}, "recipient": {"id": PAGE_ID}, "timestamp": 1,
         "message": {"mid": f"mid.{uuid.uuid4().hex}", "text": "look at this", "attachments": [{"type": "image"}]}}]}]}
    assert _post_raw("messenger", settings.messenger_app_secret, payload).status_code == 200
    with SessionLocal() as db:
        c = db.query(Conversation).filter_by(business_id=wired["business_id"], channel="messenger").one()
        contents = [m.content for m in db.query(Message).filter_by(conversation_id=c.id).order_by(Message.created_at)]
    assert contents[0] == "look at this" and len(contents) == 2  # customer text + the AI's reply; no separate placeholder
