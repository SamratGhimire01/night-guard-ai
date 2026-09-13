import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.db.models.payment import PaymentStatus


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    appointment_id: uuid.UUID
    provider: str
    amount: Decimal
    currency: str
    status: PaymentStatus
    gateway_reference: str | None
    payment_url: str
