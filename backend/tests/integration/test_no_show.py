# ruff: noqa: F811  (fixtures imported from the Phase 45 suite are re-declared as test arguments — the pytest idiom)
"""Phase 48 — real no-show detection: a CONFIRMED appointment whose whole slot has passed without a check-in or a
cancel is flagged NO_SHOW by one atomic `UPDATE ... WHERE status = 'CONFIRMED'`. Real DB throughout; the real asyncio
loop is proven live against the running server (PHASE_STATUS.md), the callable and the scheduler tick here.
"""

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.exceptions import ConflictError, UnprocessableEntityError
from app.db.database import SessionLocal
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.conversation import Conversation, Message
from app.db.models.notification import Notification
from app.db.models.payment import Payment, PaymentStatus
from app.memory.appointment_context import get_appointment_context
from app.services import booking_service, checkin_service, no_show_service, scheduler
from tests.integration.test_reminders import _make_appointment, business_ready, fake_email_provider  # noqa: F401

NOW = datetime.now(timezone.utc)


def _appt(db, ctx, *, minutes_from_now: int, status=AppointmentStatus.CONFIRMED) -> Appointment:
    """A 30-minute appointment starting `minutes_from_now` (negative = in the past)."""
    return _make_appointment(
        db,
        business_id=ctx["business_id"],
        customer_id=ctx["customer_id"],
        service_id=ctx["service_id"],
        scheduled_at=NOW + timedelta(minutes=minutes_from_now),
        created_at=NOW - timedelta(days=3),
        status=status,
    )


def _status(appointment_id) -> AppointmentStatus:
    with SessionLocal() as db:
        return db.get(Appointment, appointment_id).status


def _flag(ctx) -> int:
    with SessionLocal() as db:
        return no_show_service.flag_no_shows(db, business_id=ctx["business_id"])


def test_passed_confirmed_appointment_is_flagged_no_show(business_ready):
    with SessionLocal() as db:
        appt = _appt(db, business_ready, minutes_from_now=-90)  # ended 60 min ago
        appt_id = appt.id
    assert _flag(business_ready) == 1
    assert _status(appt_id) == AppointmentStatus.NO_SHOW
    assert _flag(business_ready) == 0, "already flagged: a second scan finds nothing"


def test_only_a_fully_passed_slot_counts_in_progress_and_future_are_untouched(business_ready):
    with SessionLocal() as db:
        in_progress = _appt(db, business_ready, minutes_from_now=-10).id  # started 10 min ago, 20 min left
        future = _appt(db, business_ready, minutes_from_now=120).id
        just_ended = _appt(db, business_ready, minutes_from_now=-45).id  # ended 15 min ago
    assert _flag(business_ready) == 1
    assert _status(in_progress) == AppointmentStatus.CONFIRMED
    assert _status(future) == AppointmentStatus.CONFIRMED
    assert _status(just_ended) == AppointmentStatus.NO_SHOW


def test_checked_in_appointment_is_never_flagged(business_ready):
    with SessionLocal() as db:
        appt = _appt(db, business_ready, minutes_from_now=-90)
        checkin_service.check_in_appointment(db, business_id=business_ready["business_id"], token=appt.checkin_token)
        appt_id = appt.id
    assert _flag(business_ready) == 0
    assert _status(appt_id) == AppointmentStatus.ARRIVED


def test_cancelled_appointment_is_never_flagged(business_ready, fake_email_provider):
    with SessionLocal() as db:
        appt = _appt(db, business_ready, minutes_from_now=-90)
        booking_service.cancel_appointment(db, business_id=business_ready["business_id"], appointment_id=appt.id)
        appt_id = appt.id
    assert _flag(business_ready) == 0
    assert _status(appt_id) == AppointmentStatus.CANCELLED


def test_arrived_completed_and_pending_rows_are_never_flagged(business_ready):
    with SessionLocal() as db:
        ids = [
            _appt(db, business_ready, minutes_from_now=-90 - 40 * i, status=s).id
            for i, s in enumerate((AppointmentStatus.ARRIVED, AppointmentStatus.COMPLETED, AppointmentStatus.PENDING))
        ]
    assert _flag(business_ready) == 0
    assert [_status(i) for i in ids] == [AppointmentStatus.ARRIVED, AppointmentStatus.COMPLETED, AppointmentStatus.PENDING]


def test_scan_never_relabels_old_history_beyond_the_lookback(business_ready):
    with SessionLocal() as db:
        old = _appt(db, business_ready, minutes_from_now=-60 * 24 * 3).id  # ended ~3 days ago (> 24 h lookback)
    assert _flag(business_ready) == 0
    assert _status(old) == AppointmentStatus.CONFIRMED


