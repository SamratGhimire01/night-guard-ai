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
import re
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
from app.services.conversation.response_templates import render

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
        assert render("handoff_addendum", "en") in agent_msg.content


def test_non_text_message_is_recorded_as_a_placeholder_and_status_only_webhooks_are_skipped(business_with_whatsapp):
    """extract_incoming_text_messages's own docstring documents two real,
    frequent Meta webhook shapes this codebase deliberately doesn't act on:
    a non-text message (image/sticker/button, `type != "text"`) and a
    delivery/read-receipt status webhook (`statuses` key, no `messages` key
    at all). Phase 52 changed the first: a non-text message is now STORED as a
    placeholder CUSTOMER message ("[Customer sent an image]") instead of being
    dropped without a trace (the AI still does not answer it); a status-only
    webhook is still skipped, never a 500 and never a conversation."""
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

    status, body = _post_webhook(status_only_payload)
    assert status == 200, body
    with SessionLocal() as db:
        assert db.query(Conversation).filter(Conversation.business_id == business_with_whatsapp["business_id"]).count() == 0, (
            "a status-only webhook must never create a conversation"
        )

    status, body = _post_webhook(non_text_payload)
    assert status == 200, body
    with SessionLocal() as db:
        (conversation,) = db.query(Conversation).filter(Conversation.business_id == business_with_whatsapp["business_id"]).all()
        messages = db.query(Message).filter(Message.conversation_id == conversation.id).all()
        assert [(m.sender_type, m.content) for m in messages] == [(MessageSenderType.CUSTOMER, "[Customer sent an image]")]


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


def test_resend_qr_link_reaches_whatsapp_as_a_plain_link_through_the_real_webhook(business_with_whatsapp, monkeypatch):
    """Phase 14: real signed webhook -> real orchestrator -> the exact Graph API body a real send would POST. The reply
    is a plain text message whose body carries the QR-page link (WhatsApp auto-links it); nothing is uploaded."""
    from app.services import qr_link_service
    from tests.integration._resend_channel_support import run_resend_scenario

    business_id, phone_number_id = business_with_whatsapp["business_id"], business_with_whatsapp["phone_number_id"]
    with SessionLocal() as db:  # a token makes the real send path run (no token = a logged simulation, nothing POSTed)
        integration = db.query(Integration).filter(Integration.business_id == business_id).one()
        integration.config = {"phone_number_id": phone_number_id, "access_token": "tok-test"}
        db.commit()

    wa_id = "15551239001"
    build = lambda text: _build_payload(phone_number_id=phone_number_id, wa_id=wa_id, message_id=f"wamid.{uuid.uuid4().hex}", text=text)  # noqa: E731
    out = run_resend_scenario(monkeypatch, business_id=business_id, post_webhook=_post_webhook,
                              first_payload=build("hello"), second_payload=build("send me my QR code"))
    assert len(out["captured"]) == 1, out["captured"]
    sent = out["captured"][0]
    assert sent["type"] == "text" and sent["to"] == wa_id and "media" not in jsonlib.dumps(sent).lower()
    assert sent["text"]["body"] == out["stored_reply"], "what WhatsApp received is exactly what was stored/answered"
    url = re.search(r"https?://\S+", sent["text"]["body"]).group(0)
    assert qr_link_service.verify_token(url.rsplit("/qr/", 1)[1]) == out["appointment_id"]


# ---------------------------------------------------------------------------
# Typing indicator (Meta: POST /messages with status=read + typing_indicator)
# ---------------------------------------------------------------------------


def test_typing_indicator_posts_metas_documented_body(monkeypatch):
    from app.services.channels import whatsapp as whatsapp_module

    calls = []
    monkeypatch.setattr(
        whatsapp_module.httpx, "post", lambda url, **kw: calls.append((url, kw)) or _FakeHttpxResponse(200, {"success": True})
    )
    detail = whatsapp_module.WhatsAppChannelAdapter().send_typing_indicator(
        message_id="wamid.IN1", phone_number_id="12345", access_token="tok"
    )
    assert detail == "sent"
    url, kw = calls[0]
    assert url.endswith("/12345/messages")
    assert kw["json"] == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.IN1",
        "typing_indicator": {"type": "text"},
    }
    assert kw["headers"] == {"Authorization": "Bearer tok"}


