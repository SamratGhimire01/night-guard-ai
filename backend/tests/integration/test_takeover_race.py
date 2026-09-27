"""Phase 52 — closing the last takeover race: a staff claim landing AFTER the AI's final takeover check but BEFORE its reply is
delivered. The two `is_active` checkpoints alone cannot close that (the claim commits in the gap, the AI then sends anyway →
a double reply). The per-conversation ReplyLock (takeover_service.ReplyLock) is held from the AI's final check through the
channel send, and every staff claim takes it too.

Deterministic, not timing luck: the race is FORCED into the exact window —
  * forward gap: the claim is fired from INSIDE the (slow) channel send, i.e. after the AI's last check → it must wait, and
    commit only after the reply was delivered (AI first, then the human — sequential, never simultaneous);
  * reverse gap: a claim is "in progress" (holds the lock, not yet committed) at the instant the AI reaches its final check
    → the AI must wait for it, see the takeover, and discard its draft.
Each test was mutation-checked against a no-op lock (see PHASE_STATUS.md): they fail without the lock.
"""

import json as jsonlib
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ConflictError
from app.db.database import SessionLocal, engine
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.main import app
from app.services import takeover_service
from app.services.conversation import handle_incoming_message

# fixtures/helpers shared with the takeover tests (pytest collects the fixtures by name from this module's namespace)
from tests.integration.test_human_takeover import (  # noqa: F401
    _auth, _count, _messages, _new_conversation, _set_takeover, _webhook, biz, llm, sends,
)


def _turn(business_id, conversation_id, content, deliver):
    with SessionLocal() as db:
        return handle_incoming_message(
            db, conversation_id=conversation_id, business_id=business_id, content=content, deliver=deliver
        )


def _claim(conversation_id, user_id):
    with SessionLocal() as db:
        takeover_service.start_or_extend(db, db.get(Conversation, conversation_id), user_id=user_id)


# ------------------------------------------------------------------------------ forward gap


def test_claim_landing_during_delivery_waits_and_commits_only_after_the_reply_is_out(biz, llm):
    cid = _new_conversation(biz["business_id"])
    events, state = [], {}

    def mark(label):
        events.append((time.monotonic(), label))

    def claim():
        _claim(cid, biz["staff_id"])
        mark("claim_committed")

    def slow_send(text):
        mark("send_start")
        thread = threading.Thread(target=claim)
        thread.start()  # the staff claim is fired NOW: after the AI's final check, before its reply is out
        time.sleep(1.0)  # a slow channel send (Meta latency) — the claim is racing it the whole time
        with SessionLocal() as other:
            state["claim_visible_mid_send"] = takeover_service.is_active(other, conversation_id=cid)
        mark("send_end")
        state["thread"] = thread
        return "sent wamid=race"

    result = _turn(biz["business_id"], cid, "what are your hours?", slow_send)
    state["thread"].join(15)

    assert [label for _, label in sorted(events)] == ["send_start", "send_end", "claim_committed"]
    assert state["claim_visible_mid_send"] is False  # the claim had NOT committed while the reply was still going out
    assert result["response"] and result["delivery_detail"] == "sent wamid=race"
    agent = [m for m in _messages(cid) if m.sender_type == MessageSenderType.AGENT]
    assert len(agent) == 1 and agent[0].delivery_status == "sent"  # exactly one AI reply, delivered once
    # and from now on the human owns it: the next customer message gets no AI reply and no send
    sent_after = []
    result2 = _turn(biz["business_id"], cid, "hello??", lambda t: sent_after.append(t) or "sent")
    assert result2["response"] is None and sent_after == []


# ------------------------------------------------------------------------------ reverse gap


def test_claim_in_progress_at_the_ai_final_check_wins_and_the_draft_is_discarded(biz, llm):
    cid = _new_conversation(biz["business_id"])
    state = {}

    def staff_claim_in_progress():
        """Runs INSIDE the LLM call: a staff member has taken the lock and is mid-claim (nothing committed yet)."""
        got = threading.Event()

        def staff():
            with takeover_service.ReplyLock(cid, timeout_seconds=10):
                got.set()
                time.sleep(1.0)  # the claim is being written...
                _set_takeover(cid, seconds_from_now=7200, by=biz["staff_id"])  # ...and committed, still holding the lock

        state["thread"] = threading.Thread(target=staff)
        state["thread"].start()
        assert got.wait(5)

    llm.during_call = staff_claim_in_progress
    delivered = []
    started = time.monotonic()
    result = _turn(biz["business_id"], cid, "need a human", lambda t: delivered.append(t) or "sent")
    state["thread"].join(10)

    assert time.monotonic() - started >= 1.0  # the AI really did wait for the in-progress claim
    assert delivered == []  # NOTHING was sent
    assert result["response"] is None and result["takeover"] is True
    assert _count(cid, MessageSenderType.AGENT) == 0
    assert [m.content for m in _messages(cid)] == ["need a human"]  # the customer's message is kept


