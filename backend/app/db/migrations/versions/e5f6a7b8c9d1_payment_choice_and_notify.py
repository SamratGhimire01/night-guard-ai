"""customer chooses eSewa or Khalti; payment-success chat notification

Revision ID: e5f6a7b8c9d1
Revises: c3d4e5f6a7b9
Create Date: 2026-09-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d1'
down_revision = 'c3d4e5f6a7b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('businesses', sa.Column('payment_providers', postgresql.ARRAY(sa.String(length=20)), server_default='{}', nullable=False))
    # keep every existing business on exactly the gateway it already had
    op.execute("UPDATE businesses SET payment_providers = ARRAY[payment_provider] WHERE payment_provider IS NOT NULL")
    op.drop_column('businesses', 'payment_provider')
    op.add_column('conversations', sa.Column('payment_choice_appointment_id', sa.UUID(), nullable=True))
    op.add_column('payments', sa.Column('conversation_id', sa.UUID(), nullable=True))
    op.add_column('payments', sa.Column('completion_notified_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('payments', 'completion_notified_at')
    op.drop_column('payments', 'conversation_id')
    op.drop_column('conversations', 'payment_choice_appointment_id')
    op.add_column('businesses', sa.Column('payment_provider', sa.VARCHAR(length=20), nullable=True))
    op.execute("UPDATE businesses SET payment_provider = payment_providers[1]")
    op.drop_column('businesses', 'payment_providers')
