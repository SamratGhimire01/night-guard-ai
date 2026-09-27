"""phase 58 per-business booking_enabled flag (booking as an optional module)

Revision ID: a9b8c7d6e5f4
Revises: c7d8e9f0a1b2
Create Date: 2026-09-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9b8c7d6e5f4'
down_revision = 'c7d8e9f0a1b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'businesses',
        sa.Column('booking_enabled', sa.Boolean(), server_default='true', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('businesses', 'booking_enabled')
