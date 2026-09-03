from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.mixins import CreatedAtMixin, TenantMixin, UUIDPrimaryKeyMixin


class Customer(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, Base):
    """A tenant's end customer (e.g. a dental patient)."""

    __tablename__ = "customers"
    __table_args__ = (
        # Lets other tenant tables (Appointment, Conversation, FollowUp) enforce, at the
        # database level, that a customer_id they reference belongs to the same business_id.
        UniqueConstraint("id", "business_id", name="uq_customers_id_business_id"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    preferred_language: Mapped[str | None] = mapped_column(String(32))
