import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKeyConstraint, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.mixins import CreatedAtMixin, TenantMixin, UUIDPrimaryKeyMixin


class Service(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, Base):
    """A bookable service a tenant offers (e.g. a dental cleaning)."""

    __tablename__ = "services"
    __table_args__ = (
        # Lets Appointment enforce, at the database level, that a service_id it references
        # belongs to the same business_id.
        UniqueConstraint("id", "business_id", name="uq_services_id_business_id"),
        # staff_id (nullable, "if applicable") must belong to the same business_id.
        ForeignKeyConstraint(
            ["staff_id", "business_id"],
            ["staff.id", "staff.business_id"],
            name="fk_services_staff_same_tenant",
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(nullable=False)
    staff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    # Phase 44: per-service deposit configuration for real payment collection
    # (a Premium feature, gated at the business level — see Business.
    # payment_collection_enabled). Off by default: a pre-existing service
    # keeps requiring no online payment after migration. deposit_percentage
    # is only meaningful when deposit_enabled is true (enforced by
    # ServiceCreate/ServiceUpdate, not a DB CHECK constraint — same pattern
    # as this codebase's other conditionally-meaningful fields).
    deposit_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    deposit_percentage: Mapped[int | None] = mapped_column()
