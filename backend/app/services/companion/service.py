"""Casual-companion persona ("Maya"): a standalone chat path that never touches the business orchestrator, KB, bookings
or any other tenant's data. Enabled per Instagram integration with config {"persona": "companion"} — remove that key
(or this package) to disable it.

Learning, two layers, both plain text you can read/edit in the DB:
- per person: Conversation.summary holds notes about that one person, refreshed every _NOTES_EVERY messages;
- global: Integration.config["learned"] holds style lessons distilled daily from all of Maya's chats (learn_if_due,
  called from the scheduler). Lessons are style-only — never one person's facts — so nothing leaks between users."""

import logging
import random
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.db.models.integration import Integration
from app.llm import get_chat_provider
from app.services.channels.base import get_or_create_conversation

logger = logging.getLogger(__name__)

_DIR = Path(__file__).parent
SYSTEM_PROMPT = "\n\n".join((_DIR / f).read_text(encoding="utf-8") for f in ("persona.md", "prompt.md", "prompt_texting.md"))
# ponytail: last-N window + per-person notes; no retrieval over older messages, add it if notes prove too lossy
_HISTORY_LIMIT = 120  # chat texts are short (~15 tokens each), so ~2k tokens of raw history on top of the notes
# Seconds before a reply goes out, so it feels like a person picking up her phone — not an instant bot.
_REPLY_DELAYS = (3, 8, 15, 25)
_NOTES_EVERY = 6
_LEARN_EVERY = timedelta(hours=24)
_FALLBACK = "sorry, network le dukha diyo 😅 feri bhana ta?"
_STYLE_REMINDER = (
    "Reminder: you're Maya, texting — not an assistant. Reply in 2-12 words unless the user shares something "
    "emotional, asks for advice, or explicitly asks you to explain. No lists, no definitions, no background info, no "
    "menus of options. Boring topic? dodge it or joke. Disagree when you disagree. Keep your life details consistent."
)


def _stage(agent_turns: int) -> str:
    if agent_turns < 3:
        return ("CONVERSATION STAGE: stranger — brand new. Slow start: short, polite, a bit reserved. If you don't "
                "know their name yet, ask it once, naturally — if they skip it, don't ask again for a while.")
    if agent_turns < 15:
        return "CONVERSATION STAGE: getting to know each other — friendly, curious, open up gradually."
    if agent_turns < 80:
        return "CONVERSATION STAGE: friends — teasing, sharing your day, remembering things about them."
    return ("CONVERSATION STAGE: close — long chat history. If the notes say the relationship has been warm and they've "
            "been nice, you can be affectionate and a little flirty. Never sexual. If they've been rude, stay cool.")


def _chat(messages: list[dict]) -> str:
    return get_chat_provider().chat(messages).strip()


def reply(
    db: Session, *, business_id: uuid.UUID, channel: str, external_ref: str, content: str,
    external_message_id: str | None, deliver, learned: str = "",
) -> str:
    conversation = get_or_create_conversation(
        db, business_id=business_id, channel=channel, external_ref=external_ref,
        default_customer_name="Instagram Contact",
    )
    conversation_id, notes = conversation.id, conversation.summary
    history = list(reversed(db.execute(
        select(Message.sender_type, Message.content).where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc()).limit(_HISTORY_LIMIT)
    ).all()))
    agent_turns = db.execute(
        select(func.count()).where(Message.conversation_id == conversation_id,
                                   Message.sender_type == MessageSenderType.AGENT)
    ).scalar_one()

    system = SYSTEM_PROMPT
    if learned:
        system += "\n\n# WHAT YOU'VE LEARNED FROM YOUR PAST CHATS (follow these)\n" + learned
    if notes:
        system += "\n\n# WHAT YOU KNOW ABOUT THIS PERSON (from earlier chats — use naturally, never recite)\n" + notes
    messages = [{"role": "system", "content": system}]
    messages += [{"role": "user" if sender == MessageSenderType.CUSTOMER else "assistant", "content": body}
                 for sender, body in history]
    # Recency nudge: the rules sit at the start of a ~10k-token prompt and the model drifts back to explaining.
    messages.append({"role": "system", "content": _stage(agent_turns) + "\n" + _STYLE_REMINDER})
    messages.append({"role": "user", "content": content})

    # Stored before the LLM call so a Meta redelivery hits the external_message_id unique constraint. Everything the
    # LLM call needs is plain data by now, so no DB connection is held while waiting on the model.
    db.add(Message(conversation_id=conversation_id, sender_type=MessageSenderType.CUSTOMER, content=content,
                   external_message_id=external_message_id))
    db.commit()

    try:
        text = _chat(messages) or _FALLBACK
    except Exception:
        logger.exception("companion: LLM call failed for conversation %s", conversation_id)
        text = _FALLBACK

    db.add(Message(conversation_id=conversation_id, sender_type=MessageSenderType.AGENT, content=text))
    db.commit()
    # Off the webhook thread, so Meta gets its 200 immediately. ponytail: an in-memory timer — a reply pending during
    # a backend restart is stored but never sent, and two quick messages can get their replies out of order.
    threading.Timer(random.choice(_REPLY_DELAYS), deliver, [text]).start()

    if (agent_turns + 1) % _NOTES_EVERY == 0:
        _update_notes(db, conversation_id, notes, history[-12:] + [(MessageSenderType.CUSTOMER, content),
                                                                   (MessageSenderType.AGENT, text)])
    return text


