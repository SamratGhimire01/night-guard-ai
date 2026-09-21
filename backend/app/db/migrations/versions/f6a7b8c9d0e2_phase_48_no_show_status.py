"""phase 48 no_show appointment status

Revision ID: f6a7b8c9d0e2
Revises: e5f6a7b8c9d1
Create Date: 2026-09-21 12:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'f6a7b8c9d0e2'
down_revision = 'e5f6a7b8c9d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Adding an enum VALUE isn't a column diff, so autogenerate never emits it. Uppercase label to match this project's
    # convention (SQLAlchemy stores the Python member NAME). Same pattern as Phase 46's ARRIVED: never remaps or touches
    # an existing row — no appointment becomes NO_SHOW by migrating, only by the scheduler's own atomic claim.
    op.execute("ALTER TYPE appointment_status ADD VALUE IF NOT EXISTS 'NO_SHOW'")


def downgrade() -> None:
    # No ALTER TYPE ... DROP VALUE in Postgres: rebuild the type without NO_SHOW. A NO_SHOW row goes back to CONFIRMED —
    # the honest pre-feature state (it was never checked in). The Phase 10 exclusion constraint's predicate casts to
    # `appointment_status`, so it is dropped and recreated identically around the rebuild (see Phase 46's downgrade).
    op.execute("UPDATE appointments SET status = 'CONFIRMED' WHERE status = 'NO_SHOW'")
    op.execute("ALTER TABLE appointments DROP CONSTRAINT excl_appointments_no_overlap")
    op.execute("ALTER TYPE appointment_status RENAME TO appointment_status_old")
    op.execute("CREATE TYPE appointment_status AS ENUM ('PENDING', 'CONFIRMED', 'CANCELLED', 'ARRIVED', 'COMPLETED')")
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
