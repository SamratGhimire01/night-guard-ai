import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.channel_identity import ChannelIdentity
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
    {phone_number_id, wa_id, bsuid, contact_name, message_id, text} — `wa_id` is the address to reply to: the sender's
    phone number, or their BSUID when Meta withholds the number (WhatsApp usernames); `bsuid` is the BSUID whenever
    Meta sent one (None on older-format payloads).

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
            # A contact is keyed by phone (`wa_id`) and/or business-scoped user id (`user_id`, the BSUID) — a user with a
            # WhatsApp username has ONLY the latter.
            contacts = {}
            for c in value.get("contacts", []) or []:
                for key in (c.get("wa_id"), c.get("user_id")):
                    if key:
                        contacts[key] = (c.get("profile") or {}).get("name")
            for message in value.get("messages", []) or []:
                if message.get("type") != "text":
                    continue
                text_body = (message.get("text") or {}).get("body")
                # Real bug found live (Phase 50): when the sender has a WhatsApp username, Meta OMITS `from` (their phone
                # number) and sends only `from_user_id` (a BSUID such as "NP.2887…"). Requiring `from` silently dropped
                # every message from such a user — no reply, no conversation, nothing in the logs. The reply address is
                # the phone when present, else the BSUID (which the Cloud API accepts as `recipient`, see
                # WhatsAppChannelAdapter.send_message).
                bsuid = message.get("from_user_id")
                wa_id = message.get("from") or bsuid
                message_id = message.get("id")
                if not (phone_number_id and wa_id and message_id and text_body):
                    continue
                results.append(
                    {
                        "phone_number_id": phone_number_id,
                        "wa_id": wa_id,
                        "bsuid": bsuid,
                        "contact_name": contacts.get(message.get("from")) or contacts.get(bsuid),
                        "message_id": message_id,
                        "text": text_body,
                    }
                )
    return results


def _resolve_integration(db: Session, *, phone_number_id: str) -> Integration | None:
    """Which tenant owns this Meta phone_number_id? A single Meta App/WABA
    can send on behalf of several registered numbers, one per Night Guard AI
    business — Integration (Phase 2's model) is the real, already-modeled
    place for that per-tenant mapping: type="whatsapp",
    config={"phone_number_id": "...", "access_token": "..."}. Returns the
    full row (not just business_id) since send_message also needs this
    business's own saved access token out of `config` — see
    WhatsAppChannelAdapter.send_message's docstring on the platform-wide
    fallback."""
    return db.execute(
        select(Integration).where(
            Integration.type == "whatsapp",
            Integration.enabled.is_(True),
            Integration.config["phone_number_id"].astext == phone_number_id,
        )
    ).scalar_one_or_none()


def _link_bsuid_alias(db: Session, *, business_id, wa_id: str, bsuid: str | None) -> None:
    """When Meta sends BOTH a phone number and a BSUID, remember the BSUID as a second identity of the SAME customer, so
    if that person later turns on a username (Meta then omits the number) their messages still land in the same
    customer/conversation instead of starting a stranger. Best-effort: never raises."""
    if not bsuid or bsuid == wa_id:
        return
    try:
        identity = db.execute(
            select(ChannelIdentity).where(
                ChannelIdentity.business_id == business_id,
                ChannelIdentity.channel == "whatsapp",
                ChannelIdentity.external_ref == wa_id,
            )
        ).scalar_one_or_none()
        if identity is None:
            return
        db.add(
            ChannelIdentity(
                business_id=business_id, channel="whatsapp", external_ref=bsuid, customer_id=identity.customer_id
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()  # already linked (the unique constraint is the real guard)
    except Exception:
        db.rollback()
        logger.exception("whatsapp webhook: could not link BSUID alias (non-fatal)")


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
        integration = _resolve_integration(db, phone_number_id=incoming["phone_number_id"])
        if integration is None:
            logger.warning("whatsapp webhook: no business registered for phone_number_id=%s", incoming["phone_number_id"])
            outcomes.append({"message_id": incoming["message_id"], "status": "unknown_phone_number_id"})
            continue
        business_id = integration.business_id

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

        _link_bsuid_alias(db, business_id=business_id, wa_id=incoming["wa_id"], bsuid=incoming.get("bsuid"))
        send_detail = _adapter.send_message(
            to=incoming["wa_id"],
            text=result["response"],
            phone_number_id=incoming["phone_number_id"],
            access_token=(integration.config or {}).get("access_token") or "",
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
