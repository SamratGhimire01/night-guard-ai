import uuid
from datetime import datetime, timezone

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_role
from app.core.exceptions import NotFoundError
from app.db.models.business import BusinessUser
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.db.models.handoff import HumanHandoff
from app.memory.conversations import get_conversation
from app.schemas.inbox import (
    InboxConversation,
    InboxHandoff,
    InboxListItem,
    InboxMessage,
    InboxSummary,
    ReplyRequest,
    ReplyWindow,
    TakeoverState,
)
from app.services import inbox_service, takeover_service

router = APIRouter()

# Same bar as /handoffs: the people fielding an escalation are the people who must be able to answer it. Viewing and replying
# share one role list on purpose (owner/admin/staff) -- see docs/unified-inbox-proposal.md section 5.
_INBOX_ROLES = ["owner", "admin", "staff"]


def _state(conversation: Conversation) -> TakeoverState:
    until = conversation.human_takeover_until
    return TakeoverState(
        active=until is not None and until > datetime.now(timezone.utc),
        until=until,
        taken_over_by=conversation.human_takeover_by,
    )


def _load(db: Session, conversation_id: uuid.UUID, current_user: BusinessUser) -> Conversation:
    conversation = get_conversation(db, conversation_id=conversation_id, business_id=current_user.business_id)
    if conversation is None:
        raise NotFoundError("Conversation not found.")
    return conversation


@router.post("/inbox/conversations/{conversation_id}/takeover", response_model=TakeoverState)
def take_over_conversation(
    conversation_id: uuid.UUID,
    current_user: BusinessUser = Depends(require_role(_INBOX_ROLES)),
    db: Session = Depends(get_db),
) -> TakeoverState:
    """Claim the conversation: the AI goes silent for the next `human_takeover_seconds` (2h), restarted by every staff reply
    and by calling this again."""
    conversation = takeover_service.start_or_extend(db, _load(db, conversation_id, current_user), user_id=current_user.id)
    return _state(conversation)


@router.post("/inbox/conversations/{conversation_id}/release", response_model=TakeoverState)
def release_conversation(
    conversation_id: uuid.UUID,
    current_user: BusinessUser = Depends(require_role(_INBOX_ROLES)),
    db: Session = Depends(get_db),
) -> TakeoverState:
    """Hand the conversation back to the AI immediately. Idempotent."""
    return _state(takeover_service.release(db, _load(db, conversation_id, current_user)))


def _utc(value: datetime) -> datetime:
    """`messages.created_at` is a naive timestamp (the database runs in UTC). Serialised as-is a browser would read it as LOCAL
    time; tag it UTC so every timestamp the inbox returns is unambiguous."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _message_out(message, email: str | None) -> InboxMessage:
    return InboxMessage(
        id=message.id,
        sender_type=message.sender_type.value,
        content=message.content,
        created_at=_utc(message.created_at),
        delivery_status=message.delivery_status,
        delivery_detail=message.delivery_detail,
        sent_by_user_id=message.sent_by_user_id,
        sent_by_email=email,
    )


@router.get("/inbox/conversations/{conversation_id}", response_model=InboxConversation)
def get_inbox_conversation(
    conversation_id: uuid.UUID,
    current_user: BusinessUser = Depends(require_role(_INBOX_ROLES)),
    db: Session = Depends(get_db),
) -> InboxConversation:
    """Header for one conversation: who, which channel, who owns it (AI vs a staff member), the open handoff if any, and
    whether a reply can reach the customer right now (the 24h window) — `reply.reason` says why not."""
    conversation = _load(db, conversation_id, current_user)
    customer = db.get(Customer, conversation.customer_id)
    handoff = db.execute(
        select(HumanHandoff).where(
            HumanHandoff.business_id == conversation.business_id,
            HumanHandoff.conversation_id == conversation.id,
            HumanHandoff.resolved_at.is_(None),
        )
    ).scalar_one_or_none()
    state = inbox_service.reply_state(db, conversation)
    takeover = _state(conversation)
    owner = db.get(BusinessUser, conversation.human_takeover_by) if conversation.human_takeover_by else None
    return InboxConversation(
        id=conversation.id,
        channel=conversation.channel,
        customer_id=conversation.customer_id,
        customer_name=customer.name if customer else "Unknown customer",
        customer_phone=customer.phone if customer else None,
        customer_email=customer.email if customer else None,
        takeover=takeover,
        takeover_by_email=owner.email if takeover.active and owner else None,
        reply=ReplyWindow(can_reply=state.can_reply, reason=state.reason, window_closes_at=state.window_closes_at),
        open_handoff=InboxHandoff(id=handoff.id, reason=handoff.reason) if handoff else None,
        last_customer_message_at=inbox_service.last_customer_message_at(db, conversation.id),
        lead_signal=conversation.lead_signal,
        lead_summary=conversation.lead_summary,
    )


@router.get("/inbox/conversations/{conversation_id}/messages", response_model=list[InboxMessage])
def get_inbox_messages(
    conversation_id: uuid.UUID,
    after: uuid.UUID | None = Query(default=None, description="only messages newer than this message id (for polling)"),
    limit: int = Query(default=200, ge=1, le=500),
    latest: bool = Query(default=False, description="return the NEWEST `limit` messages (oldest-first) instead of the oldest"),
    current_user: BusinessUser = Depends(require_role(_INBOX_ROLES)),
    db: Session = Depends(get_db),
) -> list[InboxMessage]:
    """The whole thread, oldest first — customer, AI and staff messages from every channel through one query — with each
    message's delivery status. Poll with `after=<last id you have>` for near-real-time updates."""
    conversation = _load(db, conversation_id, current_user)
    return [_message_out(m, e) for m, e in inbox_service.list_thread(db, conversation=conversation, after_message_id=after, limit=limit, latest=latest)]


