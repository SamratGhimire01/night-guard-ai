import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.mixins import CreatedAtMixin, TenantMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin


class AppointmentStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class Appointment(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        # Lets Notification enforce that an appointment_id it references belongs to the
        # same business_id.
        UniqueConstraint("id", "business_id", name="uq_appointments_id_business_id"),
        # customer_id / service_id / staff_id must all belong to the same business_id as
        # this appointment. staff_id is nullable; a NULL staff_id is not checked
        # (Postgres default MATCH SIMPLE), which is the desired behavior.
        ForeignKeyConstraint(
            ["customer_id", "business_id"],
            ["customers.id", "customers.business_id"],
            name="fk_appointments_customer_same_tenant",
        ),
        ForeignKeyConstraint(
            ["service_id", "business_id"],
            ["services.id", "services.business_id"],
            name="fk_appointments_service_same_tenant",
        ),
        ForeignKeyConstraint(
            ["staff_id", "business_id"],
            ["staff.id", "staff.business_id"],
            name="fk_appointments_staff_same_tenant",
        ),
        # Phase 10 race-condition guarantee: this is the ONLY thing that makes
        # concurrent double-booking actually impossible (app-level "check then
        # insert" cannot, by itself). Two overlapping appointments for the same
        # (business_id, resolved staff resource) can never both commit. A NULL
        # staff_id coalesces to business_id, so an unassigned booking is treated as
        # occupying a single shared per-business resource — see booking_service's
        # module docstring for why. appointment_range() is a DB-side IMMUTABLE SQL
        # function (added in the migration) wrapping `scheduled_at + duration` as a
        # tstzrange; it exists only because Postgres won't let a GiST index
        # expression call the (STABLE) timestamptz-plus-interval operator directly.
        # Cancelled appointments never occupy the resource, hence the WHERE clause.
        ExcludeConstraint(
            (text("business_id"), "="),
            (text("COALESCE(staff_id, business_id)"), "="),
            (func.appointment_range(text("scheduled_at"), text("duration_minutes")), "&&"),
            # 'CANCELLED' uppercase: SQLAlchemy's Enum(AppointmentStatus) stores the
            # Python member NAME as the Postgres enum label, not member.value.
            where=text("status <> 'CANCELLED'::appointment_status"),
            using="gist",
            name="excl_appointments_no_overlap",
        ),
        # get_available_slots and list_appointments both filter by business_id +
        # a scheduled_at date range every time they run.
        Index("ix_appointments_business_id_scheduled_at", "business_id", "scheduled_at"),
    )

    # No inline ForeignKey on these three: the composite fk_appointments_*_same_tenant
    # constraints below already enforce them against customers/services/staff.
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    service_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    staff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, name="appointment_status"), nullable=False
    )
    # Phase 12: shared by every Appointment row written from the same
    # group-booking request (e.g. "book me and my wife and daughter"), so
    # GET /appointments can show/filter "these were booked together." NULL for
    # every ordinary single-person booking — this is purely additive, nothing
    # about Phase 10/11's booking path changes.
    group_booking_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)


class AppointmentParticipant(UUIDPrimaryKeyMixin, Base):
    """An extra named participant on an appointment. No business_id: inherited via appointment_id."""

    __tablename__ = "appointment_participants"

    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