def test_typing_indicator_never_raises_and_is_skipped_without_a_token(monkeypatch):
    import httpx

    from app.services.channels import whatsapp as whatsapp_module

    adapter = whatsapp_module.WhatsAppChannelAdapter()

    def _boom(url, **kw):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(whatsapp_module.httpx, "post", _boom)
    assert adapter.send_typing_indicator(message_id="m", phone_number_id="1", access_token="tok").startswith("failed")

    monkeypatch.setattr(whatsapp_module.httpx, "post", lambda *a, **k: _FakeHttpxResponse(400, {}))
    assert adapter.send_typing_indicator(message_id="m", phone_number_id="1", access_token="tok") == "failed: HTTP 400"

    monkeypatch.setattr(settings, "whatsapp_access_token", "")
    monkeypatch.setattr(whatsapp_module.httpx, "post", _boom)  # would raise if it were reached
    assert adapter.send_typing_indicator(message_id="m", phone_number_id="1").startswith("simulated")


def test_webhook_shows_typing_once_per_new_message_and_not_for_duplicates(business_with_whatsapp, monkeypatch):
    from app.services.channels import whatsapp_webhook

    typed = []
    monkeypatch.setattr(
        whatsapp_webhook._adapter, "send_typing_indicator", lambda **kw: typed.append(kw["message_id"]) or "sent"
    )
    message_id = f"wamid.{uuid.uuid4().hex}"
    payload = _build_payload(
        phone_number_id=business_with_whatsapp["phone_number_id"], wa_id="15551230011", message_id=message_id, text="hi"
    )
    assert _post_webhook(payload)[0] == 200
    assert _post_webhook(payload)[0] == 200  # Meta redelivery
    assert typed == [message_id]


# ---------------------------------------------------------------------------
# Phase 50 — WhatsApp usernames: Meta omits the sender's phone number (`from` / `wa_id`) and sends only a business-scoped
# user id (BSUID). Found live: such a user's "hi" was silently dropped, so they "couldn't chat".
# ---------------------------------------------------------------------------

# byte-for-byte the shape Meta really delivered (ngrok inspector capture), only the phone_number_id/message id swapped
_BSUID = "NP.28874496152238272"


def _bsuid_only_payload(*, phone_number_id: str, message_id: str, text: str = "hi", bsuid: str = _BSUID) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1393681432091899",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "9779840923251", "phone_number_id": phone_number_id},
                            "contacts": [{"profile": {"name": "Aadarsha Ghimire", "username": "aadarshaghimire"}, "user_id": bsuid}],
                            "messages": [{"from_user_id": bsuid, "id": message_id, "timestamp": "1789983258", "text": {"body": text}, "type": "text"}],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def test_extract_reads_a_message_from_a_user_with_no_phone_number():
    from app.services.channels.whatsapp_webhook import extract_incoming_text_messages

    (msg,) = extract_incoming_text_messages(_bsuid_only_payload(phone_number_id="pn1", message_id="wamid.x"))
    assert msg["wa_id"] == _BSUID and msg["bsuid"] == _BSUID  # reply address falls back to the BSUID
    assert msg["contact_name"] == "Aadarsha Ghimire" and msg["text"] == "hi" and msg["phone_number_id"] == "pn1"


def test_extract_prefers_the_phone_number_when_meta_sends_both():
    from app.services.channels.whatsapp_webhook import extract_incoming_text_messages

    payload = _build_payload(phone_number_id="pn1", wa_id="9779823045928", message_id="wamid.y", text="Yo", contact_name="Samrat")
    payload["entry"][0]["changes"][0]["value"]["messages"][0]["from_user_id"] = "NP.2883195738732363"
    payload["entry"][0]["changes"][0]["value"]["contacts"][0]["user_id"] = "NP.2883195738732363"
    (msg,) = extract_incoming_text_messages(payload)
    assert msg["wa_id"] == "9779823045928" and msg["bsuid"] == "NP.2883195738732363" and msg["contact_name"] == "Samrat"


