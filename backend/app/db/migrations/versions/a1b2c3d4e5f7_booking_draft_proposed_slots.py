"""booking draft proposed slots

Revision ID: a1b2c3d4e5f7
Revises: f030c3b290ee
Create Date: 2026-09-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f7'
down_revision = 'f030c3b290ee'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('booking_draft_proposed_slots', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('conversations', 'booking_draft_proposed_slots')
