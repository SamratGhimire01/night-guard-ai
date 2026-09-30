import csv
import io
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models.appointment import Appointment
from app.db.models.conversation import Conversation, Message
from app.db.models.customer import Customer
from app.schemas.customer import CustomerCreate, CustomerUpdate


def create_customer(db: Session, *, business_id: uuid.UUID, payload: CustomerCreate) -> Customer:
    customer = Customer(business_id=business_id, **payload.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def update_customer(
    db: Session, *, business_id: uuid.UUID, customer_id: uuid.UUID, payload: CustomerUpdate
) -> Customer | None:
    """Tenant-scoped partial update. None for a customer that doesn't exist or
    belongs to another business — same IDOR-safe pattern as every other
    resource in this codebase. `exclude_unset`: a field the client never sent
    is left alone; a field sent as an explicit null DOES come through (and
    clears a nullable column) — CustomerUpdate's validators reject an
    explicit null on name/sms_opt_in before this ever runs."""
    customer = get_customer(db, business_id=business_id, customer_id=customer_id)
    if customer is None:
        return None
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)
    db.commit()
    db.refresh(customer)
    return customer


def get_customer(db: Session, *, business_id: uuid.UUID, customer_id: uuid.UUID) -> Customer | None:
    """Scoped to business_id: a customer belonging to another tenant is indistinguishable
    from one that doesn't exist at all — this is what makes cross-tenant IDOR impossible."""
    return db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.business_id == business_id)
    ).scalar_one_or_none()


def delete_customer(db: Session, *, business_id: uuid.UUID, customer_id: uuid.UUID) -> bool:
    customer = get_customer(db, business_id=business_id, customer_id=customer_id)
    if customer is None:
        return False
    db.delete(customer)
    db.commit()
    return True


def list_customers(db: Session, *, business_id: uuid.UUID, q: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    """Everyone who has contacted the business, newest contact first, with how they reached it and what came of it.
    `q` matches name, phone or email (case-insensitive)."""
    conversations = (
        select(
            Conversation.customer_id.label("customer_id"),
            func.count(func.distinct(Conversation.id)).label("conversations"),
            func.max(Message.created_at).label("last_contact_at"),
            func.min(Conversation.channel).label("channel"),
        )
        .select_from(Conversation)
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .where(Conversation.business_id == business_id)
        .group_by(Conversation.customer_id)
        .subquery()
    )
    appointments = (
        select(Appointment.customer_id.label("customer_id"), func.count().label("appointments"))
        .where(Appointment.business_id == business_id)
        .group_by(Appointment.customer_id)
        .subquery()
    )
    stmt = (
        select(Customer, conversations.c.conversations, conversations.c.last_contact_at, conversations.c.channel, appointments.c.appointments)
        .outerjoin(conversations, conversations.c.customer_id == Customer.id)
        .outerjoin(appointments, appointments.c.customer_id == Customer.id)
        .where(Customer.business_id == business_id)
    )
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(func.lower(Customer.name).like(like), func.lower(Customer.email).like(like), Customer.phone.like(f"%{q.strip()}%"))
        )
    stmt = stmt.order_by(func.coalesce(conversations.c.last_contact_at, Customer.created_at).desc()).limit(limit).offset(offset)
    rows = []
    for customer, n_conversations, last_contact_at, channel, n_appointments in db.execute(stmt).all():
        rows.append({
            "id": customer.id,
            "name": customer.known_name,
            "phone": customer.phone,
            "email": customer.email,
            "channel": channel,
            "conversations": n_conversations or 0,
            "appointments": n_appointments or 0,
            "first_seen_at": customer.created_at,
            "last_contact_at": last_contact_at or customer.created_at,
        })
    return rows


def _csv_safe(value) -> str:
    """Stops a spreadsheet from running a customer-supplied value as a formula (CSV injection)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def customers_csv(db: Session, *, business_id: uuid.UUID) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Name", "Phone", "Email", "First contacted on", "Conversations", "Appointments", "First seen", "Last contact"])
    offset = 0
    while True:
        batch = list_customers(db, business_id=business_id, limit=500, offset=offset)
        for r in batch:
            writer.writerow([
                _csv_safe(r["name"] or ""), _csv_safe(r["phone"]), _csv_safe(r["email"]), r["channel"] or "",
                r["conversations"], r["appointments"], r["first_seen_at"].isoformat(), r["last_contact_at"].isoformat(),
            ])
        if len(batch) < 500:
            break
        offset += 500
    return "﻿" + out.getvalue()  # BOM: Excel then opens Nepali (and any non-Latin) names correctly
