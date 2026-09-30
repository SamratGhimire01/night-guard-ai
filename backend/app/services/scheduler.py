import asyncio
import logging
import time

from app.core.config import settings
from app.db.database import SessionLocal
from app.services import companion, lead_service, no_show_service, reminder_service
from app.services.followups import followup_service

logger = logging.getLogger(__name__)


def _score_leads_sync() -> int:
    with SessionLocal() as db:
        return lead_service.score_stale_conversations(db)


async def _tick() -> None:
    """One real poll of the DB for due reminders, in its own fresh session
    (never reused across ticks — the same short-lived-session discipline as
    every request-scoped session elsewhere in this codebase) and its own
    try/except: a bug or a transient DB outage on one tick must never kill
    every future tick, the same resilience philosophy as
    dispatch_notification's outer wrapper (Phase 13) and Phase 30's proven
    `pool_pre_ping` recovery from a real Postgres outage."""
    try:
        with SessionLocal() as db:
            sent = reminder_service.run_due_reminders(db)
            if sent:
                logger.info("reminder scheduler tick: sent %d real reminder(s)", sent)
    except Exception:
        logger.exception("reminder scheduler tick failed")
    # its own try/except and fresh session: a failure in one job must never skip the other
    try:
        with SessionLocal() as db:
            flagged = no_show_service.flag_no_shows(db)
            if flagged:
                logger.info("no-show scheduler tick: flagged %d appointment(s) NO_SHOW", flagged)
    except Exception:
        logger.exception("no-show scheduler tick failed")
    # its own try/except and fresh session, same discipline as the two jobs above -- but ALSO off the event loop
    # (asyncio.to_thread), unlike them: real bug hit live-testing this exact change, this job's per-conversation LLM
    # call is a genuine multi-second blocking network call (not a quick DB query like reminders/no-shows), and this
    # coroutine runs on the SAME event loop that serves every live HTTP request (run_forever is a plain asyncio
    # background task, not a threadpooled `def` route handler) -- inline, a backlog of 20 conversations froze the
    # whole server for the length of 20 sequential LLM calls, exactly the "blocking work off the event loop"
    # discipline app/api/routes/knowledge.py's PDF/embedding calls already follow, just missed here.
    try:
        scored = await asyncio.to_thread(_score_leads_sync)
        if scored:
            logger.info("lead scheduler tick: scored %d conversation(s)", scored)
    except Exception:
        logger.exception("lead scheduler tick failed")
    try:
        followed_up = await _followups_if_due()
        if followed_up:
            logger.info("follow-up scheduler tick: sent %d follow-up(s)", followed_up)
    except Exception:
        logger.exception("follow-up scheduler tick failed")
    try:
        learned = await asyncio.to_thread(_companion_learn_sync)  # LLM call, off the event loop like lead scoring
        if learned:
            logger.info("companion scheduler tick: refreshed lessons for %d persona(s)", learned)
    except Exception:
        logger.exception("companion learning tick failed")


_last_followup_run = 0.0


async def _followups_if_due(now: float | None = None) -> int:
    """Follow-ups for every business that turned them on, at most every followup_run_interval_seconds. Sending email
    blocks (SMTP), so it runs off the event loop like the other network-bound jobs."""
    global _last_followup_run
    now = time.monotonic() if now is None else now
    if _last_followup_run and now - _last_followup_run < settings.followup_run_interval_seconds:
        return 0
    _last_followup_run = now
    return await asyncio.to_thread(_followups_sync)


def _followups_sync() -> int:
    with SessionLocal() as db:
        return followup_service.run_due_followups(db)


def _companion_learn_sync() -> int:
    with SessionLocal() as db:
        return companion.learn_if_due(db)


async def run_forever() -> None:
    """The real "runs on its own clock" loop — a plain asyncio background
    task (started from app/main.py's lifespan), not a new dependency. See
    PHASE_STATUS.md Phase 45 for the full APScheduler/Celery+Redis
    comparison and why this is the right-sized choice: a single fixed-
    interval periodic scan needs nothing more than sleep-then-run-again, and
    this codebase already has real precedent for a periodic-job function
    with nothing scheduling it (Phase 13's dispatch_queued_notifications,
    Phase 18's run_followups) — this is that missing piece, built as small
    as it can be. Exits cleanly on asyncio.CancelledError, which is exactly
    what app.main's lifespan sends on real shutdown (matching Phase 30's
    finding that uvicorn's default SIGTERM handling already waits for
    in-flight work correctly — no new shutdown-hook complexity needed here
    either)."""
    logger.info("reminder scheduler started, polling every %ds", settings.reminder_poll_interval_seconds)
    try:
        while True:
            await _tick()
            await asyncio.sleep(settings.reminder_poll_interval_seconds)
    except asyncio.CancelledError:
        logger.info("reminder scheduler stopped")
        raise
