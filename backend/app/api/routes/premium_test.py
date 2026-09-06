from fastapi import APIRouter, Depends

from app.api.dependencies import require_plan
from app.db.models.business import BusinessPlan, BusinessUser

router = APIRouter()

# Phase 34 — a deliberately synthetic route. No real premium feature exists
# in this codebase yet (Google Calendar/payments/voice/yearly reports are all
# future phases), and the ticket explicitly asked to "simulate one with a
# test route ... if no real premium feature exists yet" to prove
# require_plan actually blocks/allows at the HTTP layer. Delete this file
# once a real premium-gated route exists to demonstrate the mechanism
# instead — see PHASE_STATUS.md Phase 34.


@router.get("/premium-test/ping")
def premium_test_ping(
    current_user: BusinessUser = Depends(require_plan(BusinessPlan.PREMIUM)),
) -> dict:
    return {"message": "Premium feature executed."}