def test_flagging_a_no_show_never_touches_its_deposit_payment(business_ready):
    with SessionLocal() as db:
        appt = _appt(db, business_ready, minutes_from_now=-90)
        payment = Payment(
            business_id=business_ready["business_id"], appointment_id=appt.id, provider="esewa",
            amount=Decimal("12.00"), currency="NPR", status=PaymentStatus.PENDING, payment_url="https://x.example/p",
        )
        db.add(payment)
        db.commit()
        appt_id, payment_id = appt.id, payment.id
    assert _flag(business_ready) == 1
    with SessionLocal() as db:
        p = db.get(Payment, payment_id)
        assert (p.status, p.amount, p.appointment_id, p.completion_notified_at) == (
            PaymentStatus.PENDING, Decimal("12.00"), appt_id, None
        )


def test_no_show_appears_as_a_past_appointment_in_the_customers_chat_context(business_ready):
    with SessionLocal() as db:
        _appt(db, business_ready, minutes_from_now=-90)
    _flag(business_ready)
    with SessionLocal() as db:
        ctx = get_appointment_context(
            db, business_id=business_ready["business_id"], customer_id=business_ready["customer_id"]
        )
    assert [a["status"] for a in ctx["recent_past"]] == ["no_show"]
    assert ctx["active"] == []


def test_the_scheduler_tick_runs_the_no_show_scan():
    """The real loop body (`scheduler._tick`) — what the timer calls every poll — flags it. Uses its own rows."""
    with SessionLocal() as db:
        from app.db.models.business import Business
        from app.db.models.customer import Customer
        from app.db.models.service import Service

        business = Business(name="NoShow Tick Biz", timezone="UTC")
        db.add(business)
        db.flush()
        customer = Customer(business_id=business.id, name="C")
        service = Service(business_id=business.id, name="S", price=Decimal("1.00"), duration_minutes=30)
        db.add_all([customer, service])
        db.flush()
        appt = _make_appointment(
            db, business_id=business.id, customer_id=customer.id, service_id=service.id,
            scheduled_at=NOW - timedelta(minutes=90), created_at=NOW - timedelta(days=1),
        )
        appt_id, business_id = appt.id, business.id
    try:
        asyncio.run(scheduler._tick())
        assert _status(appt_id) == AppointmentStatus.NO_SHOW
    finally:
        with SessionLocal() as db:
            db.delete(db.get(Business, business_id))
            db.commit()


# --- real concurrency: same 8-thread Barrier technique as Phase 45/46 ---------------------------------------------


def _race(workers: list) -> list:
    barrier = threading.Barrier(len(workers))
    results = [None] * len(workers)

    def run(i):
        with SessionLocal() as db:
            barrier.wait()
            try:
                results[i] = workers[i](db)
            except (ConflictError, UnprocessableEntityError) as exc:
                results[i] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(workers))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_eight_concurrent_scans_flag_an_appointment_exactly_once(business_ready):
    with SessionLocal() as db:
        appt_id = _appt(db, business_ready, minutes_from_now=-90).id
    bid = business_ready["business_id"]
    results = _race([lambda db: no_show_service.flag_no_shows(db, business_id=bid)] * 8)
    assert sorted(results) == [0] * 7 + [1], f"exactly one winner expected, got {results}"
    assert _status(appt_id) == AppointmentStatus.NO_SHOW


def test_check_in_racing_the_scan_never_ends_as_both(business_ready):
    """4 scans and 4 check-ins released at the same instant, repeated on fresh appointments: every appointment ends
    exactly ARRIVED (check-in won: the scan flagged nothing) or NO_SHOW (scan won: every check-in was refused) — never
    a mix, never both flags."""
    bid = business_ready["business_id"]
    outcomes = set()
    for i in range(6):
        with SessionLocal() as db:
            appt = _appt(db, business_ready, minutes_from_now=-90 - 40 * i)
            appt_id, token = appt.id, appt.checkin_token
        results = _race(
            [lambda db: no_show_service.flag_no_shows(db, business_id=bid)] * 4
            + [lambda db: checkin_service.check_in_appointment(db, business_id=bid, token=token)] * 4
        )
        flagged = sum(r for r in results[:4] if isinstance(r, int))
        checked_in = [r for r in results[4:] if isinstance(r, Appointment)]
        final = _status(appt_id)
        if final == AppointmentStatus.ARRIVED:
            assert flagged == 0 and len(checked_in) == 1
        else:
            assert final == AppointmentStatus.NO_SHOW and flagged == 1 and checked_in == []
        outcomes.add(final)
    assert outcomes <= {AppointmentStatus.ARRIVED, AppointmentStatus.NO_SHOW}