def test_bsuid_only_user_gets_a_conversation_and_a_reply_addressed_by_recipient(business_with_whatsapp, monkeypatch):
    from app.services.channels.whatsapp import WhatsAppChannelAdapter

    sent: list[dict] = []
    monkeypatch.setattr(WhatsAppChannelAdapter, "send_message", lambda self, **kw: (sent.append(kw), "sent")[1])
    status, body = _post_webhook(
        _bsuid_only_payload(phone_number_id=business_with_whatsapp["phone_number_id"], message_id=f"wamid.{uuid.uuid4().hex}")
    )
    assert status == 200, body
    assert [s["to"] for s in sent] == [_BSUID], "the reply goes to the BSUID (send_message turns it into `recipient`)"
    with SessionLocal() as db:
        (conversation,) = db.query(Conversation).filter(Conversation.business_id == business_with_whatsapp["business_id"]).all()
        assert db.query(Message).filter(Message.conversation_id == conversation.id).count() == 2  # customer + agent


def test_a_bsuid_is_linked_to_the_phone_identity_so_a_later_username_user_keeps_their_conversation(
    business_with_whatsapp, monkeypatch
):
    from app.services.channels.whatsapp import WhatsAppChannelAdapter

    monkeypatch.setattr(WhatsAppChannelAdapter, "send_message", lambda self, **kw: "sent")
    pnid, bsuid, phone = business_with_whatsapp["phone_number_id"], "NP.4444444444444", "9779800000042"
    both = _build_payload(phone_number_id=pnid, wa_id=phone, message_id=f"wamid.{uuid.uuid4().hex}", text="hello")
    both["entry"][0]["changes"][0]["value"]["messages"][0]["from_user_id"] = bsuid
    assert _post_webhook(both)[0] == 200
    assert _post_webhook(_bsuid_only_payload(phone_number_id=pnid, message_id=f"wamid.{uuid.uuid4().hex}", bsuid=bsuid))[0] == 200
    with SessionLocal() as db:
        conversations = db.query(Conversation).filter(Conversation.business_id == business_with_whatsapp["business_id"]).all()
        assert len(conversations) == 1, "same person, one customer, one conversation"
        assert db.query(Message).filter(Message.conversation_id == conversations[0].id).count() == 4


def test_send_message_addresses_a_bsuid_by_recipient_on_a_new_enough_api_version_and_a_phone_by_to(monkeypatch):
    import io
    import json as j
    import urllib.request

    from app.services.channels.whatsapp import WhatsAppChannelAdapter

    seen: list[tuple[str, dict]] = []

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout=None):
        seen.append((request.full_url, j.loads(request.data)))
        return _Resp(b'{"messages":[{"id":"wamid.ok"}]}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(settings, "whatsapp_api_version", "v20.0")
    adapter = WhatsAppChannelAdapter()
    adapter.send_message(to=_BSUID, text="hi", phone_number_id="PN", access_token="tok")
    adapter.send_message(to="9779840923250", text="hi", phone_number_id="PN", access_token="tok")
    (bs_url, bs_body), (ph_url, ph_body) = seen
    assert "/v26.0/PN/messages" in bs_url and bs_body["recipient"] == _BSUID and "to" not in bs_body
    assert "/v20.0/PN/messages" in ph_url and ph_body["to"] == "9779840923250" and "recipient" not in ph_body

    monkeypatch.setattr(settings, "whatsapp_api_version", "v27.0")  # never downgraded
    adapter.send_message(to=_BSUID, text="hi", phone_number_id="PN", access_token="tok")
    assert "/v27.0/PN/messages" in seen[-1][0]


def test_proactive_send_prefers_the_phone_identity_over_a_bsuid_alias(business_with_whatsapp, monkeypatch):
    from app.db.models.channel_identity import ChannelIdentity
    from app.services.channels import proactive
    from app.services.channels.whatsapp import WhatsAppChannelAdapter

    sent: list[dict] = []
    monkeypatch.setattr(WhatsAppChannelAdapter, "send_message", lambda self, **kw: (sent.append(kw), "sent")[1])
    with SessionLocal() as db:
        biz = business_with_whatsapp["business_id"]
        customer = Customer(business_id=biz, name="Both")
        db.add(customer)
        db.flush()
        db.add_all(
            [
                ChannelIdentity(business_id=biz, channel="whatsapp", external_ref="NP.999", customer_id=customer.id),
                ChannelIdentity(business_id=biz, channel="whatsapp", external_ref="9779800000077", customer_id=customer.id),
            ]
        )
        conv = Conversation(business_id=biz, customer_id=customer.id, channel="whatsapp", status="open")
        db.add(conv)
        db.commit()
        pn = business_with_whatsapp["phone_number_id"]
        integ = db.query(Integration).filter(Integration.business_id == biz, Integration.type == "whatsapp").one()
        integ.config = {"phone_number_id": pn, "access_token": "t"}
        db.commit()
        proactive.send_to_conversation(db, conversation=conv, text="Payment received")
    assert [s["to"] for s in sent] == ["9779800000077"]


# ---------------------------------------------------------------------------
# Message-bubble split (WhatsApp delivery-time only) -- see
# style_checks.split_into_bubbles / whatsapp_webhook._deliver_whatsapp_reply. "cancellation" intent with no
# cancellation_request field is used throughout below specifically because it passes
# classification.response straight through untouched -- no tool dispatch (needs a real
# cancellation_request), no handoff addendum (not in handoff_service._INFO_INTENTS/COMPLAINT/
# HUMAN_HANDOFF), no format_service_list rewrite (only SERVICE_QUESTION/PRICING_QUESTION/
# GENERAL_QUESTION get that) -- so the text this test controls is exactly the text the style
# guard validates and exactly the text that must reach the split, with nothing else appended.
# ---------------------------------------------------------------------------


def _set_stub_response(monkeypatch, text: str, intent: str = "cancellation") -> None:
    import app.services.conversation.intent as intent_module

    class _StubChatWithText:
        def chat(self, messages):
            return jsonlib.dumps({"intent": intent, "response": text})

    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: _StubChatWithText())


