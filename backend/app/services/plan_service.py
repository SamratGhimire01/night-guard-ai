import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.audit_log import AuditLog
from app.db.models.business import Business, BusinessPlan


def get_business(db: Session, *, business_id: uuid.UUID) -> Business | None:
    return db.get(Business, business_id)


def list_businesses(db: Session) -> list[Business]:
    """Small, unpaginated on purpose — same "naturally small in practice"
    reasoning Phase 28 (F3) already applied to services/staff/knowledge/
    handoffs: this is a platform-operator tool for a pre-self-serve sales
    process, not a customer-facing list. Revisit if the real business count
    ever grows enough to matter (see PHASE_STATUS.md Phase 34)."""
    return list(db.execute(select(Business).order_by(Business.created_at)).scalars())


def change_plan(db: Session, *, business_id: uuid.UUID, new_plan: BusinessPlan, actor: str) -> Business | None:
    """The ONLY writer of Business.plan (see the column's own docstring) —
    reached only through the superadmin-gated admin routes. Real audit
    logging (Phase 34 requirement #3), reusing the existing general-purpose
    AuditLog model exactly like booking_service's `_record_booking_metric`/
    `reschedule_appointment` already do for their own state transitions:
    `actor` is the real acting superadmin's email (never "system" — this is
    always a real person's deliberate action), and `result` encodes the real
    from/to transition, the same "from=X to=Y" free-text convention
    `reschedule_appointment` already established for `moved_from=...`.

    Returns None if the business doesn't exist (caller turns that into a 404
    — same pattern as every other tenant-scoped lookup in this codebase)."""
    business = db.get(Business, business_id)
    if business is None:
        return None

    old_plan = business.plan
    business.plan = new_plan
    db.add(
        AuditLog(
            business_id=business_id,
            actor=actor,
            action="plan_changed",
            resource_type="business",
            resource_id=str(business_id),
            result=f"from={old_plan.value} to={new_plan.value}",
        )
    )
    db.commit()
    db.refresh(business)
    return business
