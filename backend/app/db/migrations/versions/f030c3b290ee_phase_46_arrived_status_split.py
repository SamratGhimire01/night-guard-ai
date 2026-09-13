"""phase 46 arrived status split

Revision ID: f030c3b290ee
Revises: fc8e1d0ac457
Create Date: 2026-09-13 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f030c3b290ee'
down_revision = 'fc8e1d0ac457'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('appointments', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))

    # Not autogenerate-detected: adding an enum VALUE isn't a column diff.
    # 'ARRIVED' uppercase to match this project's established convention —
    # SQLAlchemy's Enum(AppointmentStatus) stores the Python member NAME as
    # the Postgres enum label, not member.value. Safe to run inside this
    # migration's transaction on Postgres 12+ as long as the new value is
    # never read/written in the same transaction that adds it — it isn't
    # here. Every pre-existing COMPLETED row is untouched by this migration
    # (real, genuine completions from before the ARRIVED split existed
    # remain exactly as they were — this only adds a new value, never
    # remaps an existing one).
    op.execute("ALTER TYPE appointment_status ADD VALUE IF NOT EXISTS 'ARRIVED'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE. Reversing requires rebuilding
    # the enum type from scratch: any row currently ARRIVED (checked in, not
    # yet completed) is remapped to CONFIRMED first — the honest pre-split
    # state, since the visit was never actually completed.
    #
    # Real bug found and fixed by actually running this downgrade against a
    # copy of this dev DB before trusting it (not just reasoning about it):
    # `excl_appointments_no_overlap` (Phase 10)'s own WHERE predicate casts a
    # literal to `appointment_status` — rebuilding the type out from under
    # that constraint without dropping it first fails with a real Postgres
    # error ("operator does not exist: appointment_status <>
    # appointment_status_old"), because the constraint's predicate stays
    # bound to the old (renamed) type. Dropped and recreated identically to
    # its original definition (app/db/models/appointment.py) around the
    # rebuild, verified clean in a rolled-back transaction against this real
    # dev DB.
    op.execute("UPDATE appointments SET status = 'CONFIRMED' WHERE status = 'ARRIVED'")
    op.execute("ALTER TABLE appointments DROP CONSTRAINT excl_appointments_no_overlap")
    op.execute("ALTER TYPE appointment_status RENAME TO appointment_status_old")
    op.execute("CREATE TYPE appointment_status AS ENUM ('PENDING', 'CONFIRMED', 'CANCELLED', 'COMPLETED')")
    op.execute(
        "ALTER TABLE appointments ALTER COLUMN status TYPE appointment_status "
        "USING status::text::appointment_status"
    )
    op.execute("DROP TYPE appointment_status_old")
    op.execute(
        "ALTER TABLE appointments ADD CONSTRAINT excl_appointments_no_overlap "
        "EXCLUDE USING gist ("
        "business_id WITH =, "
        "COALESCE(staff_id, business_id) WITH =, "
        "appointment_range(scheduled_at, duration_minutes) WITH &&"
        ") WHERE (status <> 'CANCELLED'::appointment_status)"
    )

    op.drop_column('appointments', 'completed_at')
