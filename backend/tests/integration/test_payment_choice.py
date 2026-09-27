# ruff: noqa: F811  (fixtures imported from the Phase 44 suite are re-declared as test arguments — the pytest idiom)
"""Real payment-flow improvements on top of Phase 44: a business can enable eSewa AND Khalti together and the chat
customer chooses; the payment link also comes as a QR (chat page + email); and a gateway-VERIFIED completed payment
sends a proactive "payment received" message back into the original conversation/channel.

Gateway network calls are stubbed at payment_service._PROVIDERS (same seam as test_payments.py); the real sandbox
walkthrough for both gateways is documented in PHASE_STATUS.md.
"""

import json
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.db.models.integration import Integration
from app.db.models.payment import Payment, PaymentStatus
from app.main import app
from app.services import payment_service
from app.services.channels.whatsapp import WhatsAppChannelAdapter
from app.services.payments.base import PaymentInitiation, PaymentVerification

# fixtures + helpers reused as-is from the Phase 44 suite
from tests.integration.test_payments import (  # noqa: F401
    _auth_header,
    _FakeProvider,
    premium_npr_ready,
    two_businesses,
)

client = TestClient(app)


class _Gateway(_FakeProvider):
    def __init__(self, url: str, ref: str | None):
        super().__init__()
        self.initiate_result = PaymentInitiation(payment_url=url, gateway_reference=ref)
        self.initiated = 0

    def initiate_payment(self, **kwargs):
        self.initiated += 1
        return super().initiate_payment(**kwargs)


@pytest.fixture
def gateways(monkeypatch):
    esewa = _Gateway("https://esewa.fake/redirect/abc", None)
    khalti = _Gateway("https://khalti.fake/?pidx=P123", "P123")
    monkeypatch.setitem(payment_service._PROVIDERS, "esewa", esewa)
    monkeypatch.setitem(payment_service._PROVIDERS, "khalti", khalti)
    return {"esewa": esewa, "khalti": khalti}


class _Chat:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        return self.reply


@pytest.fixture
def chat(monkeypatch):
    import app.services.conversation.intent as intent_module
    import app.services.conversation.orchestrator as orchestrator_module

    class _Embed:
        def embed(self, texts):
            return [[0.01] * 1536 for _ in texts]

    stub = _Chat("")
    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: stub)
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _Embed())
    return stub


def _next_monday() -> date:
    today = date.today()
    return today + timedelta(days=(0 - today.weekday()) % 7 or 7)


def _booking_reply() -> str:
    return json.dumps(
        {
            "intent": "booking",
            "response": "Let me check.",
            "booking_request": {"service": "Root Canal", "date": _next_monday().isoformat(), "time": "14:00"},
        }
    )


def _set_providers(ctx, providers: list[str]):
    resp = client.patch(
        "/api/v1/business/payment-settings",
        json={"payment_collection_enabled": True, "payment_providers": providers},
        headers=_auth_header(ctx["token_a"]),
    )
    assert resp.status_code == 200, resp.text
    return resp


