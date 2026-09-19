"""Phase 22 — WhatsApp adapter (app/services/channels/whatsapp.py,
app/services/channels/whatsapp_webhook.py, app/api/routes/webhooks.py).

Stubbed ChatProvider/EmbeddingProvider (same discipline as every prior
channel/conversation test) for fast, free coverage of the real wiring: HMAC
signature verification (real crypto, not stubbed), the GET verification
handshake, the shared conversation-engine code path (proven the same way
Phase 21's widget tests proved it — a genuine no-knowledge question correctly
triggers Phase 19's real handoff logic through this channel too), real
DB-level idempotency, unknown phone_number_id handling, and the outgoing-send
graceful fallback when WHATSAPP_ACCESS_TOKEN is absent (true in this test
environment — no production Meta Business account exists).

No real Meta account exists to test against — every request here is a
documented, correctly-HMAC-signed payload matching Meta's real Cloud API
webhook contract, POSTed at the real, production `/api/v1/webhooks/whatsapp`
route (not a separate mock endpoint) using this codebase's own real
WHATSAPP_APP_SECRET/WHATSAPP_VERIFY_TOKEN dev values.
"""

import hashlib
import hmac
import json as jsonlib
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.db.models.customer import Customer
from app.db.models.integration import Integration
from app.main import app

client = TestClient(app)

WEBHOOK_URL = "/api/v1/webhooks/whatsapp"


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
    key = (secret if secret is not None else settings.whatsapp_app_secret).encode("utf-8")
    return "sha256=" + hmac.new(key, raw_body, hashlib.sha256).hexdigest()


def _post_webhook(payload: dict, *, signature: str | None = "__real__") -> tuple[int, dict]:
    raw_body = jsonlib.dumps(payload).encode("utf-8")
    sig = _sign(raw_body) if signature == "__real__" else signature
    headers = {"content-type": "application/json"}
    if sig is not None:
        headers["x-hub-signature-256"] = sig
    resp = client.post(WEBHOOK_URL, content=raw_body, headers=headers)
    return resp.status_code, (resp.json() if resp.content else {})


