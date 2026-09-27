import uuid
from abc import ABC, abstractmethod

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.db.models.customer import Customer
from app.services.conversation.orchestrator import handle_incoming_message

# Every ChannelAdapter shares this one open-conversation-per-customer-per-
# channel convention. "open" here just means "not explicitly closed" — Phase
# 8 never introduced a close action, so in practice this is "the most
# recently created conversation for this customer on this channel."
_OPEN_STATUS = "open"


def get_or_create_conversation(
    db: Session, *, business_id: uuid.UUID, channel: str, external_ref: str, default_customer_name: str
) -> Conversation:
    """The real, shared "find-or-create Customer + Conversation for this
    external contact" plumbing every ChannelAdapter reuses — this is what
    makes the conversation engine channel-agnostic: a future WhatsApp/
    Messenger/Instagram adapter calls this exact function with its own
    channel name and external_ref (a phone number, a PSID, ...) and gets the
    same Customer/Conversation resolution behavior the website widget uses
    today, with zero new logic.

    `external_ref` is resolved through ChannelIdentity, never used as a
    Customer field directly — a Customer may in principle be reachable
    through more than one channel identity over time.
    """
    identity = db.execute(
        select(ChannelIdentity).where(
            ChannelIdentity.business_id == business_id,
            ChannelIdentity.channel == channel,
            ChannelIdentity.external_ref == external_ref,
        )
    ).scalar_one_or_none()

    if identity is None:
        customer = Customer(business_id=business_id, name=default_customer_name)
        db.add(customer)
        db.flush()
        identity = ChannelIdentity(
            business_id=business_id, channel=channel, external_ref=external_ref, customer_id=customer.id
        )
        db.add(identity)
        db.commit()
        db.refresh(customer)
    else:
        customer = db.get(Customer, identity.customer_id)

    conversation = db.execute(
        select(Conversation)
        .where(
            Conversation.business_id == business_id,
            Conversation.customer_id == customer.id,
            Conversation.channel == channel,
            Conversation.status == _OPEN_STATUS,
        )
        .order_by(Conversation.created_at.desc())
    ).scalars().first()

    if conversation is None:
        conversation = Conversation(
            business_id=business_id, customer_id=customer.id, channel=channel, status=_OPEN_STATUS
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    return conversation


def record_non_text_message(
    db: Session,
    *,
    business_id: uuid.UUID,
    channel: str,
    external_ref: str,
    placeholder: str,
    external_message_id: str,
    default_customer_name: str,
) -> Conversation:
    """Store what a customer sent that isn't text (a photo, a voice note, …) as a real CUSTOMER message reading e.g.
    "[Customer sent an image]", so staff reading the conversation see that something arrived — before Phase 52 these were
    dropped without a trace. The AI is NOT invoked for it (it can't read the attachment; before, the customer got silence
    too) and no reply is sent. Idempotent on `external_message_id` (the caller catches the IntegrityError of a redelivery)."""
    conversation = get_or_create_conversation(
        db, business_id=business_id, channel=channel, external_ref=external_ref, default_customer_name=default_customer_name
    )
    db.add(
        Message(
            conversation_id=conversation.id,
            sender_type=MessageSenderType.CUSTOMER,
            content=placeholder,
            external_message_id=external_message_id,
        )
    )
    db.commit()
    return conversation


class ChannelAdapter(ABC):
    """One implementation per external channel. The ONLY job of an adapter is
    channel-specific plumbing (session/identity handling, payload shape) —
    the actual conversation intelligence is always Phase 8's orchestrator,
    called identically by every adapter. A future channel adapter should
    never need to touch app/services/conversation/ at all.
    """

    channel: str

    @abstractmethod
    def receive_message(
        self,
        db: Session,
        *,
        business_id: uuid.UUID,
        external_customer_ref: str,
        content: str,
        external_message_id: str | None = None,
        force_language: str | None = None,
        deliver=None,
    ) -> dict | None:
        """Returns the same dict handle_incoming_message returns
        ({"intent", "response", "customer_message_id", "agent_message_id"}),
        or None if business_id doesn't resolve to a real business.

        `external_message_id` (Phase 22): optional — only channels with a
        real webhook-delivery id (WhatsApp's message id) pass this, for the
        real DB-level idempotency guarantee on Message.external_message_id.
        Channels without that concept (website) simply never pass it.

        `force_language` (Phase 43h): optional — only the website widget's
        voice-message route ever passes this (a spoken-Nepali override, see
        widget_service.send_widget_message). Every other caller leaves it
        None, unaffected."""
        raise NotImplementedError


class WebsiteChannelAdapter(ChannelAdapter):
    channel = "website"

    def receive_message(
        self,
        db: Session,
        *,
        business_id: uuid.UUID,
        external_customer_ref: str,
        content: str,
        external_message_id: str | None = None,
        force_language: str | None = None,
        deliver=None,
    ) -> dict | None:
        conversation = get_or_create_conversation(
            db,
            business_id=business_id,
            channel=self.channel,
            external_ref=external_customer_ref,
            default_customer_name="Website Visitor",
        )
        # The exact same Phase 8 orchestrator every other channel/testing path
        # already goes through — no parallel/simplified conversation logic.
        return handle_incoming_message(
            db,
            conversation_id=conversation.id,
            business_id=business_id,
            content=content,
            external_message_id=external_message_id,
            force_language=force_language,
            deliver=deliver,
        )