def test_long_reply_is_split_into_up_to_three_real_whatsapp_bubbles(business_with_whatsapp, monkeypatch):
    from app.services.channels.whatsapp import WhatsAppChannelAdapter

    long_reply = (
        "We can absolutely help you get that rescheduled to a time that works better for you. "
        "Our team looks over every request personally to make sure nothing about your original booking gets lost "
        "in the process, so please do not worry about starting over from scratch. "
        "Once you tell us the new day and time you would like, we will confirm it back to you right away. "
        "We really do want to make this as easy as possible for you."
    )
    assert len(long_reply.split()) > 40  # comfortably over the split threshold, not just brushing it

    sent: list[dict] = []
    monkeypatch.setattr(WhatsAppChannelAdapter, "send_message", lambda self, **kw: (sent.append(kw), "sent wamid=x")[1])
    _set_stub_response(monkeypatch, long_reply)

    status, body = _post_webhook(_build_payload(
        phone_number_id=business_with_whatsapp["phone_number_id"], wa_id="15551239001",
        message_id=f"wamid.{uuid.uuid4().hex}", text="Can I move my appointment?",
    ))
    assert status == 200, body

    assert 2 <= len(sent) <= 3, f"expected 2-3 real bubbles (BEFORE: one block) for a reply this long, got: {sent}"
    reconstructed = " ".join(s["text"] for s in sent)
    assert reconstructed == long_reply, "splitting must never drop, reorder, or alter any of the validated text"
    for s in sent:
        assert s["text"] != long_reply, "AFTER: each bubble is a genuine fragment, never the whole reply repeated"

    with SessionLocal() as db:
        (conversation,) = db.query(Conversation).filter(Conversation.business_id == business_with_whatsapp["business_id"]).all()
        agent_msg = db.query(Message).filter(
            Message.conversation_id == conversation.id, Message.sender_type == MessageSenderType.AGENT
        ).one()
        assert agent_msg.content == long_reply, "persistence stays exactly ONE row with the FULL text -- split only at send time"
        assert agent_msg.delivery_status == "sent"


def test_short_reply_is_not_split(business_with_whatsapp, monkeypatch):
    from app.services.channels.whatsapp import WhatsAppChannelAdapter

    short_reply = "Sure, what day works best for you?"
    sent: list[dict] = []
    monkeypatch.setattr(WhatsAppChannelAdapter, "send_message", lambda self, **kw: (sent.append(kw), "sent wamid=y")[1])
    _set_stub_response(monkeypatch, short_reply)

    status, body = _post_webhook(_build_payload(
        phone_number_id=business_with_whatsapp["phone_number_id"], wa_id="15551239002",
        message_id=f"wamid.{uuid.uuid4().hex}", text="Can I move my appointment?",
    ))
    assert status == 200, body
    assert len(sent) == 1 and sent[0]["text"] == short_reply, "a short reply is never turned into pointless bubbles"


