import logging

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.conversation import Message
from app.db.models.integration import Integration
from app.services.channels.base import record_non_text_message
from app.services.channels.delivery import send_in_bubbles
from app.services.channels.instagram import InstagramChannelAdapter
from app.services.channels.meta_messaging_webhook import extract_incoming_non_text_messages
from app.services.channels.meta_messaging_webhook import (
    extract_incoming_text_messages as _extract_from_messaging_shape,
)

logger = logging.getLogger(__name__)

_adapter = InstagramChannelAdapter()

__all__ = ["extract_incoming_text_messages", "process_webhook_payload"]


def _extract_from_changes_shape(payload: dict) -> list[dict]:
    """Instagram-only second envelope shape: Meta's Graph API "Test" button
    for the `messages` field (confirmed via a real "Send to My Server" test
    against this endpoint) delivers `entry[].changes[]` with
    `{"field": "messages", "value": {...}}` instead of `entry[].messaging[]`
    — the message data (sender/recipient/message.mid/message.text) lives
    under `value` rather than directly on the event. Same normalized output
    shape as the shared parser. Messenger's real captured traffic has only
    ever used `entry[].messaging[]`, so this stays local to Instagram rather
    than folded into meta_messaging_webhook.py's shared parser."""
    results = []
    for entry in payload.get("entry", []) or []:
        account_id = entry.get("id")
        for change in entry.get("changes", []) or []:
            if change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            message = value.get("message") or {}
            if not message or message.get("is_echo"):
                continue
            text = message.get("text")
            sender_id = (value.get("sender") or {}).get("id")
            message_id = message.get("mid")
            if not (account_id and sender_id and message_id and text):
                continue
            results.append(
                {"account_id": account_id, "sender_id": sender_id, "message_id": message_id, "text": text}
            )
    return results


def extract_incoming_text_messages(payload: dict) -> list[dict]:
    """Instagram accepts both real envelope shapes Meta has been observed to
    send for the `messages` field: the shared `entry[].messaging[]` shape
    (meta_messaging_webhook.py) and `entry[].changes[]` with
    `{"field": "messages", "value": {...}}` (confirmed via Meta's own "Send
    to My Server" test tool). Messenger keeps using only the shared parser
    directly — this dual handling is Instagram-specific."""
    return _extract_from_messaging_shape(payload) + _extract_from_changes_shape(payload)


def _resolve_integration(db: Session, *, ig_account_id: str) -> Integration | None:
    """Which tenant owns this Instagram professional account? Same pattern as
    Phase 26's page_id -> business_id resolution, reusing the same
    already-generic Integration model with zero schema changes:
    type="instagram", config={"ig_account_id": ..., "access_token": ...}.
    Returns the full Integration row (not just business_id) since
    send_message also needs this business's own per-account access token out
    of `config` — same reasoning as Messenger's page_access_token (Instagram
    has no platform-wide token either)."""
    # Matches EITHER id Instagram gives the account: the typed `ig_account_id`, or `ig_user_id` (the professional account id
    # Meta puts in every webhook's entry[].id — stored automatically on save). Before this, a business that had typed the
    # other id had every inbound DM silently dropped with only a log line ("no business registered").
    return db.execute(
        select(Integration).where(
            Integration.type == "instagram",
            Integration.enabled.is_(True),
            or_(
                Integration.config["ig_account_id"].astext == ig_account_id,
                Integration.config["ig_user_id"].astext == ig_account_id,
            ),
        )
    ).scalar_one_or_none()


