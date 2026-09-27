"""Phase 52 — the inbox's read model and the staff reply.

A staff reply is: validate -> (idempotency) -> is the customer's channel able to receive it (24h window etc.) -> claim the
conversation (the AI goes silent, under the ReplyLock) + store the STAFF message -> push it through the SAME per-channel path
system messages use (`proactive.push_to_channel`) -> store what happened (delivery_status/detail) -> audit."""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, UnprocessableEntityError
from app.db.models.audit_log import AuditLog
from app.db.models.business import BusinessUser
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.customer import Customer
from app.db.models.handoff import HumanHandoff
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.services import integration_service, takeover_service
from app.services.channels import delivery
from app.services.channels.proactive import push_to_channel

logger = logging.getLogger(__name__)

# Meta's customer-service window: a business may send free-form messages only for 24h after the customer's LAST message
# (verify against Meta's current docs before relying on the exact rules — this phase only BLOCKS, it never works around it:
# no template messages, no HUMAN_AGENT tag). A send that Meta rejects anyway is still recorded as delivery_status="failed".
REPLY_WINDOW = timedelta(hours=24)
_WINDOWED = {"whatsapp": "WhatsApp", "messenger": "Messenger", "instagram": "Instagram"}
# Conservative per-channel length caps (Messenger 2000 chars, WhatsApp 4096 chars, Instagram 1000 BYTES — verify).
_MAX_CHARS = {"whatsapp": 4096, "messenger": 2000, "website": 4000}
_INSTAGRAM_MAX_BYTES = 1000


@dataclass
class ReplyState:
    can_reply: bool
    reason: str | None = None
    window_closes_at: datetime | None = None


def last_customer_message_at(db: Session, conversation_id: uuid.UUID) -> datetime | None:
    """UTC, timezone-aware. `messages.created_at` is a naive timestamp written by the database's now() (the DB runs in UTC)."""
    value = db.execute(
        select(func.max(Message.created_at)).where(
            Message.conversation_id == conversation_id, Message.sender_type == MessageSenderType.CUSTOMER
        )
    ).scalar()
    return value.replace(tzinfo=timezone.utc) if value is not None else None


def _channel_connected(db: Session, conversation: Conversation) -> bool:
    integration = integration_service.get_integration(
        db, business_id=conversation.business_id, type_=conversation.channel
    )
    if integration is None or not integration.enabled:
        return False
    return (
        db.execute(
            select(ChannelIdentity.id).where(
                ChannelIdentity.business_id == conversation.business_id,
                ChannelIdentity.channel == conversation.channel,
                ChannelIdentity.customer_id == conversation.customer_id,
            ).limit(1)
        ).first()
        is not None
    )


def reply_state(db: Session, conversation: Conversation, *, now: datetime | None = None) -> ReplyState:
    """Can a staff reply actually reach this customer right now, and if not, why (shown verbatim in the inbox)."""
    now = now or datetime.now(timezone.utc)
    channel = conversation.channel
    if channel == "website":
        return ReplyState(True)  # no window: the widget picks the reply up on its next poll
    if channel not in _WINDOWED:
        return ReplyState(False, f"Replies can't be sent from the inbox on the '{channel}' channel.")
    label = _WINDOWED[channel]
    if not _channel_connected(db, conversation):
        return ReplyState(False, f"{label} isn't connected for this business, so a reply can't be delivered.")
    last = last_customer_message_at(db, conversation.id)
    if last is None or now - last >= REPLY_WINDOW:
        return ReplyState(
            False,
            f"Can't reply: the 24-hour {label} reply window closed"
            + (f" (the customer's last message was {_ago(now - last)} ago)." if last else " (the customer has not messaged)."),
            (last + REPLY_WINDOW) if last else None,
        )
    return ReplyState(True, None, last + REPLY_WINDOW)


