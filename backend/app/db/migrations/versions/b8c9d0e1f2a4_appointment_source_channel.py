"""appointments.source_channel: which chat channel a booking came from (Analytics channel breakdown)

Revision ID: b8c9d0e1f2a4
Revises: a7b8c9d0e1f3
Create Date: 2026-09-21 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8c9d0e1f2a4'
down_revision = 'a7b8c9d0e1f3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL for every existing row and never back-filled: the channel of an old booking can't be reconstructed reliably.
    op.add_column('appointments', sa.Column('source_channel', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('appointments', 'source_channel')
