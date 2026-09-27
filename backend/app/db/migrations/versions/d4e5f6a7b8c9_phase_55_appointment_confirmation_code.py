"""phase 55 appointment confirmation_code (short customer-facing booking reference)

Revision ID: d4e5f6a7b8c9
Revises: e6f7a8b9c0d1
Create Date: 2026-09-27 09:00:00.000000

Root-cause fix for 21 of the 30 id_leak findings (read-through of
backend/data/regression/failure_log_batches/*.json): the customer-facing "Your
booking ID is ..." confirmation was reading out the raw internal UUID primary
key -- never meant for a customer, just an internal DB identifier. This is a
short, separate, customer-facing reference generated at booking time and shown
instead; the real `id` column is untouched and still used for every internal
lookup (cancel/reschedule/resend, check-in QR, payment redirect).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'e6f7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('appointments', sa.Column('confirmation_code', sa.String(length=8), nullable=True))
    # Backfill existing rows (dev/test data only -- this is a brand-new column) with a
    # deterministic-per-row value so the column can go NOT NULL + UNIQUE below.
    op.execute("UPDATE appointments SET confirmation_code = upper(substr(md5(id::text), 1, 7))")
    op.alter_column('appointments', 'confirmation_code', nullable=False)
    op.create_unique_constraint('uq_appointments_confirmation_code', 'appointments', ['confirmation_code'])


def downgrade() -> None:
    op.drop_constraint('uq_appointments_confirmation_code', 'appointments', type_='unique')
    op.drop_column('appointments', 'confirmation_code')
