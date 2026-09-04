import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.conversation import Message
from app.db.models.integration import Integration
from app.services.channels.meta_webhook_signature import verify_signature
from app.services.channels.whatsapp import WhatsAppChannelAdapter

logger = logging.getLogger(__name__)

_adapter = WhatsAppChannelAdapter()

# Re-exported (Phase 26 moved the real implementation to
# meta_webhook_signature.py, shared with messenger_webhook.py — the HMAC
# mechanism is genuinely identical across Meta webhook products) so
# app/api/routes/webhooks.py's existing `from ...whatsapp_webhook import
# verify_signature` keeps working unchanged.
__all__ = ["verify_signature", "process_webhook_payload", "extract_incoming_text_messages"]


def extract_incoming_text_messages(payload: dict) -> list[dict]:
    """Walks Meta's real webhook envelope shape
    (entry[].changes[].value.{metadata,contacts,messages}[]) and returns one
    normalized dict per real incoming TEXT message found:
    {phone_number_id, wa_id, contact_name, message_id, text}.

    Deliberately tolerant, not a strict schema: Meta sends the same endpoint
    for message-status webhooks (delivered/read receipts, no "messages" key)
    and non-text message types (images, buttons, ...) this phase doesn't
    handle — both are silently skipped, never a 500, since raising here would
    make Meta retry-storm us over an event we simply don't act on.
    """
    results = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
            contacts = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts", []) or []}
            for message in value.get("messages", []) or []:
                if message.get("type") != "text":
                    continue
                text_body = (message.get("text") or {}).get("body")
                wa_id = message.get("from")
                message_id = message.get("id")
                if not (phone_number_id and wa_id and message_id and text_body):
                    continue
                results.append(
                    {
                        "phone_number_id": phone_number_id,
                        "wa_id": wa_id,
                        "contact_name": contacts.get(wa_id),
                        "message_id": message_id,
                        "text": text_body,
                    }
                )
    return results


def _resolve_business_id(db: Session, *, phone_number_id: str) -> uuid.UUID | None:
    """Which tenant owns this Meta phone_number_id? A single Meta App/WABA
    (one WHATSAPP_ACCESS_TOKEN) can send on behalf of several registered
    numbers, one per Night Guard AI business — Integration (Phase 2's model,
    previously unused, same "give an existing-but-empty model its first real
    producer" pattern as Phase 19's HumanHandoff) is the real, already-modeled
    place for that per-tenant mapping: type="whatsapp",
    config={"phone_number_id": "..."}. No connect-your-WhatsApp-number UI
    exists yet (out of this phase's scope, same honest gap as "no staff-invite
    endpoint" in earlier phases) — a real Integration row is inserted directly
    for testing, exactly like those precedents."""
    integration = db.execute(
        select(Integration).where(
            Integration.type == "whatsapp",
            Integration.enabled.is_(True),
            Integration.config["phone_number_id"].astext == phone_number_id,
        )
    ).scalar_one_or_none()
    return integration.business_id if integration else None


def process_webhook_payload(db: Session, payload: dict) -> list[dict]:
    """The real webhook-processing pipeline: for every real incoming text
    message in this payload, resolve its tenant, skip it if already processed
    (real idempotency — see Message.external_message_id), run it through the
    exact same WhatsAppChannelAdapter -> Phase 8 orchestrator every other
    entry point uses, then send the real reply back over WhatsApp (or a safe
    simulation — see WhatsAppChannelAdapter.send_message).

    Returns a list of per-message outcomes for logging/testing — this is
    NEVER sent back to Meta itself: the webhook route always acks with a
    plain 200 regardless of what happened here, exactly per Meta's own
    contract (a non-200/slow response makes Meta retry-storm the webhook).
    """
    outcomes = []
    for incoming in extract_incoming_text_messages(payload):
        business_id = _resolve_business_id(db, phone_number_id=incoming["phone_number_id"])
        if business_id is None:
            logger.warning("whatsapp webhook: no business registered for phone_number_id=%s", incoming["phone_number_id"])
            outcomes.append({"message_id": incoming["message_id"], "status": "unknown_phone_number_id"})
            continue

        already = db.execute(
            select(Message.id).where(Message.external_message_id == incoming["message_id"])
        ).scalar_one_or_none()
        if already is not None:
            logger.info("whatsapp webhook: duplicate message_id=%s, skipping", incoming["message_id"])
            outcomes.append({"message_id": incoming["message_id"], "status": "duplicate_skipped"})
            continue

        try:
            result = _adapter.receive_message(
                db,
                business_id=business_id,
                external_customer_ref=incoming["wa_id"],
                content=incoming["text"],
                external_message_id=incoming["message_id"],
            )
        except IntegrityError:
            # Real backstop for a genuine race between two concurrent
            # deliveries of the identical webhook — the unique constraint on
            # external_message_id rejected the second insert. Same
            # "IntegrityError means already handled" discipline as Phase
            # 18/19's own DB-constraint backstops.
            db.rollback()
            logger.info("whatsapp webhook: race caught by DB constraint for message_id=%s", incoming["message_id"])
            outcomes.append({"message_id": incoming["message_id"], "status": "duplicate_skipped"})
            continue

        if result is None:
            outcomes.append({"message_id": incoming["message_id"], "status": "business_not_found"})
            continue

        send_detail = _adapter.send_message(
            to=incoming["wa_id"], text=result["response"], phone_number_id=incoming["phone_number_id"]
        )
        outcomes.append(
            {
                "message_id": incoming["message_id"],
                "status": "processed",
                "intent": result["intent"].value,
                "response": result["response"],
                "send_detail": send_detail,
            }
        )
    return outcomes
