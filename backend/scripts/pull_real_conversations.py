"""One-off dump: every real conversation across every tenant, with the tenant's
configured data (services, hours, business profile) and any appointments the
conversation produced, so failures can be checked against real ground truth
instead of guessed at.

Fresh process each run (imports current code from disk) -- run via:
    docker exec night_guard_ai-backend-1 python scripts/pull_real_conversations.py

Writes one JSON file per conversation to data/regression/real_conversations/
(repo root, bind-mounted, so it lands on the host too).
"""

import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment
from app.db.models.business import Business, BusinessHours
from app.db.models.conversation import Conversation, Message
from app.db.models.customer import Customer
from app.db.models.knowledge import KnowledgeDocument, KnowledgeDocumentStatus
from app.db.models.service import Service

# backend/ is the container's bind-mounted volume (see docker-compose.yml); only
# paths under it are visible on the host, so data lives at backend/data/ rather
# than a top-level data/ the container can't actually write to.
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "regression" / "real_conversations"


def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)


def dump_business(session: Session, business: Business) -> dict:
    services = session.execute(select(Service).where(Service.business_id == business.id)).scalars().all()
    hours = session.execute(select(BusinessHours).where(BusinessHours.business_id == business.id)).scalars().all()
    # Approved-only: this is the tenant's real ground truth for anything a RAG-backed
    # reply might cite (policies, parking, insurance, etc. -- not modeled as columns
    # anywhere else), so unconfigured_fact checks must cross-reference this too.
    knowledge_docs = (
        session.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.business_id == business.id,
                KnowledgeDocument.status == KnowledgeDocumentStatus.APPROVED,
            )
        )
        .scalars()
        .all()
    )
    return {
        "id": str(business.id),
        "name": business.name,
        "timezone": business.timezone,
        "currency": business.currency,
        "languages": business.languages,
        "language_mode": business.language_mode.value if business.language_mode else None,
        "tone": business.tone,
        "content_scope": business.content_scope.value if business.content_scope else None,
        "payment_collection_enabled": business.payment_collection_enabled,
        "payment_providers": business.payment_providers,
        "services": [
            {
                "id": str(s.id),
                "name": s.name,
                "description": s.description,
                "price": float(s.price),
                "duration_minutes": s.duration_minutes,
                "deposit_enabled": s.deposit_enabled,
                "deposit_percentage": s.deposit_percentage,
            }
            for s in services
        ],
        "knowledge_documents": [
            {"id": str(k.id), "title": k.title, "content": k.content} for k in knowledge_docs
        ],
        "hours": [
            {
                "day_of_week": h.day_of_week,
                "closed": h.closed,
                "open_time": str(h.open_time) if h.open_time else None,
                "close_time": str(h.close_time) if h.close_time else None,
            }
            for h in hours
        ],
    }


def dump_conversation(session: Session, conversation: Conversation) -> dict:
    messages = (
        session.execute(
            select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)
        )
        .scalars()
        .all()
    )
    customer = session.get(Customer, conversation.customer_id)
    appointments = (
        session.execute(
            select(Appointment).where(
                Appointment.business_id == conversation.business_id,
                Appointment.customer_id == conversation.customer_id,
            )
        )
        .scalars()
        .all()
    )
    return {
        "conversation_id": str(conversation.id),
        "business_id": str(conversation.business_id),
        "channel": conversation.channel,
        "status": conversation.status,
        "detected_language": conversation.detected_language,
        "created_at": conversation.created_at.isoformat(),
        "customer": {
            "id": str(customer.id) if customer else None,
            "preferred_language": customer.preferred_language if customer else None,
        },
        "messages": [
            {
                "sender_type": m.sender_type.value,
                "content": m.content,
                "detected_intent": m.detected_intent,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
        "booking_draft": {
            "service_id": str(conversation.booking_draft_service_id)
            if conversation.booking_draft_service_id
            else None,
            "date": conversation.booking_draft_date,
            "time": conversation.booking_draft_time,
        },
        # Proxy for "tool calls made": this codebase has no explicit tool-call log,
        # so the real side effect of a booking is the Appointment row it produced.
        "appointments_for_this_customer": [
            {
                "id": str(a.id),
                "service_id": str(a.service_id) if a.service_id else None,
                "scheduled_at": a.scheduled_at.isoformat() if a.scheduled_at else None,
                "status": a.status.value,
                "created_at": a.created_at.isoformat(),
            }
            for a in appointments
        ],
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*.json"):
        old.unlink()

    session = SessionLocal()
    try:
        businesses = session.execute(select(Business)).scalars().all()
        business_dumps = {b.id: dump_business(session, b) for b in businesses}

        conversations = session.execute(select(Conversation).order_by(Conversation.created_at)).scalars().all()

        count = 0
        for conv in conversations:
            record = dump_conversation(session, conv)
            record["business"] = business_dumps[conv.business_id]
            out_path = OUT_DIR / f"{record['created_at'][:10]}_{record['conversation_id']}.json"
            out_path.write_text(json.dumps(record, indent=2, default=_json_default))
            count += 1
    finally:
        session.close()

    print(f"businesses={len(businesses)} conversations_written={count} out_dir={OUT_DIR}")


if __name__ == "__main__":
    main()
