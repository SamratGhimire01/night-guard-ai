import hashlib
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Conversation
from app.services.channels.base import WebsiteChannelAdapter

_website_adapter = WebsiteChannelAdapter()

_SESSION_TOKEN_BYTES = 32  # 256 bits — cryptographically infeasible to guess


def generate_session_token() -> str:
    return secrets.token_urlsafe(_SESSION_TOKEN_BYTES)


def _hash_token(token: str) -> str:
    """The raw token is a bearer secret handed to an anonymous browser and
    never stored server-side — only this SHA-256 hash goes into
    ChannelIdentity.external_ref. A database leak alone does not hand an
    attacker a working session token, unlike storing the raw value would."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _resolve_session_token(db: Session, *, business_id: uuid.UUID, client_token: str | None) -> tuple[str, str]:
    """Returns (token_to_use, external_ref) for this request.

    SESSION ISOLATION — the ticket's explicit threat-model ask, resolved the
    safer of the two named ways: a client-supplied token that's missing,
    malformed, or simply doesn't match any known identity FOR THIS business
    is never trusted or echoed back — a brand-new, server-generated session is
    minted instead, silently. This means there is no "wrong token" vs.
    "expired session" vs. "someone else's token" vs. "cross-business replay"
    distinction anywhere in this function's behavior or the route's response:
    every one of those cases collapses into "start fresh," so there is no
    oracle an attacker can probe to learn whether a guessed/stolen token was
    close to valid. A token is only ever trusted when its hash matches a real,
    previously-issued ChannelIdentity row scoped to this exact business_id —
    so a token issued by Business A can never resolve to anything on Business
    B; it will simply, silently, mint Business B a brand-new session instead.
    """
    if client_token:
        external_ref = _hash_token(client_token)
        exists = db.execute(
            select(ChannelIdentity.id).where(
                ChannelIdentity.business_id == business_id,
                ChannelIdentity.channel == _website_adapter.channel,
                ChannelIdentity.external_ref == external_ref,
            )
        ).scalar_one_or_none()
        if exists is not None:
            return client_token, external_ref

    token = generate_session_token()
    return token, _hash_token(token)


def get_locked_language(db: Session, *, business_id: uuid.UUID, session_token: str | None) -> str | None:
    """Phase 43b: a real, side-effect-free lookup of the Phase 25 language
    lock (Conversation.detected_language) for an EXISTING session -- used by
    the voice route to pick the right Deepgram STT language before the
    call's very first utterance even exists. Never creates a
    ChannelIdentity/Conversation (unlike get_or_create_conversation) and
    returns None for a brand-new/missing/unrecognized token -- all of which
    mean "cold start, no lock yet" to the caller."""
    if not session_token:
        return None
    external_ref = _hash_token(session_token)
    identity = db.execute(
        select(ChannelIdentity).where(
            ChannelIdentity.business_id == business_id,
            ChannelIdentity.channel == _website_adapter.channel,
            ChannelIdentity.external_ref == external_ref,
        )
    ).scalar_one_or_none()
    if identity is None:
        return None

    conversation = db.execute(
        select(Conversation)
        .where(
            Conversation.business_id == business_id,
            Conversation.customer_id == identity.customer_id,
            Conversation.channel == _website_adapter.channel,
            Conversation.status == "open",
        )
        .order_by(Conversation.created_at.desc())
    ).scalars().first()
    return conversation.detected_language if conversation else None


def get_widget_config(db: Session, *, business_id: uuid.UUID) -> Business | None:
    """Returns the real Business row for public branding lookup, or None if
    business_id doesn't resolve (route turns that into a 404, same as
    send_widget_message below)."""
    return db.get(Business, business_id)


def send_widget_message(
    db: Session,
    *,
    business_id: uuid.UUID,
    session_token: str | None,
    content: str,
    force_language: str | None = None,
) -> tuple[str, dict] | None:
    """Returns (session_token_to_use, orchestrator_result_dict), or None if
    business_id doesn't resolve to a real business (the route turns that into
    a 404 — see PHASE_STATUS.md for why that's not treated as a meaningful
    business_id-enumeration leak here).

    `force_language` (Phase 43h): only ever passed by the voice-message route,
    for a turn whose SPOKEN input was detected as Nepali — forces this one
    reply into Romanized Nepali regardless of the conversation's own
    text-based language lock. None (every typed-text caller) means "normal
    Phase 25/25b behavior," completely unchanged."""
    business = db.get(Business, business_id)
    if business is None:
        return None

    token, external_ref = _resolve_session_token(db, business_id=business_id, client_token=session_token)

    # The exact same Phase 8 orchestrator every other channel/testing path
    # already goes through — no parallel/simplified conversation logic.
    result = _website_adapter.receive_message(
        db,
        business_id=business_id,
        external_customer_ref=external_ref,
        content=content,
        force_language=force_language,
    )
    return token, result
