import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models.business import BusinessPlan


class PlanRead(BaseModel):
    """Requirement #5 — "what plan am I on, what does it include," and also
    what the admin view/list endpoints return. `features` is a real,
    honest description (app.core.entitlements.PLAN_FEATURES), not invented
    per-request."""

    business_id: uuid.UUID
    plan: BusinessPlan
    features: list[str]


class AdminPlanUpdate(BaseModel):
    """No validator needed to reject an explicit null: `plan` is required
    (not `| None`), so a client sending `{"plan": null}` already gets a 422
    from Pydantic itself — nothing to hand-write here."""

    plan: BusinessPlan


class AdminBusinessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    plan: BusinessPlan


class UpgradeRequestResult(BaseModel):
    requested_at: datetime
    team_notified: bool  # False when the support email could not be sent; the request is still recorded
