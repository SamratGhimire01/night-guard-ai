import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class HumanHandoffRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    reason: str
    status: str
    resolved_at: datetime | None
    created_at: datetime


class HumanHandoffUpdate(BaseModel):
    """The only real transition today is marking a handoff resolved — there's
    no "reopen"/"unresolve" action, so this deliberately only accepts that one
    value rather than a free-text status field."""

    status: Literal["resolved"]
