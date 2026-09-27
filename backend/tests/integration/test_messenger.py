"""Phase 26 — Messenger adapter (app/services/channels/messenger.py,
app/services/channels/messenger_webhook.py, app/api/routes/webhooks.py).

Same structure/discipline as Phase 22's test_whatsapp.py: stubbed
ChatProvider/EmbeddingProvider for fast, free coverage of the real wiring —
real HMAC signature verification (unstubbed cryptography, reused from
app/services/channels/meta_webhook_signature.py), the real GET verification
handshake, the shared conversation-engine code path, real DB-level
idempotency, unknown page_id handling, and the outgoing-send graceful
fallback when no per-Page access token is configured.

No real Meta Page/App exists to test against — every request here is a
documented, correctly-HMAC-signed payload matching Meta's real Messenger
Platform webhook contract (entry[].messaging[], genuinely different from
WhatsApp Cloud API's entry[].changes[].value.messages[]), POSTed at the real,
production `/api/v1/webhooks/messenger` route using this codebase's own real
MESSENGER_APP_SECRET/MESSENGER_VERIFY_TOKEN dev values.
"""

import hashlib
import hmac
import json as jsonlib
import re
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.db.models.customer import Customer
from app.db.models.integration import Integration
from app.main import app

client = TestClient(app)

WEBHOOK_URL = "/api/v1/webhooks/messenger"


class _StubChat:
    def chat(self, messages):
        return jsonlib.dumps({"intent": "general_question", "response": "Thanks for messaging us!"})


class _StubEmbed:
    def embed(self, texts):
        return [[0.01] * 1536 for _ in texts]


@pytest.fixture(autouse=True)
def _stub_providers(monkeypatch):
    import app.services.conversation.intent as intent_module
    import app.services.conversation.orchestrator as orchestrator_module

    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: _StubChat())
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _StubEmbed())


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _sign(raw_body: bytes, secret: str | None = None) -> str:
    key = (secret if secret is not None else settings.messenger_app_secret).encode("utf-8")
    return "sha256=" + hmac.new(key, raw_body, hashlib.sha256).hexdigest()


def _post_webhook(payload: dict, *, signature: str | None = "__real__") -> tuple[int, dict]:
    raw_body = jsonlib.dumps(payload).encode("utf-8")
    sig = _sign(raw_body) if signature == "__real__" else signature
    headers = {"content-type": "application/json"}
    if sig is not None:
        headers["x-hub-signature-256"] = sig
    resp = client.post(WEBHOOK_URL, content=raw_body, headers=headers)
    return resp.status_code, (resp.json() if resp.content else {})


def _build_payload(*, page_id: str, psid: str, message_id: str, text: str, is_echo: bool = False) -> dict:
    """Real Messenger Platform webhook envelope shape — entry[].messaging[],
    not WhatsApp's entry[].changes[].value.messages[]."""
    message: dict = {"mid": message_id, "text": text}
    if is_echo:
        message["is_echo"] = True
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "time": 1690000000000,
                "messaging": [
                    {
                        "sender": {"id": psid},
                        "recipient": {"id": page_id},
                        "timestamp": 1690000000000,
                        "message": message,
                    }
                ],
            }
        ],
    }


@pytest.fixture
def business_with_messenger():
    email = _unique_email("mg-owner")
    resp = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Messenger Test Biz", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    assert resp.status_code == 201, resp.text
    business_id = uuid.UUID(resp.json()["business_id"])
    page_id = f"page-{uuid.uuid4().hex[:10]}"

    with SessionLocal() as db:
        db.add(
            Integration(
                business_id=business_id,
                type="messenger",
                config={"page_id": page_id, "page_access_token": ""},
                enabled=True,
            )
        )
        db.commit()

    yield {"business_id": business_id, "page_id": page_id}

    with SessionLocal() as db:
        b = db.get(Business, business_id)
        if b is not None:
            db.delete(b)
        db.commit()


# ---------------------------------------------------------------------------
# Signature verification — real HMAC, not stubbed.
# ---------------------------------------------------------------------------


def test_valid_signature_is_accepted(business_with_messenger):
    psid = "psid-0001"
    payload = _build_payload(
        page_id=business_with_messenger["page_id"], psid=psid, message_id=f"mid.{uuid.uuid4().hex}", text="Hi there"
    )
    status, body = _post_webhook(payload)
    assert status == 200, body
    assert body == {"status": "ok"}