def process_webhook_payload(db: Session, payload: dict) -> list[dict]:
    """The real webhook-processing pipeline — same shape as WhatsApp's/
    Messenger's process_webhook_payload, reusing the real, genuinely-shared
    entry[].messaging[] parser (meta_messaging_webhook.py) unchanged: for
    every real incoming text message, resolve its tenant, skip it if already
    processed (real idempotency, reusing Message.external_message_id's
    unique constraint — see the note below), run it through the exact same
    InstagramChannelAdapter -> Phase 8 orchestrator every other entry point
    uses, then send the real reply back (or a safe simulation).

    Idempotency column reuse, explicitly justified (same reasoning already
    applied to Messenger in Phase 26): Instagram message ids (opaque base64-
    ish strings, e.g. "aWdfZAG1lOm...") and WhatsApp/Messenger message ids
    are generated by different Meta subsystems with visibly different
    formats — cross-channel collision is not a real risk, so this reuses
    Message.external_message_id rather than adding a third column/migration
    for a namespace clash that isn't actually possible in practice. Even in a
    pathological collision, the failure mode is a dropped duplicate-looking
    message (logged, acked), never data corruption or cross-tenant leakage.

    Returns per-message outcomes for logging/testing only — NEVER sent back
    to Meta; the webhook route always acks with a plain 200 once past
    signature verification, per Meta's own documented webhook contract.
    """
    outcomes = []
    for incoming in extract_incoming_text_messages(payload):
        integration = _resolve_integration(db, ig_account_id=incoming["account_id"])
        if integration is None:
            logger.warning("instagram webhook: no business registered for ig_account_id=%s", incoming["account_id"])
            outcomes.append({"message_id": incoming["message_id"], "status": "unknown_ig_account_id"})
            continue
        business_id = integration.business_id

        already = db.execute(
            select(Message.id).where(Message.external_message_id == incoming["message_id"])
        ).scalar_one_or_none()
        if already is not None:
            logger.info("instagram webhook: duplicate message_id=%s, skipping", incoming["message_id"])
            outcomes.append({"message_id": incoming["message_id"], "status": "duplicate_skipped"})
            continue

        try:
            result = _adapter.receive_message(
                db,
                business_id=business_id,
                external_customer_ref=incoming["sender_id"],
                content=incoming["text"],
                external_message_id=incoming["message_id"],
                # Long replies go out as up to 3 DMs (delivery.send_in_bubbles); the Message row keeps the full text.
                deliver=lambda text, incoming=incoming, integration=integration: send_in_bubbles(
                    text,
                    lambda bubble: _adapter.send_message(
                        igsid=incoming["sender_id"],
                        text=bubble,
                        ig_account_id=incoming["account_id"],
                        access_token=(integration.config or {}).get("access_token") or "",
                    ),
                    channel="Instagram",
                ),
            )
        except IntegrityError:
            # Real backstop for a genuine race between two concurrent
            # deliveries of the identical webhook — same "IntegrityError
            # means already handled" discipline as WhatsApp/Messenger.
            db.rollback()
            logger.info("instagram webhook: race caught by DB constraint for message_id=%s", incoming["message_id"])
            outcomes.append({"message_id": incoming["message_id"], "status": "duplicate_skipped"})
            continue

        if result is None:
            outcomes.append({"message_id": incoming["message_id"], "status": "business_not_found"})
            continue

        if result.get("response") is None:
            # Phase 52: a staff member owns this conversation -- the customer's message is stored (inbox), nothing is sent.
            outcomes.append({"message_id": incoming["message_id"], "status": "human_takeover"})
            continue

        send_detail = result.get("delivery_detail")
        outcomes.append(
            {
                "message_id": incoming["message_id"],
                "status": "processed",
                "intent": result["intent"].value,
                "response": result["response"],
                "send_detail": send_detail,
            }
        )
    for incoming in extract_incoming_non_text_messages(payload):
        integration = _resolve_integration(db, ig_account_id=incoming["account_id"])
        if integration is None:
            outcomes.append({"message_id": incoming["message_id"], "status": "unknown_account_id"})
            continue
        try:
            record_non_text_message(
                db,
                business_id=integration.business_id,
                channel="instagram",
                external_ref=incoming["sender_id"],
                placeholder=incoming["placeholder"],
                external_message_id=incoming["message_id"],
                default_customer_name="Instagram Contact",
            )
        except IntegrityError:
            db.rollback()  # a redelivery of a message we already stored
            outcomes.append({"message_id": incoming["message_id"], "status": "duplicate_skipped"})
            continue
        outcomes.append({"message_id": incoming["message_id"], "status": "non_text_recorded"})
    return outcomes
