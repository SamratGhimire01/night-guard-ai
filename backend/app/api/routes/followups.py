from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_role
from app.db.models.business import BusinessUser
from app.services.followups import followup_service

router = APIRouter()


@router.post("/followups/run")
def run_followups(
    inactivity_hours: int = Query(default=followup_service.DEFAULT_INACTIVITY_HOURS, ge=1, le=24 * 30),
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> dict:
    """Real, callable-not-scheduled trigger — no cron/scheduler infrastructure
    exists yet in this codebase (see PHASE_STATUS.md); this runs the real
    detection + send right now, tenant-scoped, owner/admin only (follow-ups
    reach real customers, same bar as every other outbound-message trigger)."""
    results = followup_service.run_followups(
        db, business_id=current_user.business_id, inactivity_hours=inactivity_hours
    )
    return {"processed": len(results), "results": results}
