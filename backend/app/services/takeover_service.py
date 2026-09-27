"""Phase 52 — human takeover: while a staff member owns a conversation the AI must stay silent.

State is two columns on the conversation (`human_takeover_until`, `human_takeover_by`). "Active" is always derived from the
clock (`until > now()`), so expiry needs no job: 2 hours after the last staff reply the AI is simply back in charge.

`is_active` deliberately reads the COLUMN from the database, never the ORM object: the orchestrator calls it a second time
right after its multi-second LLM call to catch a staff reply that landed mid-turn, and the object it holds was loaded before
that reply was committed (and refreshing it would throw away the turn's own unflushed draft-state changes).
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError
from app.db.database import engine
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Conversation

logger = logging.getLogger(__name__)

# How long a staff claim waits for an in-flight AI reply to finish delivering before giving up with a retryable 409. An AI
# reply's locked section is a few DB writes plus ONE channel send (the adapters time out at 15s), so this is generous.
CLAIM_LOCK_TIMEOUT_SECONDS = 30


class ReplyLock:
    """Per-conversation mutual exclusion between "the AI is about to DELIVER a reply" and "a staff member is CLAIMING the
    conversation" — what closes the race the two `is_active` checkpoints alone cannot: a claim committing after the AI's last
    check but before its message actually reaches the customer.

    Protocol (each side, for one conversation):
      AI    acquire -> is_active() -> (active? give up : persist reply + DELIVER to the channel) -> release
      staff acquire -> set human_takeover_until -> commit -> release
    Whichever gets the lock first wins cleanly: if staff wins, the AI's check under the lock sees the takeover and discards
    its draft; if the AI wins, its reply is fully delivered BEFORE the claim can commit (staff then speaks after it — sequential,
    never simultaneous). A claim can therefore never commit while an AI reply is between "last check" and "sent".

    Implementation: a Postgres SESSION-level advisory lock on a DEDICATED connection. It has to be session-level (the AI turn
    commits several times, which would drop a transaction-level lock) and it has to be a connection of its own (the turn's
    Session hands its connection back to the pool on every commit, and a session-level lock belongs to the connection, not to
    the Session). Held only for the short delivery section, never across an LLM call. Every caller releases in a `finally`;
    if the process dies the connection dies and Postgres frees the lock.

    `timeout_seconds=None` waits indefinitely (the AI side: the holder is a staff claim, which is a single quick UPDATE);
    a number raises ConflictError (409, retryable) if the lock isn't free in time (the staff side)."""

    def __init__(self, conversation_id: uuid.UUID, *, timeout_seconds: int | None = None):
        self._key = str(conversation_id)
        self._timeout = timeout_seconds
        self._conn = None

    @property
    def held(self) -> bool:
        return self._conn is not None

    def acquire(self) -> None:
        if self._conn is not None:
            return
        conn = engine.connect()
        try:
            if self._timeout is not None:
                conn.execute(text(f"SET LOCAL lock_timeout = '{int(self._timeout)}s'"))
            conn.execute(text("SELECT pg_advisory_lock(hashtextextended(:k, 0))"), {"k": self._key})
            conn.commit()  # ends the transaction (drops the SET LOCAL); the session-level lock stays held
        except OperationalError as exc:
            conn.close()
            raise ConflictError("This conversation is busy (an automated reply is being delivered). Please retry.") from exc
        except BaseException:
            conn.close()
            raise
        self._conn = conn

    def release(self) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            conn.execute(text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))"), {"k": self._key})
            conn.commit()
        except Exception:
            logger.exception("could not release the reply lock for conversation %s; dropping its connection", self._key)
            conn.invalidate()  # closing the DB session releases every lock it held
        finally:
            conn.close()

    def __enter__(self) -> "ReplyLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def is_active(db: Session, *, conversation_id: uuid.UUID) -> bool:
    """True while a human owns the conversation. Compared by Postgres, so no timezone/clock-skew handling here.
    clock_timestamp(), not now(): now() is the START of the current transaction, which for the post-LLM checkpoint is
    seconds in the past."""
    return bool(
        db.execute(
            select(Conversation.human_takeover_until > func.clock_timestamp()).where(Conversation.id == conversation_id)
        ).scalar()
    )


def is_active_for_contact(db: Session, *, business_id: uuid.UUID, channel: str, external_ref: str) -> bool:
    """Read-only twin for the webhook layer, which knows only the channel + external contact (not the conversation id yet)
    and wants to skip the "typing…" indicator when no AI reply is going to follow. Never creates anything."""
    return bool(
        db.execute(
            select(Conversation.human_takeover_until > func.clock_timestamp())
            .join(
                ChannelIdentity,
                (ChannelIdentity.customer_id == Conversation.customer_id)
                & (ChannelIdentity.business_id == Conversation.business_id)
                & (ChannelIdentity.channel == Conversation.channel),
            )
            .where(
                ChannelIdentity.business_id == business_id,
                ChannelIdentity.channel == channel,
                ChannelIdentity.external_ref == external_ref,
                Conversation.status == "open",
            )
            .order_by(Conversation.created_at.desc())
            .limit(1)
        ).scalar()
    )


def start_or_extend(db: Session, conversation: Conversation, *, user_id: uuid.UUID) -> Conversation:
    """Claim the conversation for `user_id`, or push the expiry out again (sliding window). Commits — under the ReplyLock, so
    the claim can't land while an AI reply is between its last takeover check and being delivered."""
    with ReplyLock(conversation.id, timeout_seconds=CLAIM_LOCK_TIMEOUT_SECONDS):
        conversation.human_takeover_until = datetime.now(timezone.utc) + timedelta(seconds=settings.human_takeover_seconds)
        conversation.human_takeover_by = user_id
        db.commit()
    db.refresh(conversation)
    return conversation


def release(db: Session, conversation: Conversation) -> Conversation:
    """Hand the conversation back to the AI right now. Idempotent. Commits."""
    conversation.human_takeover_until = None
    conversation.human_takeover_by = None
    db.commit()
    db.refresh(conversation)
    return conversation
