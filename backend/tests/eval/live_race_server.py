"""Live-proof helper (Phase 52): the REAL app in a second uvicorn process on :8001 whose ONLY difference is that the outbound
WhatsApp call takes SEND_DELAY extra seconds — a slow Meta response, so the "after the AI's final check, before its reply is
out" window is wide enough to fire a real HTTP staff claim into. Everything else (orchestrator, lock, DB, Azure LLM) is real.

    docker exec -d -e PYTHONPATH=/app night_guard_ai-backend-1 python tests/eval/live_race_server.py
"""
import logging
import time

import uvicorn

from app.services.channels.whatsapp import WhatsAppChannelAdapter

SEND_DELAY = 5.0
_real_send = WhatsAppChannelAdapter.send_message
log = logging.getLogger("live_race")


def _slow_send(self, **kw):
    log.warning("SLOW-SEND START (holding for %.0fs like a slow Meta response)", SEND_DELAY)
    time.sleep(SEND_DELAY)
    detail = _real_send(self, **kw)  # still the real call to Meta (fake recipient -> HTTP 400)
    log.warning("SLOW-SEND END: %s", detail)
    return detail


WhatsAppChannelAdapter.send_message = _slow_send

from app.main import app  # noqa: E402  (imported after the patch on purpose)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")