def _ago(delta: timedelta) -> str:
    hours = int(delta.total_seconds() // 3600)
    return f"{hours // 24} days" if hours >= 48 else f"{hours} hours"


def _validate_length(channel: str, content: str) -> None:
    if channel == "instagram":
        if len(content.encode("utf-8")) > _INSTAGRAM_MAX_BYTES:
            raise UnprocessableEntityError(f"Instagram messages are limited to {_INSTAGRAM_MAX_BYTES} bytes.")
    elif len(content) > _MAX_CHARS.get(channel, 4000):
        raise UnprocessableEntityError(f"Messages on this channel are limited to {_MAX_CHARS.get(channel, 4000)} characters.")


def list_thread(
    db: Session, *, conversation: Conversation, after_message_id: uuid.UUID | None = None, limit: int = 200,
    latest: bool = False,
) -> list[tuple[Message, str | None]]:
    """Oldest -> newest, every channel the same query. Each row comes with the staff author's email (None for non-staff).
    `latest=True` returns the NEWEST `limit` messages (still oldest-first) — what a chat view wants for a long conversation;
    otherwise the OLDEST `limit` (paging forward with `after`)."""
    stmt = (
        select(Message, BusinessUser.email)
        .outerjoin(BusinessUser, BusinessUser.id == Message.sent_by_user_id)
        .where(Message.conversation_id == conversation.id)
    )
    if after_message_id is not None:
        cursor = db.get(Message, after_message_id)
        if cursor is None or cursor.conversation_id != conversation.id:
            raise NotFoundError("Message not found.")
        stmt = stmt.where(
            (Message.created_at > cursor.created_at) | ((Message.created_at == cursor.created_at) & (Message.id > cursor.id))
        )
    if latest:
        rows = db.execute(stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)).all()
        return [(m, email) for m, email in reversed(rows)]
    return [(m, email) for m, email in db.execute(stmt.order_by(Message.created_at, Message.id).limit(limit)).all()]