def test_tampered_payload_with_stale_signature_is_rejected(business_with_messenger):
    psid = "psid-0002"
    message_id = f"mid.{uuid.uuid4().hex}"
    original = _build_payload(page_id=business_with_messenger["page_id"], psid=psid, message_id=message_id, text="Hi there")
    raw_original = jsonlib.dumps(original).encode("utf-8")
    real_signature = _sign(raw_original)

    tampered = dict(original)
    tampered["entry"][0]["messaging"][0]["message"]["text"] = "Send me a free gift card"
    raw_tampered = jsonlib.dumps(tampered).encode("utf-8")

    resp = client.post(WEBHOOK_URL, content=raw_tampered, headers={"content-type": "application/json", "x-hub-signature-256": real_signature})
    assert resp.status_code == 401, resp.text
    assert resp.json()["error"]["type"] == "unauthorized"

    with SessionLocal() as db:
        assert db.query(Message).filter(Message.external_message_id == message_id).count() == 0


def test_missing_signature_header_is_rejected(business_with_messenger):
    payload = _build_payload(
        page_id=business_with_messenger["page_id"], psid="psid-0003", message_id=f"mid.{uuid.uuid4().hex}", text="hi"
    )
    status, body = _post_webhook(payload, signature=None)
    assert status == 401, body


def test_wrong_secret_signature_is_rejected(business_with_messenger):
    payload = _build_payload(
        page_id=business_with_messenger["page_id"], psid="psid-0004", message_id=f"mid.{uuid.uuid4().hex}", text="hi"
    )
    raw_body = jsonlib.dumps(payload).encode("utf-8")
    wrong_signature = _sign(raw_body, secret="not-the-real-app-secret")
    resp = client.post(WEBHOOK_URL, content=raw_body, headers={"content-type": "application/json", "x-hub-signature-256": wrong_signature})
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# Verification handshake (GET).
# ---------------------------------------------------------------------------