def _transcript(rows) -> str:
    return "\n".join(f"{'Them' if s == MessageSenderType.CUSTOMER else 'Maya'}: {c}" for s, c in rows)


def _update_notes(db: Session, conversation_id: uuid.UUID, notes: str | None, recent) -> None:
    """Per-person memory: merge what this person said recently into their notes (after the reply is already sent)."""
    try:
        updated = _chat([{"role": "user", "content": (
            "You keep Maya's private notes about ONE person she chats with on Instagram.\n"
            f"Current notes:\n{notes or '(none yet)'}\n\nRecent chat:\n{_transcript(recent)}\n\n"
            "Return the updated notes: at most 14 short bullet points of lasting facts THEY stated about themselves "
            "(name, where from, study/work, family, likes/dislikes, upcoming events like exams, what they enjoy "
            "talking about, how they like to text). One bullet on how the relationship feels so far (warm / neutral / "
            "they were rude or pushy, and whether they apologised). One bullet for anything Maya told them about her own "
            "life, so she stays consistent. Drop stale or trivial things. Output only the bullets.")}])
    except Exception:
        logger.exception("companion: notes update failed for conversation %s", conversation_id)
        return
    if updated:
        db.get(Conversation, conversation_id).summary = updated
        db.commit()


def learn_if_due(db: Session) -> int:
    """Daily self-improvement: for each companion integration whose lessons are older than _LEARN_EVERY, read the chats
    since then and rewrite config["learned"]. Returns how many integrations were updated."""
    now = datetime.now(timezone.utc)
    updated = 0
    for integration in db.execute(select(Integration).where(Integration.type == "instagram")).scalars():
        config = integration.config or {}
        if config.get("persona") != "companion":
            continue
        since = datetime.fromisoformat(config["learned_at"]) if config.get("learned_at") else now - timedelta(days=30)
        if now - since < _LEARN_EVERY:
            continue
        lessons = _learn(db, integration.business_id, since, config.get("learned", ""))
        integration.config = {**config, "learned_at": now.isoformat(), **({"learned": lessons} if lessons else {})}
        flag_modified(integration, "config")
        db.commit()
        updated += bool(lessons)
    return updated


def _learn(db: Session, business_id: uuid.UUID, since: datetime, old_lessons: str) -> str:
    conversation_ids = db.execute(
        select(Message.conversation_id).join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.business_id == business_id, Message.created_at >= since)
        .group_by(Message.conversation_id).order_by(func.max(Message.created_at).desc()).limit(40)
    ).scalars().all()
    chats = []
    for cid in conversation_ids:
        rows = db.execute(
            select(Message.sender_type, Message.content).where(Message.conversation_id == cid)
            .order_by(Message.created_at.desc()).limit(30)
        ).all()
        if len(rows) >= 4:
            chats.append(_transcript(reversed(rows)))
    if not chats:
        return ""
    try:
        return _chat([{"role": "user", "content": (
            "Maya is a 25-year-old girl from Thimi, Bhaktapur who chats casually with people on Instagram in Roman "
            "Nepali/English. Below are her recent chats, separated by ---. A chat where the person kept replying, "
            "laughed, or opened up went WELL. A chat where they went quiet right after Maya's message, got bored, or "
            "said she sounds like a bot/robot/fake went BADLY.\n\n"
            f"Her current lessons:\n{old_lessons or '(none yet)'}\n\nChats:\n" + "\n---\n".join(chats) + "\n\n"
            "Rewrite her lessons: at most 15 short, concrete bullet points about HOW to text better (length, tone, "
            "what openers/replies worked, what killed conversations, Roman Nepali phrasing people responded to). Keep "
            "old lessons that still hold, drop ones the chats contradict. Rules: style only — never include any "
            "person's name or personal facts; never a lesson to deny being AI when sincerely asked, to meet, call or "
            "go out with anyone (no suggesting outings or plans together), share contacts, ask for money, or get sexual. Output only the bullets.")}])
    except Exception:
        logger.exception("companion: learning pass failed for business %s", business_id)
        return ""