# ------------------------------------------------------------------------------ end to end through a real webhook


def test_whatsapp_webhook_claim_racing_a_slow_send_never_produces_a_second_ai_send(biz, llm, sends, monkeypatch):
    from app.services.channels.whatsapp import WhatsAppChannelAdapter

    _webhook("whatsapp", "hi")  # first message creates the conversation (`sends` records instead of calling Meta)
    from tests.integration.test_human_takeover import _channel_conversation

    cid = _channel_conversation(biz["business_id"], "whatsapp")

    sent, claim_result = [], {}

    def slow_send(self, **kw):
        sent.append(("send_start", time.monotonic()))
        claimer = TestClient(app)  # its own client: a real staff HTTP claim, fired from inside the send

        def claim():
            resp = claimer.post(f"/api/v1/inbox/conversations/{cid}/takeover", headers=_auth(biz["staff_token"]))
            claim_result.update(status=resp.status_code, at=time.monotonic())

        claim_result["thread"] = threading.Thread(target=claim)
        claim_result["thread"].start()
        time.sleep(1.0)
        sent.append(("send_end", time.monotonic()))
        return "sent wamid=race"

    monkeypatch.setattr(WhatsAppChannelAdapter, "send_message", slow_send)
    _webhook("whatsapp", "what time do you open?")
    claim_result["thread"].join(15)

    assert [label for label, _ in sent] == ["send_start", "send_end"]  # the AI sent exactly once
    assert claim_result["status"] == 200 and claim_result["at"] >= sent[1][1]  # claim answered only after the send finished
    # the next customer message is now silent
    _webhook("whatsapp", "anyone there?")
    assert len(sent) == 2


# ------------------------------------------------------------------------------ the lock itself


def test_lock_serializes_and_a_waiting_staff_claim_times_out_with_a_retryable_409(biz):
    cid = _new_conversation(biz["business_id"])
    with takeover_service.ReplyLock(cid):
        started = time.monotonic()
        with pytest.raises(ConflictError):
            takeover_service.ReplyLock(cid, timeout_seconds=1).acquire()
        assert 0.9 <= time.monotonic() - started < 5
    with takeover_service.ReplyLock(cid, timeout_seconds=1):  # released -> free again
        pass


def test_lock_is_per_conversation(biz):
    a, b = _new_conversation(biz["business_id"]), _new_conversation(biz["business_id"])
    with takeover_service.ReplyLock(a):
        with takeover_service.ReplyLock(b, timeout_seconds=1):  # a different conversation is never blocked
            pass


def test_lock_is_released_when_the_turn_raises_and_no_connection_leaks(biz, llm):
    cid = _new_conversation(biz["business_id"])
    baseline = engine.pool.checkedout()

    class Boom(Exception):
        pass

    def explode():
        raise Boom()

    llm.during_call = explode
    with pytest.raises(Boom):
        _turn(biz["business_id"], cid, "hi", lambda t: "sent")
    with takeover_service.ReplyLock(cid, timeout_seconds=1):  # would raise ConflictError if the crashed turn leaked the lock
        pass
    llm.during_call = None
    for _ in range(5):
        _turn(biz["business_id"], cid, "hi again", lambda t: "sent")
    assert engine.pool.checkedout() == baseline  # neither the turns nor the lock connections leak


def test_staff_claim_mid_llm_is_never_blocked_by_the_ai_turn_even_with_a_pending_draft_state_change(biz, llm):
    """The AI turn must not hold a row lock on the conversation across its multi-second LLM call, or a claim would queue
    behind it and land AFTER the AI's check. Set up the case that dirties the conversation row first (a proposed-slots hint
    the turn clears)."""
    cid = _new_conversation(biz["business_id"])
    with SessionLocal() as db:
        db.get(Conversation, cid).booking_draft_proposed_slots = "2030-01-01T05:00:00+00:00,2030-01-01T06:00:00+00:00"
        db.commit()
    state = {}

    def claim_mid_call():
        thread = threading.Thread(target=lambda: (_claim(cid, biz["staff_id"]), state.setdefault("done", True)))
        thread.start()
        thread.join(5)  # blocked by a row lock => still alive after 5s
        state["finished_in_time"] = not thread.is_alive()

    llm.during_call = claim_mid_call
    delivered = []
    result = _turn(biz["business_id"], cid, "hello", lambda t: delivered.append(t) or "sent")
    assert state["finished_in_time"] is True
    assert result["response"] is None and delivered == []
