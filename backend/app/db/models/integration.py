from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.mixins import CreatedAtMixin, TenantMixin, UUIDPrimaryKeyMixin


class Integration(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, Base):
    """A configured third-party integration for a tenant (e.g. calendar sync).

    One row per (business_id, type): POST /api/v1/integrations upserts on
    that pair rather than allowing a business to accumulate several rows for
    the same channel — see integration_service.upsert_integration.
    """

    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("business_id", "type", name="uq_integrations_business_type"),)

    type: Mapped[str] = mapped_column(String(100), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