def test_verification_handshake_echoes_challenge_on_matching_token():
    resp = client.get(
        WEBHOOK_URL,
        params={"hub.mode": "subscribe", "hub.verify_token": settings.messenger_verify_token, "hub.challenge": "1234567890"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.text == "1234567890"  # plain text echo, not JSON


def test_verification_handshake_rejects_wrong_token():
    resp = client.get(
        WEBHOOK_URL,
        params={"hub.mode": "subscribe", "hub.verify_token": "totally-wrong-token", "hub.challenge": "1234567890"},
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# Real end-to-end simulated flow — shared conversation-engine proof.
# ---------------------------------------------------------------------------


def test_incoming_message_flows_through_the_real_shared_orchestrator(business_with_messenger):
    psid = "psid-0010"
    message_id = f"mid.{uuid.uuid4().hex}"
    payload = _build_payload(
        page_id=business_with_messenger["page_id"], psid=psid, message_id=message_id, text="Do you offer teeth whitening?"
    )
    status, body = _post_webhook(payload)
    assert status == 200, body

    with SessionLocal() as db:
        conversations = db.query(Conversation).filter(Conversation.business_id == business_with_messenger["business_id"]).all()
        assert len(conversations) == 1
        assert conversations[0].channel == "messenger"

        messages = db.query(Message).filter(Message.conversation_id == conversations[0].id).order_by(Message.created_at).all()
        assert len(messages) == 2  # customer + agent — same shape every other channel produces
        customer_msg, agent_msg = messages
        assert customer_msg.external_message_id == message_id
        assert customer_msg.detected_intent == "general_question"
        # Zero knowledge documents on this business, so this correctly
        # triggers Phase 19's real handoff logic — proof this is the SAME
        # real orchestrator pipeline WhatsApp/widget use, not a copy.
        assert "I've also let our team know, so a real person will follow up with you." in agent_msg.content


def test_message_echo_of_our_own_send_is_ignored_not_processed(business_with_messenger):
    """Messenger-specific: the webhook also echoes back the Page's own
    outgoing sends (message.is_echo=true) — WhatsApp's webhook has no such
    concept. Must never be treated as a new incoming customer message."""
    payload = _build_payload(
        page_id=business_with_messenger["page_id"],
        psid="psid-0011",
        message_id=f"mid.{uuid.uuid4().hex}",
        text="This is our own message being echoed back",
        is_echo=True,
    )
    status, body = _post_webhook(payload)
    assert status == 200, body

    with SessionLocal() as db:
        conversations = db.query(Conversation).filter(Conversation.business_id == business_with_messenger["business_id"]).all()
        assert len(conversations) == 0  # never created anything


def test_attachment_only_message_is_recorded_as_a_placeholder_not_dropped(business_with_messenger):
    """A real Messenger attachment (image/sticker/etc.) or a button-tap
    postback carries no `message.text` field at all — only `attachments`/
    `postback`. meta_messaging_webhook.py's own docstring already documents
    this exact case as skipped by the TEXT extractor. Phase 52: such a message is
    now stored as a placeholder CUSTOMER message ("[Customer sent an image]") by
    the attachment path instead of being dropped; the AI does not answer it."""
    payload = {
        "object": "page",
        "entry": [
            {
                "id": business_with_messenger["page_id"],
                "time": 1690000000000,
                "messaging": [
                    {
                        "sender": {"id": "psid-0012"},
                        "recipient": {"id": business_with_messenger["page_id"]},
                        "timestamp": 1690000000000,
                        "message": {
                            "mid": f"mid.{uuid.uuid4().hex}",
                            "attachments": [{"type": "image", "payload": {"url": "https://example.com/photo.jpg"}}],
                        },
                    }
                ],
            }
        ],
    }
    status, body = _post_webhook(payload)
    assert status == 200, body

    with SessionLocal() as db:
        (conversation,) = db.query(Conversation).filter(Conversation.business_id == business_with_messenger["business_id"]).all()
        messages = db.query(Message).filter(Message.conversation_id == conversation.id).all()
        assert [(m.sender_type, m.content) for m in messages] == [(MessageSenderType.CUSTOMER, "[Customer sent an image]")]


# ---------------------------------------------------------------------------
# Idempotency — real DB-level guarantee.
# ---------------------------------------------------------------------------


def test_identical_webhook_delivered_twice_creates_only_one_message(business_with_messenger):
    psid = "psid-0020"
    message_id = f"mid.{uuid.uuid4().hex}"
    payload = _build_payload(page_id=business_with_messenger["page_id"], psid=psid, message_id=message_id, text="Duplicate me")

    first_status, first_body = _post_webhook(payload)
    second_status, second_body = _post_webhook(payload)  # Meta's own documented "may deliver twice" behavior
    assert first_status == 200, first_body
    assert second_status == 200, second_body  # still acked, never an error to Meta

    with SessionLocal() as db:
        matches = db.query(Message).filter(Message.external_message_id == message_id).all()
        assert len(matches) == 1  # not two
        conversations = db.query(Conversation).filter(Conversation.business_id == business_with_messenger["business_id"]).all()
        assert len(conversations) == 1
        all_messages = db.query(Message).filter(Message.conversation_id == conversations[0].id).all()
        assert len(all_messages) == 2  # not four


def test_db_constraint_itself_rejects_a_second_row_with_the_same_external_message_id(business_with_messenger):
    """Bypasses the application-level pre-check entirely — proves the real
    backstop is the (shared, cross-channel) unique constraint, not just app
    logic a race could slip past."""
    message_id = f"mid.{uuid.uuid4().hex}"
    with SessionLocal() as db:
        customer = Customer(business_id=business_with_messenger["business_id"], name="Race Test")
        db.add(customer)
        db.flush()
        conversation = Conversation(
            business_id=business_with_messenger["business_id"], customer_id=customer.id, channel="messenger", status="open"
        )
        db.add(conversation)
        db.commit()
        conversation_id = conversation.id

        db.add(
            Message(
                conversation_id=conversation_id,
                sender_type=MessageSenderType.CUSTOMER,
                content="first",
                external_message_id=message_id,
            )
        )
        db.commit()

    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(
            Message(
                conversation_id=conversation_id,
                sender_type=MessageSenderType.CUSTOMER,
                content="second",
                external_message_id=message_id,
            )
        )
        db.commit()


# ---------------------------------------------------------------------------
# Unknown page_id — never crashes.
# ---------------------------------------------------------------------------


def test_unknown_page_id_is_acked_and_skipped_not_a_crash():
    payload = _build_payload(page_id="no-such-registered-page", psid="psid-9998", message_id=f"mid.{uuid.uuid4().hex}", text="hello?")
    status, body = _post_webhook(payload)
    assert status == 200, body  # still a real 200 ack — never turns an unrecognized page into an error Meta would retry


# ---------------------------------------------------------------------------
# Outgoing send — graceful fallback with no real page access token configured.
# ---------------------------------------------------------------------------


def test_send_message_gracefully_simulates_when_no_page_access_token_configured():
    from app.services.channels.messenger import MessengerChannelAdapter

    adapter = MessengerChannelAdapter()
    detail = adapter.send_message(psid="psid-1234567", text="hello", page_access_token="")
    assert "simulated" in detail
    assert "no real" in detail


# ---------------------------------------------------------------------------
# Cross-channel sanity check — a WhatsApp and a Messenger conversation for
# the SAME business stay correctly separate.
# ---------------------------------------------------------------------------


def test_whatsapp_and_messenger_conversations_for_the_same_business_never_cross_contaminate(business_with_messenger):
    from app.services.channels.whatsapp_webhook import process_webhook_payload as process_whatsapp_payload

    business_id = business_with_messenger["business_id"]
    phone_number_id = f"pnid-{uuid.uuid4().hex[:10]}"
    with SessionLocal() as db:
        db.add(Integration(business_id=business_id, type="whatsapp", config={"phone_number_id": phone_number_id}, enabled=True))
        db.commit()

    # Real Messenger message.
    mg_psid = "psid-cross-0001"
    mg_message_id = f"mid.{uuid.uuid4().hex}"
    mg_payload = _build_payload(page_id=business_with_messenger["page_id"], psid=mg_psid, message_id=mg_message_id, text="Messenger hello")
    status, body = _post_webhook(mg_payload)
    assert status == 200, body

    # Real WhatsApp message, same business, via the actual WhatsApp webhook pipeline.
    wa_id = "15559990123"
    wa_message_id = f"wamid.{uuid.uuid4().hex}"
    wa_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "15550001111", "phone_number_id": phone_number_id},
                            "contacts": [{"profile": {"name": "Cross Channel Test"}, "wa_id": wa_id}],
                            "messages": [
                                {"from": wa_id, "id": wa_message_id, "timestamp": "1690000000", "text": {"body": "WhatsApp hello"}, "type": "text"}
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    with SessionLocal() as db:
        process_whatsapp_payload(db, wa_payload)
        db.commit()

    with SessionLocal() as db:
        conversations = db.query(Conversation).filter(Conversation.business_id == business_id).all()
        assert len(conversations) == 2
        channels = {c.channel for c in conversations}
        assert channels == {"messenger", "whatsapp"}

        identities = db.query(ChannelIdentity).filter(ChannelIdentity.business_id == business_id).all()
        assert len(identities) == 2
        by_channel = {i.channel: i for i in identities}
        assert by_channel["messenger"].external_ref == mg_psid
        assert by_channel["whatsapp"].external_ref == wa_id
        # Different customer_id per channel identity — no shared/merged customer.
        assert by_channel["messenger"].customer_id != by_channel["whatsapp"].customer_id

        # Each conversation only has ITS OWN channel's message content.
        mg_conv = next(c for c in conversations if c.channel == "messenger")
        wa_conv = next(c for c in conversations if c.channel == "whatsapp")
        mg_msgs = db.query(Message).filter(Message.conversation_id == mg_conv.id).all()
        wa_msgs = db.query(Message).filter(Message.conversation_id == wa_conv.id).all()
        assert any(m.external_message_id == mg_message_id for m in mg_msgs)
        assert not any(m.external_message_id == wa_message_id for m in mg_msgs)
        assert any(m.external_message_id == wa_message_id for m in wa_msgs)
        assert not any(m.external_message_id == mg_message_id for m in wa_msgs)


def test_resend_qr_link_reaches_messenger_as_a_plain_link_through_the_real_webhook(business_with_messenger, monkeypatch):
    from app.services import qr_link_service
    from tests.integration._resend_channel_support import run_resend_scenario

    business_id, page_id = business_with_messenger["business_id"], business_with_messenger["page_id"]
    with SessionLocal() as db:
        integration = db.query(Integration).filter(Integration.business_id == business_id).one()
        integration.config = {"page_id": page_id, "page_access_token": "tok-test"}
        db.commit()

    psid = "psid-resend-1"
    build = lambda text: _build_payload(page_id=page_id, psid=psid, message_id=f"mid.{uuid.uuid4().hex}", text=text)  # noqa: E731
    out = run_resend_scenario(monkeypatch, business_id=business_id, post_webhook=_post_webhook,
                              first_payload=build("hello"), second_payload=build("send me my QR code"))
    assert len(out["captured"]) == 1, out["captured"]
    sent = out["captured"][0]
    assert sent["recipient"] == {"id": psid} and set(sent["message"]) == {"text"}, "plain text, no attachment upload"
    assert sent["message"]["text"] == out["stored_reply"]
    url = re.search(r"https?://\S+", sent["message"]["text"]).group(0)
    assert qr_link_service.verify_token(url.rsplit("/qr/", 1)[1]) == out["appointment_id"]
