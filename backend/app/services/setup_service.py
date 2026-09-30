"""The Overview's "Get set up" checklist: what a new business still has to do before the assistant can really help.

Every step is worked out from real data (nothing for the owner to tick by hand), so a step completes the moment the
thing is actually done: a service saved, hours set, an answer approved, the chat seen on a real website, a channel
connected."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.business import Business, BusinessHours
from app.db.models.integration import Integration
from app.db.models.knowledge import KnowledgeDocument, KnowledgeDocumentStatus
from app.db.models.service import Service

_MESSAGING_CHANNELS = ("whatsapp", "messenger", "instagram")


def _count(db: Session, model, *conditions) -> int:
    return db.execute(select(func.count()).select_from(model).where(*conditions)).scalar_one()


def setup_status(db: Session, *, business_id: uuid.UUID) -> dict:
    business = db.get(Business, business_id)
    steps = []
    if business.booking_enabled:
        steps.append({
            "key": "services",
            "title": "Add what customers can book",
            "description": "Your services, with price and how long they take.",
            "done": _count(db, Service, Service.business_id == business_id) > 0,
            "link": "/dashboard/services",
        })
    steps.append({
        "key": "hours",
        "title": "Set your opening hours",
        "description": "So the assistant only offers times you're open.",
        "done": _count(db, BusinessHours, BusinessHours.business_id == business_id, BusinessHours.closed.is_(False)) > 0,
        "link": "/dashboard/hours",
    })
    steps.append({
        "key": "knowledge",
        "title": "Teach your assistant",
        "description": "Add your prices, policies and common questions, or import them from your website.",
        "done": _count(
            db, KnowledgeDocument,
            KnowledgeDocument.business_id == business_id,
            KnowledgeDocument.status == KnowledgeDocumentStatus.APPROVED,
        ) > 0,
        "link": "/dashboard/knowledge",
    })
    steps.append({
        "key": "website",
        "title": "Add the chat to your website",
        "description": "One line of code, and visitors can chat with your assistant.",
        "done": business.widget_installed_at is not None,
        "link": "/dashboard/widget",
    })
    steps.append({
        "key": "channel",
        "title": "Connect WhatsApp, Instagram or Messenger",
        "description": "Answer customers where they already message you.",
        "done": _count(
            db, Integration,
            Integration.business_id == business_id,
            Integration.type.in_(_MESSAGING_CHANNELS),
            Integration.enabled.is_(True),
        ) > 0,
        "link": "/dashboard/channels",
    })
    done = sum(1 for s in steps if s["done"])
    return {"steps": steps, "completed": done, "total": len(steps)}