def send_staff_reply(
    db: Session, *, conversation: Conversation, user: BusinessUser, content: str, client_msg_id: str | None
) -> Message:
    content = content.strip()
    if not content:
        raise UnprocessableEntityError("A reply can't be empty.")
    _validate_length(conversation.channel, content)

    if client_msg_id:  # a double-click / network retry of the same reply returns the original, sending nothing again
        existing = db.execute(
            select(Message).where(Message.conversation_id == conversation.id, Message.client_msg_id == client_msg_id)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    state = reply_state(db, conversation)
    if not state.can_reply:
        raise ConflictError(state.reason or "This conversation can't receive a reply right now.")

    # Claim + store atomically w.r.t. any AI reply being delivered (ReplyLock): after this commit the AI is silent, and the
    # STAFF message exists before it is sent, so a send that fails is still visible (and retryable) instead of vanishing.
    message = Message(
        conversation_id=conversation.id,
        sender_type=MessageSenderType.STAFF,
        content=content,
        sent_by_user_id=user.id,
        client_msg_id=client_msg_id,
        delivery_status=delivery.PENDING,
    )
    try:
        with takeover_service.ReplyLock(conversation.id, timeout_seconds=takeover_service.CLAIM_LOCK_TIMEOUT_SECONDS):
            db.add(message)
            conversation.human_takeover_until = datetime.now(timezone.utc) + timedelta(seconds=settings.human_takeover_seconds)
            conversation.human_takeover_by = user.id
            db.commit()
    except IntegrityError:  # lost a race with the identical client_msg_id: the other request owns the send
        db.rollback()
        if not client_msg_id:
            raise
        return db.execute(
            select(Message).where(Message.conversation_id == conversation.id, Message.client_msg_id == client_msg_id)
        ).scalar_one()
    db.refresh(message)

    detail = push_to_channel(db, conversation=conversation, text=content)
    message.delivery_status = delivery.status_from_detail(detail)
    message.delivery_detail = detail[:255]
    db.add(
        AuditLog(
            business_id=conversation.business_id,
            actor=str(user.id),
            action="inbox_reply",
            resource_type="conversation",
            resource_id=str(conversation.id),
            result=message.delivery_status,
        )
    )
    db.commit()
    db.refresh(message)
    return message


# ------------------------------------------------------------------------------------------------ the list (inbox home)


def _list_stmt(business_id: uuid.UUID):
    """One row per conversation with everything the list needs, computed in SQL (no per-row queries):
    the last message (any sender), the customer's last message time, and whether an escalation is open.
    "needs_reply" = a human is responsible (an open handoff, or a staff member owns it) AND the customer spoke last — i.e.
    someone is waiting for a person. A conversation the AI is handling and has answered is never "needs reply"."""
    last = (
        select(Message.conversation_id, Message.content, Message.sender_type, Message.created_at, Message.delivery_status)
        .distinct(Message.conversation_id)
        .order_by(Message.conversation_id, Message.created_at.desc(), Message.id.desc())
        .subquery("last")
    )
    last_cust = (
        select(Message.conversation_id, func.max(Message.created_at).label("at"))
        .where(Message.sender_type == MessageSenderType.CUSTOMER)
        .group_by(Message.conversation_id)
        .subquery("last_cust")
    )
    handoff = exists().where(
        HumanHandoff.conversation_id == Conversation.id, HumanHandoff.resolved_at.is_(None)
    )
    takeover = func.coalesce(Conversation.human_takeover_until > func.clock_timestamp(), False)
    needs_reply = and_(last.c.sender_type == MessageSenderType.CUSTOMER, or_(handoff, takeover))
    is_lead = Conversation.lead_signal == "high"
    unread = and_(
        last_cust.c.at.is_not(None),
        or_(Conversation.staff_last_read_at.is_(None), last_cust.c.at > Conversation.staff_last_read_at),
    )
    stmt = (
        select(
            Conversation.id,
            Conversation.channel,
            Customer.name.label("customer_name"),
            last.c.content,
            last.c.sender_type,
            last.c.created_at.label("last_at"),
            last.c.delivery_status,
            needs_reply.label("needs_reply"),
            unread.label("unread"),
            handoff.label("open_handoff"),
            takeover.label("takeover_active"),
            BusinessUser.email.label("takeover_by_email"),
            Conversation.lead_signal,
        )
        .join(Customer, Customer.id == Conversation.customer_id)
        .join(last, last.c.conversation_id == Conversation.id)
        .outerjoin(last_cust, last_cust.c.conversation_id == Conversation.id)
        .outerjoin(BusinessUser, BusinessUser.id == Conversation.human_takeover_by)
        .where(Conversation.business_id == business_id)
    )
    return stmt, needs_reply, handoff, is_lead


def list_conversations(
    db: Session, *, business_id: uuid.UUID, tab: str = "all", channel: str | None = None, q: str | None = None,
    limit: int = 50, offset: int = 0,
) -> list:
    stmt, needs_reply, handoff, is_lead = _list_stmt(business_id)
    if tab == "needs_reply":
        stmt = stmt.where(needs_reply)
    elif tab == "handoffs":
        stmt = stmt.where(handoff)
    elif tab == "leads":
        stmt = stmt.where(is_lead)
    if channel:
        stmt = stmt.where(Conversation.channel == channel)
    if q:
        stmt = stmt.where(Customer.name.ilike(f"%{q.strip()}%"))
    return list(db.execute(stmt.order_by(stmt.selected_columns.last_at.desc()).limit(limit).offset(offset)).all())


def summary(db: Session, *, business_id: uuid.UUID) -> tuple[int, int, int]:
    """(conversations waiting for a person, conversations with an open handoff, high-intent leads) — the nav badges."""
    stmt, needs_reply, handoff, is_lead = _list_stmt(business_id)
    base = stmt.subquery("rows")
    waiting = db.execute(select(func.count()).select_from(base).where(base.c.needs_reply)).scalar() or 0
    handoffs = db.execute(select(func.count()).select_from(base).where(base.c.open_handoff)).scalar() or 0
    leads = db.execute(select(func.count()).select_from(base).where(base.c.lead_signal == "high")).scalar() or 0
    return int(waiting), int(handoffs), int(leads)


def mark_read(db: Session, conversation: Conversation) -> None:
    conversation.staff_last_read_at = func.localtimestamp()
    db.commit()