@router.post("/inbox/conversations/{conversation_id}/reply", response_model=InboxMessage, status_code=201)
def reply_to_conversation(
    conversation_id: uuid.UUID,
    payload: ReplyRequest,
    current_user: BusinessUser = Depends(require_role(_INBOX_ROLES)),
    db: Session = Depends(get_db),
) -> InboxMessage:
    """Send a staff reply to the customer on their real channel. Claims the conversation (the AI goes silent for the
    sliding takeover window). 409 when the reply can't be delivered (24h window closed / channel not connected) or the
    conversation is momentarily busy; the same `client_msg_id` sent twice returns the first message and sends nothing again.
    A send Meta rejects still returns 201 with `delivery_status: "failed"` and the reason in `delivery_detail`."""
    conversation = _load(db, conversation_id, current_user)
    message = inbox_service.send_staff_reply(
        db, conversation=conversation, user=current_user, content=payload.content, client_msg_id=payload.client_msg_id
    )
    author = db.get(BusinessUser, message.sent_by_user_id) if message.sent_by_user_id else None
    return _message_out(message, author.email if author else None)


@router.get("/inbox/conversations", response_model=list[InboxListItem])
def list_inbox_conversations(
    tab: Literal["all", "needs_reply", "handoffs", "leads"] = Query(default="all"),
    channel: Literal["whatsapp", "messenger", "instagram", "website"] | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100, description="customer name contains"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: BusinessUser = Depends(require_role(_INBOX_ROLES)),
    db: Session = Depends(get_db),
) -> list[InboxListItem]:
    """The inbox home: every conversation across every channel, newest activity first. `needs_reply` = a human is responsible
    (open handoff or a staff member owns it) and the customer spoke last; `unread` = the customer's latest message is newer
    than the last time staff opened it; `tab=leads` = automatic buying-intent triage (lead_signal="high", scored in the
    background -- see app/services/lead_service.py), not a customer-vs-staff turn signal like the other two tabs."""
    rows = inbox_service.list_conversations(
        db, business_id=current_user.business_id, tab=tab, channel=channel, q=q, limit=limit, offset=offset
    )
    return [
        InboxListItem(
            id=r.id,
            channel=r.channel,
            customer_name=r.customer_name,
            last_message_preview=(r.content or "")[:160],
            last_message_sender=r.sender_type.value,
            last_message_at=_utc(r.last_at),
            last_message_delivery_status=r.delivery_status,
            needs_reply=bool(r.needs_reply),
            unread=bool(r.unread),
            open_handoff=bool(r.open_handoff),
            takeover_active=bool(r.takeover_active),
            takeover_by_email=r.takeover_by_email if r.takeover_active else None,
            lead_signal=r.lead_signal,
        )
        for r in rows
    ]


@router.get("/inbox/summary", response_model=InboxSummary)
def inbox_summary(
    current_user: BusinessUser = Depends(require_role(_INBOX_ROLES)), db: Session = Depends(get_db)
) -> InboxSummary:
    """Counts for the sidebar badges: conversations waiting for a person, conversations with an open handoff, and
    high-intent leads."""
    waiting, handoffs, leads = inbox_service.summary(db, business_id=current_user.business_id)
    return InboxSummary(needs_reply=waiting, handoffs=handoffs, leads=leads)


@router.post("/inbox/conversations/{conversation_id}/read", status_code=204)
def mark_conversation_read(
    conversation_id: uuid.UUID,
    current_user: BusinessUser = Depends(require_role(_INBOX_ROLES)),
    db: Session = Depends(get_db),
) -> None:
    """Staff opened this conversation: clears its `unread` flag (shared across staff)."""
    inbox_service.mark_read(db, _load(db, conversation_id, current_user))
