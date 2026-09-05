from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_role
from app.db.models.audit_log import AuditLog
from app.db.models.business import BusinessUser
from app.db.models.handoff import HumanHandoff
from app.db.models.notification import Notification

router = APIRouter()

# Real, expected outcomes for a booking attempt (Phase 10/12's own validation/
# race-condition vocabulary) — a customer losing a real race for a slot, or a
# plain not-found/unavailable, is normal operation, not a system failure. Any
# result outside this known set would be genuinely unexpected (in practice
# this never happens today: a real bug bypasses booking_service's own
# try/except entirely and surfaces as a raw 500, tracked separately — see the
# docstring below).
_EXPECTED_BOOKING_RESULTS = {"success", "not_found", "unavailable", "conflict_race_lost"}

# Real reason strings handoff_service._handoff_reason produces (two of the four
# embed dynamic data — similarity score / intent — so bucketing by a stable
# substring, not exact match, is what keeps this breakdown from fragmenting
# into one bucket per unique score).
_HANDOFF_REASON_BUCKETS = [
    ("provider_outage", "AI provider was unreachable"),
    ("complaint", "classified as a complaint"),
    ("explicit_request", "explicitly asked to speak with a human"),
    ("no_knowledge_match", "No sufficiently relevant knowledge found"),
]


def _bucket_handoff_reason(reason: str) -> str:
    for bucket, needle in _HANDOFF_REASON_BUCKETS:
        if needle in reason:
            return bucket
    return "other"


@router.get("/internal/metrics")
def get_metrics(
    hours: int = Query(default=24, ge=1, le=24 * 30),
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> dict:
    """Real, tenant-scoped operational health snapshot over the last `hours`
    hours (default 24) — owner/admin only, the same bar as reports/training
    room (operational detail, not a customer-facing read). Real DB
    aggregation, no new metrics-collection infrastructure: booking outcomes
    reuse Phase 3's existing general-purpose AuditLog table (a race-lost
    booking never writes an Appointment row at all, so without this there'd
    be no trace one ever happened — see booking_service._record_booking_metric);
    notifications and handoffs reuse their own existing status/reason columns.

    `booking.conflict_race_lost` is reported separately from
    `booking.genuine_failure_count`/`genuine_failure_rate` on purpose: a
    customer losing a real race for a slot (Phase 10's EXCLUDE constraint
    doing its job) is expected, healthy operation, never counted as a system
    failure.

    A genuine system error (an unhandled exception / raw 500) is NOT in this
    breakdown at all — it bypasses booking_service's own try/except entirely,
    so it's tracked separately via the existing structured log line
    (`logger=app.core.exceptions`, `message="unhandled exception on ..."`),
    real, queryable JSON, not duplicated here.

    LLM call latency/outcome and per-channel webhook processing counts are
    likewise real structured JSON log lines (`app.llm.azure_openai`,
    `app.api.routes.webhooks`) rather than DB rows — deliberately: both are
    high-frequency, ephemeral operational events with no natural persisted
    home in this schema, and duplicating them into a new DB table here would
    be exactly the over-building this phase's own brief warns against."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    business_id = current_user.business_id

    booking_rows = db.execute(
        select(AuditLog.result, func.count())
        .where(
            AuditLog.business_id == business_id,
            AuditLog.action == "booking_attempt",
            AuditLog.created_at >= since,
        )
        .group_by(AuditLog.result)
    ).all()
    booking_counts = {result: count for result, count in booking_rows}
    booking_total = sum(booking_counts.values())
    genuine_failures = sum(count for result, count in booking_counts.items() if result not in _EXPECTED_BOOKING_RESULTS)

    notification_rows = db.execute(
        select(Notification.status, func.count())
        .where(Notification.business_id == business_id, Notification.created_at >= since)
        .group_by(Notification.status)
    ).all()
    notification_counts = {status.value: count for status, count in notification_rows}
    notification_total = sum(notification_counts.values())

    handoff_reasons = (
        db.execute(
            select(HumanHandoff.reason).where(
                HumanHandoff.business_id == business_id, HumanHandoff.created_at >= since
            )
        )
        .scalars()
        .all()
    )
    handoff_buckets: dict[str, int] = {}
    for reason in handoff_reasons:
        bucket = _bucket_handoff_reason(reason)
        handoff_buckets[bucket] = handoff_buckets.get(bucket, 0) + 1

    return {
        "window_hours": hours,
        "booking": {
            "total_attempts": booking_total,
            "by_result": booking_counts,
            "conflict_race_lost": booking_counts.get("conflict_race_lost", 0),
            "genuine_failure_count": genuine_failures,
            "genuine_failure_rate": round(genuine_failures / booking_total, 4) if booking_total else 0.0,
        },
        "notifications": {
            "total": notification_total,
            "by_status": notification_counts,
            "failure_rate": round(notification_counts.get("failed", 0) / notification_total, 4)
            if notification_total
            else 0.0,
        },
        "handoffs": {
            "total": len(handoff_reasons),
            "by_reason": handoff_buckets,
        },
    }