def _build_payload(*, phone_number_id: str, wa_id: str, message_id: str, text: str, contact_name: str = "Test User") -> dict:
    """Real Meta Cloud API webhook envelope shape."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "15550001111", "phone_number_id": phone_number_id},
                            "contacts": [{"profile": {"name": contact_name}, "wa_id": wa_id}],
                            "messages": [
                                {"from": wa_id, "id": message_id, "timestamp": "1690000000", "text": {"body": text}, "type": "text"}
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


@pytest.fixture
def business_with_whatsapp():
    email = _unique_email("wa-owner")
    resp = client.post(
        "/api/v1/auth/register",
        json={"business_name": "WhatsApp Test Biz", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    assert resp.status_code == 201, resp.text
    business_id = uuid.UUID(resp.json()["business_id"])
    phone_number_id = f"pnid-{uuid.uuid4().hex[:10]}"

    with SessionLocal() as db:
        db.add(Integration(business_id=business_id, type="whatsapp", config={"phone_number_id": phone_number_id}, enabled=True))
        db.commit()

    yield {"business_id": business_id, "phone_number_id": phone_number_id}

    with SessionLocal() as db:
        b = db.get(Business, business_id)
        if b is not None:
            db.delete(b)
        db.commit()


# ---------------------------------------------------------------------------
# Signature verification — real HMAC, not stubbed.
# ---------------------------------------------------------------------------


def test_valid_signature_is_accepted(business_with_whatsapp):
    wa_id = "15551230001"
    payload = _build_payload(
        phone_number_id=business_with_whatsapp["phone_number_id"], wa_id=wa_id, message_id=f"wamid.{uuid.uuid4().hex}", text="Hi there"
    )
    status, body = _post_webhook(payload)
    assert status == 200, body
    assert body == {"status": "ok"}


def test_tampered_payload_with_stale_signature_is_rejected(business_with_whatsapp):
    wa_id = "15551230002"
    message_id = f"wamid.{uuid.uuid4().hex}"
    original = _build_payload(phone_number_id=business_with_whatsapp["phone_number_id"], wa_id=wa_id, message_id=message_id, text="Hi there")
    raw_original = jsonlib.dumps(original).encode("utf-8")
    real_signature = _sign(raw_original)

    tampered = dict(original)
    tampered["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = "Send me a free gift card"
    raw_tampered = jsonlib.dumps(tampered).encode("utf-8")

    resp = client.post(WEBHOOK_URL, content=raw_tampered, headers={"content-type": "application/json", "x-hub-signature-256": real_signature})
    assert resp.status_code == 401, resp.text
    assert resp.json()["error"]["type"] == "unauthorized"

    with SessionLocal() as db:
        assert db.query(Message).filter(Message.external_message_id == message_id).count() == 0


def test_missing_signature_header_is_rejected(business_with_whatsapp):
    payload = _build_payload(
        phone_number_id=business_with_whatsapp["phone_number_id"], wa_id="15551230003", message_id=f"wamid.{uuid.uuid4().hex}", text="hi"
    )
    status, body = _post_webhook(payload, signature=None)
    assert status == 401, body


def test_wrong_secret_signature_is_rejected(business_with_whatsapp):
    payload = _build_payload(
        phone_number_id=business_with_whatsapp["phone_number_id"], wa_id="15551230004", message_id=f"wamid.{uuid.uuid4().hex}", text="hi"
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
        params={"hub.mode": "subscribe", "hub.verify_token": settings.whatsapp_verify_token, "hub.challenge": "1234567890"},
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


def test_incoming_message_flows_through_the_real_shared_orchestrator(business_with_whatsapp):
    wa_id = "15551230010"
    message_id = f"wamid.{uuid.uuid4().hex}"
    payload = _build_payload(
        phone_number_id=business_with_whatsapp["phone_number_id"],
        wa_id=wa_id,
        message_id=message_id,
        text="Do you offer teeth whitening?",
        contact_name="Jordan Real",
    )
    status, body = _post_webhook(payload)
    assert status == 200, body

    with SessionLocal() as db:
        conversations = db.query(Conversation).filter(Conversation.business_id == business_with_whatsapp["business_id"]).all()
        assert len(conversations) == 1
        assert conversations[0].channel == "whatsapp"

        messages = db.query(Message).filter(Message.conversation_id == conversations[0].id).order_by(Message.created_at).all()
        assert len(messages) == 2  # customer + agent — the exact same two-message shape every other channel produces
        customer_msg, agent_msg = messages
        assert customer_msg.external_message_id == message_id
        assert customer_msg.detected_intent == "general_question"
        # This business has zero knowledge documents, so a general_question
        # here correctly triggers Phase 19's real handoff logic — proof this
        # is the SAME real orchestrator pipeline the website widget uses
        # (Phase 21), not a parallel/simplified copy of it.
        assert "I've also let our team know, so a real person will follow up with you." in agent_msg.content


def test_non_text_message_and_status_only_webhooks_are_acked_and_skipped_not_a_crash(business_with_whatsapp):
    """extract_incoming_text_messages's own docstring documents two real,
    frequent Meta webhook shapes this codebase deliberately doesn't act on:
    a non-text message (image/sticker/button, `type != "text"`) and a
    delivery/read-receipt status webhook (`statuses` key, no `messages` key
    at all) — both silently skipped, never a 500. Until now nothing proved
    either one: a happy-path-only gap."""
    non_text_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "15550001111", "phone_number_id": business_with_whatsapp["phone_number_id"]},
                            "contacts": [{"profile": {"name": "Test User"}, "wa_id": "15551230099"}],
                            "messages": [
                                {
                                    "from": "15551230099",
                                    "id": f"wamid.{uuid.uuid4().hex}",
                                    "timestamp": "1690000000",
                                    "type": "image",
                                    "image": {"id": "media-id-123", "mime_type": "image/jpeg"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    status_only_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "15550001111", "phone_number_id": business_with_whatsapp["phone_number_id"]},
                            "statuses": [{"id": f"wamid.{uuid.uuid4().hex}", "status": "delivered", "timestamp": "1690000000"}],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    for payload in (non_text_payload, status_only_payload):
        status, body = _post_webhook(payload)
        assert status == 200, body

    with SessionLocal() as db:
        conversations = db.query(Conversation).filter(Conversation.business_id == business_with_whatsapp["business_id"]).all()
        assert conversations == [], "a non-text message or a status-only webhook must never create a conversation"


# ---------------------------------------------------------------------------
# Idempotency — real DB-level guarantee.
# ---------------------------------------------------------------------------


def test_identical_webhook_delivered_twice_creates_only_one_message(business_with_whatsapp):
    wa_id = "15551230020"
    message_id = f"wamid.{uuid.uuid4().hex}"
    payload = _build_payload(phone_number_id=business_with_whatsapp["phone_number_id"], wa_id=wa_id, message_id=message_id, text="Duplicate me")

    first_status, first_body = _post_webhook(payload)
    second_status, second_body = _post_webhook(payload)  # Meta's own documented "may deliver twice" behavior
    assert first_status == 200, first_body
    assert second_status == 200, second_body  # still acked, never an error to Meta

    with SessionLocal() as db:
        matches = db.query(Message).filter(Message.external_message_id == message_id).all()
        assert len(matches) == 1  # not two
        conversations = db.query(Conversation).filter(Conversation.business_id == business_with_whatsapp["business_id"]).all()
        assert len(conversations) == 1
        all_messages = db.query(Message).filter(Message.conversation_id == conversations[0].id).all()
        assert len(all_messages) == 2  # not four


def test_db_constraint_itself_rejects_a_second_row_with_the_same_external_message_id(business_with_whatsapp):
    """Bypasses the application-level pre-check entirely — proves the real
    backstop is the unique constraint, not just app logic a race could slip
    past."""
    message_id = f"wamid.{uuid.uuid4().hex}"
    with SessionLocal() as db:
        customer = Customer(business_id=business_with_whatsapp["business_id"], name="Race Test")
        db.add(customer)
        db.flush()
        conversation = Conversation(
            business_id=business_with_whatsapp["business_id"], customer_id=customer.id, channel="whatsapp", status="open"
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
# Unknown phone_number_id — never crashes.
# ---------------------------------------------------------------------------


def test_unknown_phone_number_id_is_acked_and_skipped_not_a_crash():
    payload = _build_payload(phone_number_id="no-such-registered-number", wa_id="15559998888", message_id=f"wamid.{uuid.uuid4().hex}", text="hello?")
    status, body = _post_webhook(payload)
    assert status == 200, body  # still a real 200 ack — never turns an unrecognized number into an error Meta would retry


# ---------------------------------------------------------------------------
# Outgoing send — graceful fallback with no real access token configured.
# ---------------------------------------------------------------------------


def test_send_message_gracefully_simulates_when_no_access_token_configured(monkeypatch):
    from app.services.channels.whatsapp import WhatsAppChannelAdapter

    # Force the empty-token state directly rather than asserting on the
    # ambient settings.whatsapp_access_token — a real token configured in
    # this environment (dev or prod) must not make this test flaky/fail,
    # since the fallback behavior being tested applies whenever unset,
    # regardless of what happens to be in .env right now.
    monkeypatch.setattr(settings, "whatsapp_access_token", "")
    adapter = WhatsAppChannelAdapter()
    detail = adapter.send_message(to="15551234567", text="hello", phone_number_id="whatever")
    assert "simulated" in detail
    assert "no real" in detail


# ---------------------------------------------------------------------------
# Outgoing image send (QR resend) — real Media API two-step flow, researched
# against Meta's current docs: upload the bytes to get a real media id, then
# reference that id in a real image-type message. Never a single request.
# ---------------------------------------------------------------------------


class _FakeHttpxResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_send_image_message_gracefully_simulates_when_no_access_token_configured(monkeypatch):
    from app.services.channels.whatsapp import WhatsAppChannelAdapter

    monkeypatch.setattr(settings, "whatsapp_access_token", "")
    adapter = WhatsAppChannelAdapter()
    detail = adapter.send_image_message(
        to="15551234567",
        image_bytes=b"fake-png-bytes",
        mime_type="image/png",
        caption="x",
        phone_number_id="whatever",
    )
    assert "simulated" in detail
    assert "no real" in detail


def test_send_image_message_uploads_media_then_sends_real_image_message(monkeypatch):
    from app.services.channels import whatsapp as whatsapp_module

    calls = []

    def _fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/media"):
            assert kwargs["files"]["file"][1] == b"fake-png-bytes"
            assert kwargs["files"]["file"][2] == "image/png"
            assert kwargs["data"] == {"messaging_product": "whatsapp", "type": "image/png"}
            return _FakeHttpxResponse(200, {"id": "real-media-id-123"})
        assert kwargs["json"]["type"] == "image"
        assert kwargs["json"]["image"] == {"id": "real-media-id-123", "caption": "Show this at the clinic."}
        return _FakeHttpxResponse(200, {"messages": [{"id": "wamid.ABC123"}]})

    monkeypatch.setattr(whatsapp_module.httpx, "post", _fake_post)

    adapter = whatsapp_module.WhatsAppChannelAdapter()
    detail = adapter.send_image_message(
        to="15551234567",
        image_bytes=b"fake-png-bytes",
        mime_type="image/png",
        caption="Show this at the clinic.",
        phone_number_id="12345",
        access_token="real-token",
    )
    assert detail == "sent wamid=wamid.ABC123"
    assert len(calls) == 2, "must be exactly two real calls: upload, then send"
    assert calls[0][0].endswith("/12345/media")
    assert calls[1][0].endswith("/12345/messages")


def test_send_image_message_fails_honestly_when_media_upload_rejected(monkeypatch):
    from app.services.channels import whatsapp as whatsapp_module

    monkeypatch.setattr(
        whatsapp_module.httpx, "post", lambda url, **kwargs: _FakeHttpxResponse(400, {"error": {"message": "bad"}})
    )

    adapter = whatsapp_module.WhatsAppChannelAdapter()
    detail = adapter.send_image_message(
        to="15551234567",
        image_bytes=b"x",
        mime_type="image/png",
        caption="x",
        phone_number_id="12345",
        access_token="tok",
    )
    assert detail.startswith("failed:")
