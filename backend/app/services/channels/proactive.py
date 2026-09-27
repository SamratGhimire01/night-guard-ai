import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.services import integration_service
from app.services.channels import delivery
from app.services.channels.instagram import InstagramChannelAdapter
from app.services.channels.messenger import MessengerChannelAdapter
from app.services.channels.whatsapp import WhatsAppChannelAdapter, is_bsuid

logger = logging.getLogger(__name__)


def push_to_channel(db: Session, *, conversation: Conversation, text: str) -> str:
    """Push `text` to the customer on the conversation's own channel, using the business's saved credentials, and return a
    short status string ("sent wamid=…", "simulated — …", "failed: HTTP 400", "recorded for widget poll", "recorded; …"). The
    website widget has no push channel — it picks the recorded Message up on its next poll (widget.js -> GET .../updates).
    Never raises. Shared by system messages (`send_to_conversation`) and staff replies (inbox_service)."""
    if conversation.channel == "website":
        return "recorded for widget poll"
    try:
        identities = db.execute(
            select(ChannelIdentity).where(
                ChannelIdentity.business_id == conversation.business_id,
                ChannelIdentity.channel == conversation.channel,
                ChannelIdentity.customer_id == conversation.customer_id,
            )
        ).scalars().all()
        # a WhatsApp customer may have both a phone identity and a BSUID alias: prefer the phone number
        identity = min(identities, key=lambda i: is_bsuid(i.external_ref), default=None)
        integration = integration_service.get_integration(
            db, business_id=conversation.business_id, type_=conversation.channel
        )
        if identity is None or integration is None or not integration.enabled:
            return "recorded; no connected channel to push to"
        config = integration.config or {}
        if conversation.channel == "whatsapp":
            return WhatsAppChannelAdapter().send_message(
                to=identity.external_ref,
                text=text,
                phone_number_id=config.get("phone_number_id") or "",
                access_token=config.get("access_token") or "",
            )
        if conversation.channel == "messenger":
            return MessengerChannelAdapter().send_message(
                psid=identity.external_ref, text=text, page_access_token=config.get("page_access_token") or ""
            )
        if conversation.channel == "instagram":
            return InstagramChannelAdapter().send_message(
                igsid=identity.external_ref,
                text=text,
                # the professional account id — the same one the webhook reply path sends with (entry[].id)
                ig_account_id=config.get("ig_user_id") or config.get("ig_account_id") or "",
                access_token=config.get("access_token") or "",
            )
        return f"recorded; no push for channel {conversation.channel!r}"
    except Exception:
        logger.exception("proactive send failed for conversation_id=%s", conversation.id)
        return "recorded; push failed"


def send_to_conversation(db: Session, *, conversation: Conversation, text: str) -> str:
    """A message the SYSTEM starts (not a reply to a customer turn) into the conversation it belongs to: recorded as an
    AGENT Message, then pushed out through `push_to_channel`, and what happened is stored on that message
    (delivery_status/detail). Never raises: the caller (a payment confirmation) has already succeeded and must not be
    undone by a failed chat send; returns a short description of what happened."""
    message = Message(conversation_id=conversation.id, sender_type=MessageSenderType.AGENT, content=text)
    db.add(message)
    db.commit()
    detail = push_to_channel(db, conversation=conversation, text=text)
    try:
        message.delivery_status = delivery.status_from_detail(detail)
        message.delivery_detail = detail[:255]
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("could not record delivery status for conversation_id=%s (non-fatal)", conversation.id)
    return detail