def _customer_with_email(ctx) -> uuid.UUID:
    resp = client.post(
        "/api/v1/customers",
        json={"name": "Chat Customer", "email": f"cc-{uuid.uuid4().hex[:8]}@example.com"},
        headers=_auth_header(ctx["token_a"]),
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


def _conversation(ctx, customer_id: uuid.UUID, channel: str = "website") -> uuid.UUID:
    with SessionLocal() as db:
        conv = Conversation(business_id=ctx["business_id_a"], customer_id=customer_id, channel=channel, status="open")
        db.add(conv)
        db.commit()
        return conv.id


def _say(ctx, conversation_id: uuid.UUID, text: str) -> dict:
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", headers=_auth_header(ctx["token_a"]), json={"content": text}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _payments(ctx) -> list[Payment]:
    with SessionLocal() as db:
        return list(db.query(Payment).filter(Payment.business_id == ctx["business_id_a"]).all())


# --- settings ---------------------------------------------------------------


def test_both_gateways_can_be_enabled_and_disabling_clears_them(premium_npr_ready):
    resp = _set_providers(premium_npr_ready, ["khalti", "esewa", "esewa"])
    assert resp.json()["payment_providers"] == ["esewa", "khalti"]  # de-duplicated, stable order

    off = client.patch(
        "/api/v1/business/payment-settings",
        json={"payment_collection_enabled": False, "payment_providers": ["esewa"]},
        headers=_auth_header(premium_npr_ready["token_a"]),
    )
    assert off.json()["payment_providers"] == []


def test_settings_reject_enabling_with_no_gateway_or_an_unknown_one(premium_npr_ready):
    for providers in ([], ["paypal"]):
        resp = client.patch(
            "/api/v1/business/payment-settings",
            json={"payment_collection_enabled": True, "payment_providers": providers},
            headers=_auth_header(premium_npr_ready["token_a"]),
        )
        assert resp.status_code == 422, resp.text


# --- Part 1: the customer chooses -------------------------------------------


def test_chat_asks_which_gateway_and_creates_the_request_through_the_answer(premium_npr_ready, gateways, chat):
    ctx = premium_npr_ready
    _set_providers(ctx, ["esewa", "khalti"])
    chat.reply = _booking_reply()
    conv = _conversation(ctx, _customer_with_email(ctx))

    booked = _say(ctx, conv, "Root canal next Monday 2pm please")
    assert "eSewa or Khalti" in booked["response"]
    assert "9000.00" in booked["response"]
    assert _payments(ctx) == [], "no payment request exists until the customer chooses"
    assert gateways["esewa"].initiated == gateways["khalti"].initiated == 0
    with SessionLocal() as db:
        assert db.get(Conversation, conv).payment_choice_appointment_id is not None

    calls_before = chat.calls
    answer = _say(ctx, conv, "khalti please")
    assert chat.calls == calls_before, "a clear gateway answer is resolved deterministically, no LLM call"
    (payment,) = _payments(ctx)
    assert payment.provider == "khalti" and payment.gateway_reference == "P123"
    assert gateways["khalti"].initiated == 1 and gateways["esewa"].initiated == 0
    assert "https://khalti.fake/?pidx=P123" in answer["response"]
    assert f"/pay-qr/{payment.id}" in answer["response"]
    assert payment.conversation_id == conv
    with SessionLocal() as db:
        assert db.get(Conversation, conv).payment_choice_appointment_id is None


def test_esewa_answer_uses_esewa_and_an_ambiguous_answer_keeps_asking(premium_npr_ready, gateways, chat):
    ctx = premium_npr_ready
    _set_providers(ctx, ["esewa", "khalti"])
    chat.reply = _booking_reply()
    conv = _conversation(ctx, _customer_with_email(ctx))
    _say(ctx, conv, "book root canal monday 2pm")

    chat.reply = json.dumps({"intent": "general_question", "response": "Either works!"})
    calls = chat.calls
    both = _say(ctx, conv, "eSewa or Khalti, which is faster?")
    assert chat.calls == calls + 1, "naming both is a question, so it goes to the normal LLM flow"
    assert "pay-qr" not in both["response"]
    assert _payments(ctx) == []
    with SessionLocal() as db:
        assert db.get(Conversation, conv).payment_choice_appointment_id is not None, "still waiting for a real answer"

    _say(ctx, conv, "e-sewa")
    (payment,) = _payments(ctx)
    assert payment.provider == "esewa" and gateways["esewa"].initiated == 1


def test_single_gateway_business_never_asks_and_gives_link_plus_qr(premium_npr_ready, gateways, chat):
    ctx = premium_npr_ready  # fixture enables esewa only
    chat.reply = _booking_reply()
    conv = _conversation(ctx, _customer_with_email(ctx))
    booked = _say(ctx, conv, "root canal monday 2pm")
    (payment,) = _payments(ctx)
    assert payment.provider == "esewa"
    assert "eSewa or Khalti" not in booked["response"]
    assert "https://esewa.fake/redirect/abc" in booked["response"]
    assert f"/pay-qr/{payment.id}" in booked["response"]
    assert payment.conversation_id == conv


def test_api_booking_with_both_enabled_cannot_ask_so_uses_the_first_gateway(premium_npr_ready, gateways):
    ctx = premium_npr_ready
    _set_providers(ctx, ["esewa", "khalti"])
    resp = client.post(
        "/api/v1/appointments",
        json={
            "customer_id": str(ctx["customer_id"]),
            "service_id": str(ctx["deposit_service_id"]),
            "scheduled_at": f"{_next_monday().isoformat()}T10:00:00Z",
        },
        headers=_auth_header(ctx["token_a"]),
    )
    assert resp.status_code == 201, resp.text
    (payment,) = _payments(ctx)
    assert payment.provider == "esewa" and payment.conversation_id is None


# --- Part 2: the QR ----------------------------------------------------------


def test_payment_qr_page_encodes_the_real_payment_url_and_only_while_pending(premium_npr_ready, gateways, monkeypatch):
    import app.api.routes.qr_view as qr_view

    ctx = premium_npr_ready
    encoded: list[str] = []
    real = qr_view.generate_qr_png
    monkeypatch.setattr(qr_view, "generate_qr_png", lambda data: (encoded.append(data), real(data))[1])

    client.post(
        "/api/v1/appointments",
        json={
            "customer_id": str(ctx["customer_id"]),
            "service_id": str(ctx["deposit_service_id"]),
            "scheduled_at": f"{_next_monday().isoformat()}T10:00:00Z",
        },
        headers=_auth_header(ctx["token_a"]),
    )
    (payment,) = _payments(ctx)
    page = client.get(f"/pay-qr/{payment.id}")
    assert page.status_code == 200 and "data:image/png;base64," in page.text
    assert "NPR 9000.00" in page.text
    assert encoded == ["https://esewa.fake/redirect/abc"]

    with SessionLocal() as db:
        db.get(Payment, payment.id).status = PaymentStatus.COMPLETED
        db.commit()
    assert client.get(f"/pay-qr/{payment.id}").status_code == 404
    assert client.get(f"/pay-qr/{uuid.uuid4()}").status_code == 404


def test_payment_email_embeds_a_second_inline_qr_of_the_payment_url(premium_npr_ready, gateways, monkeypatch):
    import app.services.notifications.content as content

    ctx = premium_npr_ready
    encoded: list[str] = []
    real = content.generate_qr_png
    monkeypatch.setattr(content, "generate_qr_png", lambda data: (encoded.append(data), real(data))[1])
    client.post(
        "/api/v1/appointments",
        json={
            "customer_id": str(ctx["customer_id"]),
            "service_id": str(ctx["deposit_service_id"]),
            "scheduled_at": f"{_next_monday().isoformat()}T10:00:00Z",
        },
        headers=_auth_header(ctx["token_a"]),
    )
    (payment,) = _payments(ctx)
    with SessionLocal() as db:
        from app.db.models.business import Business
        from app.db.models.customer import Customer
        from app.db.models.service import Service

        appt = db.get(Appointment, payment.appointment_id)
        args = dict(
            appointment=appt,
            business=db.get(Business, appt.business_id),
            service=db.get(Service, appt.service_id),
            customer=db.get(Customer, appt.customer_id),
            payment=payment,
        )
        _, body, html_body, images = content.compose_email(event_type="booking_confirmed", **args)
        assert [cid for cid, _, _ in images] == ["payment-qrcode", "checkin-qrcode"]
        assert 'src="cid:payment-qrcode"' in html_body and "https://esewa.fake/redirect/abc" in body
        assert "https://esewa.fake/redirect/abc" in encoded

        subject, _, html_body, images = content.compose_email(event_type="payment_requested", **args)
        assert [cid for cid, _, _ in images] == ["payment-qrcode"]  # no check-in QR on this one
        assert "deposit" in subject.lower() and "Deposit due" in html_body


def test_choosing_in_chat_also_sends_a_payment_requested_email(premium_npr_ready, gateways, chat, monkeypatch):
    import app.services.conversation.booking_tool as booking_tool

    sent: list[str] = []
    real = booking_tool.dispatch_notification
    monkeypatch.setattr(
        booking_tool, "dispatch_notification", lambda db, n: (sent.append(n.event_type), real(db, n))[1]
    )
    ctx = premium_npr_ready
    _set_providers(ctx, ["esewa", "khalti"])
    chat.reply = _booking_reply()
    conv = _conversation(ctx, _customer_with_email(ctx))
    _say(ctx, conv, "root canal monday 2pm")
    assert sent == []
    _say(ctx, conv, "khalti")
    assert sent == ["payment_requested"]


# --- Part 3: proactive payment-success message ------------------------------


def _pending_chat_payment(ctx, chat, channel: str = "website"):
    chat.reply = _booking_reply()
    customer_id = _customer_with_email(ctx)
    conv = _conversation(ctx, customer_id, channel)
    booked = _say(ctx, conv, "root canal monday 2pm")
    (payment,) = _payments(ctx)
    return conv, customer_id, payment, booked


def _agent_messages(conv: uuid.UUID) -> list[str]:
    with SessionLocal() as db:
        rows = (
            db.query(Message)
            .filter(Message.conversation_id == conv, Message.sender_type == MessageSenderType.AGENT)
            .order_by(Message.created_at)
            .all()
        )
        return [m.content for m in rows]


def test_verified_completion_sends_one_confirmation_into_the_original_conversation(premium_npr_ready, gateways, chat):
    conv, _, payment, _ = _pending_chat_payment(premium_npr_ready, chat)
    before = len(_agent_messages(conv))
    with SessionLocal() as db:
        payment_service.verify_and_update(db, db.get(Payment, payment.id))
        # a redirect hit a second time, or racing the first, must not repeat the message
        payment_service.notify_payment_completed(db, db.get(Payment, payment.id))
    messages = _agent_messages(conv)
    assert len(messages) == before + 1
    assert "Payment received" in messages[-1] and "NPR 9000.00" in messages[-1]
    with SessionLocal() as db:
        confirmation_code = db.get(Appointment, payment.appointment_id).confirmation_code
    assert confirmation_code in messages[-1]


def test_a_failed_or_unverified_payment_sends_nothing(premium_npr_ready, gateways, chat):
    conv, _, payment, _ = _pending_chat_payment(premium_npr_ready, chat)
    gateways["esewa"].verify_result = PaymentVerification(completed=False, raw_status="NOT_FOUND")
    before = len(_agent_messages(conv))
    with SessionLocal() as db:
        payment_service.verify_and_update(db, db.get(Payment, payment.id))
    assert len(_agent_messages(conv)) == before


def test_a_dashboard_booking_has_no_conversation_so_completion_just_updates_status(premium_npr_ready, gateways):
    ctx = premium_npr_ready
    client.post(
        "/api/v1/appointments",
        json={
            "customer_id": str(ctx["customer_id"]),
            "service_id": str(ctx["deposit_service_id"]),
            "scheduled_at": f"{_next_monday().isoformat()}T10:00:00Z",
        },
        headers=_auth_header(ctx["token_a"]),
    )
    (payment,) = _payments(ctx)
    with SessionLocal() as db:
        done = payment_service.verify_and_update(db, db.get(Payment, payment.id))
        assert done.status == PaymentStatus.COMPLETED


def test_completion_message_is_pushed_out_through_the_whatsapp_adapter(premium_npr_ready, gateways, chat, monkeypatch):
    ctx = premium_npr_ready
    sent: list[dict] = []
    monkeypatch.setattr(WhatsAppChannelAdapter, "send_message", lambda self, **kw: (sent.append(kw), "sent")[1])
    chat.reply = _booking_reply()
    customer_id = _customer_with_email(ctx)
    conv = _conversation(ctx, customer_id, "whatsapp")
    with SessionLocal() as db:
        db.add(
            Integration(
                business_id=ctx["business_id_a"],
                type="whatsapp",
                enabled=True,
                config={"phone_number_id": "PN-1", "access_token": "tok"},
            )
        )
        db.add(
            ChannelIdentity(
                business_id=ctx["business_id_a"], channel="whatsapp", external_ref="9779800000001", customer_id=customer_id
            )
        )
        db.commit()
    _say(ctx, conv, "root canal monday 2pm")
    (payment,) = _payments(ctx)
    with SessionLocal() as db:
        payment_service.verify_and_update(db, db.get(Payment, payment.id))
    assert len(sent) == 1
    assert sent[0]["to"] == "9779800000001" and sent[0]["phone_number_id"] == "PN-1"
    assert "Payment received" in sent[0]["text"]


def test_widget_receives_the_confirmation_via_its_updates_poll(premium_npr_ready, gateways, chat):
    ctx = premium_npr_ready
    chat.reply = _booking_reply()
    # a real widget session: first message mints the token and the website conversation/customer
    first = client.post(
        f"/api/v1/widget/{ctx['business_id_a']}/messages",
        json={"content": "hi", "session_token": None},
    )
    assert first.status_code == 200, first.text
    token = first.json()["session_token"]
    with SessionLocal() as db:
        customer = db.query(Conversation).filter(Conversation.business_id == ctx["business_id_a"]).one()
        from app.db.models.customer import Customer

        db.get(Customer, customer.customer_id).email = "widget@example.com"
        db.commit()
    booked = client.post(
        f"/api/v1/widget/{ctx['business_id_a']}/messages",
        json={"content": "root canal monday 2pm", "session_token": token},
    ).json()
    assert booked["agent_message_id"] and "/pay-qr/" in booked["response"]
    url = f"/api/v1/widget/{ctx['business_id_a']}/updates"
    params = {"session_token": token, "after": booked["agent_message_id"]}
    assert client.get(url, params=params).json() == {"messages": []}

    (payment,) = _payments(ctx)
    with SessionLocal() as db:
        payment_service.verify_and_update(db, db.get(Payment, payment.id))
    updates = client.get(url, params=params).json()["messages"]
    assert len(updates) == 1 and "Payment received" in updates[0]["content"]

    # someone else's token learns nothing
    other = client.get(url, params={"session_token": "x" * 43, "after": booked["agent_message_id"]})
    assert other.status_code == 200 and other.json() == {"messages": []}
