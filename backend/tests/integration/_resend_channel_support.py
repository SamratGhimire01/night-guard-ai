"""Shared scenario for the per-channel "QR link in chat" proofs (WhatsApp / Messenger / Instagram webhook tests).

Not a test module (leading underscore). Runs the REAL signed webhook -> REAL orchestrator path twice: message 1 creates
the customer + conversation; an appointment is then booked for that customer; message 2 ("send me my QR") is answered
by a stubbed LLM that only identifies the intent + appointment (exactly the real LLM's job). The outbound Graph-API
request is captured at urllib, i.e. the exact JSON body a real send would POST to Meta."""
import json
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.db.database import SessionLocal
from app.db.models.business import BusinessHours
from app.db.models.conversation import Conversation, Message
from app.db.models.service import Service
from app.services import booking_service


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


def run_resend_scenario(monkeypatch, *, business_id, post_webhook, first_payload, second_payload) -> dict:
    import app.services.conversation.intent as intent_module

    captured: list[dict] = []

    def fake_urlopen(request, timeout=None):
        captured.append(json.loads(request.data.decode("utf-8")))
        return _Resp({"messages": [{"id": "wamid.T"}], "message_id": "mid.T"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    status, body = post_webhook(first_payload)
    assert status == 200, body
    with SessionLocal() as db:
        conversation = db.query(Conversation).filter(Conversation.business_id == business_id).one()
        customer_id, conversation_id = conversation.customer_id, conversation.id
        for day in range(6):
            db.add(BusinessHours(business_id=business_id, day_of_week=day, open_time=time(9), close_time=time(17), closed=False))
        service = Service(business_id=business_id, name="Cleaning", price=50, duration_minutes=30)
        db.add(service)
        db.commit()
        service_id = service.id
        today = date.today()
        target = today + timedelta(days=(0 - today.weekday()) % 7 or 7)
        appointment_id = booking_service.create_appointment(
            db, business_id=business_id, customer_id=customer_id, service_id=service_id, staff_id=None,
            scheduled_at=datetime(target.year, target.month, target.day, 14, 0, tzinfo=ZoneInfo("UTC")),
        ).id

    class _ResendChat:
        def chat(self, messages):
            return json.dumps(
                {"intent": "resend_confirmation", "response": "Sure!",
                 "resend_request": {"appointment_id": str(appointment_id), "channel": None}}
            )

    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: _ResendChat())
    captured.clear()
    status, body = post_webhook(second_payload)
    assert status == 200, body
    with SessionLocal() as db:
        agent_messages = (
            db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.created_at).all()
        )
        stored_reply = agent_messages[-1].content
    return {"captured": list(captured), "stored_reply": stored_reply, "appointment_id": appointment_id, "unique": uuid.uuid4().hex}