def test_cancel_racing_the_scan_a_successful_cancel_is_never_left_no_show(business_ready, fake_email_provider):
    bid = business_ready["business_id"]
    for i in range(6):
        with SessionLocal() as db:
            appt_id = _appt(db, business_ready, minutes_from_now=-90 - 40 * i).id
        results = _race(
            [lambda db: no_show_service.flag_no_shows(db, business_id=bid)] * 4
            + [lambda db: booking_service.cancel_appointment(db, business_id=bid, appointment_id=appt_id)]
        )
        cancel_result = results[4]
        final = _status(appt_id)
        if isinstance(cancel_result, Appointment):
            assert final == AppointmentStatus.CANCELLED, "the customer cancelled successfully: it must stay cancelled"
        else:
            assert final == AppointmentStatus.NO_SHOW  # the scan won and the cancel was refused as too late


# --- Phase 49: a completed deposit on a no-show is recorded as forfeited (never refunded, never announced) ------------


def _payment(db, ctx, appt, status=PaymentStatus.COMPLETED, amount="12.00", conversation_id=None) -> Payment:
    payment = Payment(
        business_id=ctx["business_id"], appointment_id=appt.id, provider="esewa", amount=Decimal(amount),
        currency="NPR", status=status, payment_url="https://x.example/p", conversation_id=conversation_id,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def _pay(payment_id) -> Payment:
    with SessionLocal() as db:
        return db.get(Payment, payment_id)


def test_completed_deposit_on_a_no_show_is_marked_forfeited_and_nothing_else_changes(business_ready):
    with SessionLocal() as db:
        appt = _appt(db, business_ready, minutes_from_now=-90)
        payment = _payment(db, business_ready, appt)
        appt_id, payment_id = appt.id, payment.id
    assert _flag(business_ready) == 1
    p = _pay(payment_id)
    assert p.forfeited_due_to_no_show_at is not None
    assert (p.status, p.amount, p.currency, p.gateway_reference) == (PaymentStatus.COMPLETED, Decimal("12.00"), "NPR", None)
    assert _status(appt_id) == AppointmentStatus.NO_SHOW
    stamp = p.forfeited_due_to_no_show_at
    assert _flag(business_ready) == 0
    assert _pay(payment_id).forfeited_due_to_no_show_at == stamp, "set once, never rewritten"


def test_only_completed_deposits_are_forfeited_pending_and_failed_ones_are_left_alone(business_ready):
    with SessionLocal() as db:
        ids = [
            _payment(db, business_ready, _appt(db, business_ready, minutes_from_now=-90 - 40 * i), status=st).id
            for i, st in enumerate((PaymentStatus.PENDING, PaymentStatus.FAILED))
        ]
    assert _flag(business_ready) == 2
    assert [_pay(i).forfeited_due_to_no_show_at for i in ids] == [None, None]
    assert [_pay(i).status for i in ids] == [PaymentStatus.PENDING, PaymentStatus.FAILED]


def test_deposit_of_an_appointment_that_was_checked_in_or_cancelled_is_never_forfeited(business_ready, fake_email_provider):
    with SessionLocal() as db:
        arrived = _appt(db, business_ready, minutes_from_now=-90)
        cancelled = _appt(db, business_ready, minutes_from_now=-130)
        pay_arrived, pay_cancelled = _payment(db, business_ready, arrived).id, _payment(db, business_ready, cancelled).id
        checkin_service.check_in_appointment(db, business_id=business_ready["business_id"], token=arrived.checkin_token)
        booking_service.cancel_appointment(db, business_id=business_ready["business_id"], appointment_id=cancelled.id)
    assert _flag(business_ready) == 0
    assert _pay(pay_arrived).forfeited_due_to_no_show_at is None and _pay(pay_cancelled).forfeited_due_to_no_show_at is None


def test_flipping_the_status_and_recording_the_forfeiture_commit_together_or_not_at_all(business_ready, monkeypatch):
    with SessionLocal() as db:
        appt = _appt(db, business_ready, minutes_from_now=-90)
        payment = _payment(db, business_ready, appt)
        appt_id, payment_id = appt.id, payment.id
    with SessionLocal() as db:
        real_execute, calls = db.execute, []

        def failing_second_statement(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:  # the forfeiture UPDATE, after the appointment UPDATE already ran in this transaction
                raise RuntimeError("simulated failure between the two statements")
            return real_execute(*args, **kwargs)

        monkeypatch.setattr(db, "execute", failing_second_statement)
        with pytest.raises(RuntimeError):
            no_show_service.flag_no_shows(db, business_id=business_ready["business_id"])
        db.rollback()
    assert _status(appt_id) == AppointmentStatus.CONFIRMED, "the NO_SHOW flip must not survive without its forfeiture"
    assert _pay(payment_id).forfeited_due_to_no_show_at is None
    assert _flag(business_ready) == 1 and _pay(payment_id).forfeited_due_to_no_show_at is not None  # and a retry works


def test_eight_concurrent_scans_forfeit_a_deposit_exactly_once(business_ready):
    with SessionLocal() as db:
        appt = _appt(db, business_ready, minutes_from_now=-90)
        payment_id = _payment(db, business_ready, appt).id
    bid = business_ready["business_id"]
    results = _race([lambda db: no_show_service.flag_no_shows(db, business_id=bid)] * 8)
    assert sorted(results) == [0] * 7 + [1]
    with SessionLocal() as db:
        assert db.query(Payment).filter(Payment.id == payment_id, Payment.forfeited_due_to_no_show_at.is_not(None)).count() == 1


def test_no_message_of_any_kind_goes_to_the_customer_when_a_deposit_is_forfeited(
    business_ready, fake_email_provider, monkeypatch
):
    """The chat conversation the deposit was paid in exists and is linked to the payment (exactly what
    notify_payment_completed uses to message the customer) — flagging must not touch it, email, or SMS."""
    from app.services.channels import proactive
    from app.services.notifications import dispatch_service

    def forbidden(*args, **kwargs):
        raise AssertionError("a no-show/forfeiture must never message the customer")

    monkeypatch.setattr(proactive, "send_to_conversation", forbidden)
    monkeypatch.setattr(dispatch_service, "dispatch_notification", forbidden)
    monkeypatch.setattr(dispatch_service, "_dispatch", forbidden)
    with SessionLocal() as db:
        conversation = Conversation(
            business_id=business_ready["business_id"], customer_id=business_ready["customer_id"], channel="website", status="open"
        )
        db.add(conversation)
        db.commit()
        appt = _appt(db, business_ready, minutes_from_now=-90)
        payment = _payment(db, business_ready, appt, conversation_id=conversation.id)
        appt_id, payment_id, conv_id = appt.id, payment.id, conversation.id

    def counts():
        with SessionLocal() as db:
            return (
                db.query(Notification).filter(Notification.appointment_id == appt_id).count(),
                db.query(Message).filter(Message.conversation_id == conv_id).count(),
            )

    before = counts()
    assert _flag(business_ready) == 1
    assert _pay(payment_id).forfeited_due_to_no_show_at is not None
    assert counts() == before == (0, 0), "no Notification row and no chat Message was created"
    assert fake_email_provider.calls == 0, "and no email left the building"


def test_settings_refuse_a_lookback_long_enough_to_backfill_old_history(monkeypatch):
    from pydantic import ValidationError

    from app.core.config import Settings

    assert Settings().no_show_lookback_hours == 24
    for hours in (73, 720, 0):
        with pytest.raises(ValidationError):
            Settings(no_show_lookback_hours=hours)


def test_a_paid_deposit_on_old_pre_feature_history_is_never_forfeited(business_ready):
    with SessionLocal() as db:
        old = _appt(db, business_ready, minutes_from_now=-60 * 24 * 5)  # ended ~5 days ago
        payment_id = _payment(db, business_ready, old).id
        old_id = old.id
    assert _flag(business_ready) == 0
    assert _status(old_id) == AppointmentStatus.CONFIRMED and _pay(payment_id).forfeited_due_to_no_show_at is None


def test_a_deposit_that_completes_only_after_the_flag_is_not_retroactively_forfeited(business_ready):
    with SessionLocal() as db:
        appt = _appt(db, business_ready, minutes_from_now=-90)
        payment = _payment(db, business_ready, appt, status=PaymentStatus.PENDING)
        payment_id = payment.id
    assert _flag(business_ready) == 1
    with SessionLocal() as db:
        db.get(Payment, payment_id).status = PaymentStatus.COMPLETED  # the customer paid the still-live link late
        db.commit()
    assert _flag(business_ready) == 0
    assert _pay(payment_id).forfeited_due_to_no_show_at is None