def test_bubble_split_runs_on_the_style_repaired_text_never_the_raw_scripted_draft(business_with_whatsapp, monkeypatch):
    """The ground rule: split only ever happens AFTER fact_validator and the style guard have
    already run on the full joined text. Proven here, not assumed: the raw draft below has a
    real rule-4 banned scripted phrase as its FIRST sentence -- if splitting ran before/instead
    of style repair, that phrase would still show up in bubble 1. It must not appear anywhere."""
    from app.services.channels.whatsapp import WhatsAppChannelAdapter

    s1 = "Thank you for reaching out to us!"  # rule 4 banned phrase -- style guard must strip this whole sentence
    s2 = "We would be glad to help you get everything sorted for your visit."
    s3 = "Our team looks forward to welcoming you and making sure your appointment goes smoothly from start to finish."
    s4 = "Please let us know if there is a particular time of day that works best for your schedule."
    s5 = "We want to make sure the whole experience feels easy and stress free for you."
    raw_draft = f"{s1} {s2} {s3} {s4} {s5}"
    expected_repaired = f"{s2} {s3} {s4} {s5}"
    assert len(expected_repaired.split()) > 40  # still long enough that splitting should still trigger after repair

    sent: list[dict] = []
    monkeypatch.setattr(WhatsAppChannelAdapter, "send_message", lambda self, **kw: (sent.append(kw), "sent wamid=z")[1])
    _set_stub_response(monkeypatch, raw_draft)

    status, body = _post_webhook(_build_payload(
        phone_number_id=business_with_whatsapp["phone_number_id"], wa_id="15551239003",
        message_id=f"wamid.{uuid.uuid4().hex}", text="Can I move my appointment?",
    ))
    assert status == 200, body

    assert len(sent) >= 2, "the repaired text is still over the split threshold"
    reconstructed = " ".join(s["text"] for s in sent)
    assert reconstructed == expected_repaired, "must split the STYLE-REPAIRED text, never the raw scripted draft"
    assert not any("thank you for reaching out to us" in s["text"].lower() for s in sent), (
        "a banned scripted phrase must never survive into any bubble sent to a real customer"
    )

    with SessionLocal() as db:
        (conversation,) = db.query(Conversation).filter(Conversation.business_id == business_with_whatsapp["business_id"]).all()
        agent_msg = db.query(Message).filter(
            Message.conversation_id == conversation.id, Message.sender_type == MessageSenderType.AGENT
        ).one()
        assert agent_msg.content == expected_repaired


def test_worst_of_n_delivery_status_is_failed_when_any_bubble_fails(business_with_whatsapp, monkeypatch):
    """Documents the worst-of-N collapse: bubble 1 sends fine, bubble 2 genuinely fails --
    sending stops immediately (bubble 3 is never attempted, since the reply already can't
    arrive complete/in-order), and the ONE delivery_status column on the ONE Message row
    reflects the worst outcome (failed), not the first bubble's success."""
    from app.services.channels.whatsapp import WhatsAppChannelAdapter

    long_reply = (
        "We can absolutely help you get that rescheduled to a time that works better for you. "
        "Our team looks over every request personally to make sure nothing about your original booking gets lost "
        "in the process, so please do not worry about starting over from scratch. "
        "Once you tell us the new day and time you would like, we will confirm it back to you right away. "
        "We really do want to make this as easy as possible for you."
    )
    calls: list[dict] = []

    def _flaky_send(self, **kw):
        calls.append(kw)
        return "sent wamid=ok" if len(calls) == 1 else "failed: HTTP 500"

    monkeypatch.setattr(WhatsAppChannelAdapter, "send_message", _flaky_send)
    _set_stub_response(monkeypatch, long_reply)

    status, body = _post_webhook(_build_payload(
        phone_number_id=business_with_whatsapp["phone_number_id"], wa_id="15551239004",
        message_id=f"wamid.{uuid.uuid4().hex}", text="Can I move my appointment?",
    ))
    assert status == 200, body
    assert len(calls) == 2, "stops sending further bubbles once one has genuinely failed"

    with SessionLocal() as db:
        (conversation,) = db.query(Conversation).filter(Conversation.business_id == business_with_whatsapp["business_id"]).all()
        agent_msg = db.query(Message).filter(
            Message.conversation_id == conversation.id, Message.sender_type == MessageSenderType.AGENT
        ).one()
        assert agent_msg.delivery_status == "failed"
        assert agent_msg.content == long_reply, "the persisted text is unaffected by a partial delivery failure"
