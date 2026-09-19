"""booking draft search anchor date

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-09-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a8'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('booking_draft_search_anchor_date', sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column('conversations', 'booking_draft_search_anchor_date')
