from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.mixins import CreatedAtMixin, TenantMixin, UUIDPrimaryKeyMixin


class Staff(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, Base):
    """A tenant's own staff member (e.g. a dentist or hygienist)."""

    __tablename__ = "staff"
    __table_args__ = (
        # Lets Appointment enforce, at the database level, that a staff_id it references
        # belongs to the same business_id.
        UniqueConstraint("id", "business_id", name="uq_staff_id_business_id"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(100), nullable=False)
