from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.mixins import CreatedAtMixin, TenantMixin, UUIDPrimaryKeyMixin


class Integration(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, Base):
    """A configured third-party integration for a tenant (e.g. calendar sync)."""

    __tablename__ = "integrations"

    type: Mapped[str] = mapped_column(String(100), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
