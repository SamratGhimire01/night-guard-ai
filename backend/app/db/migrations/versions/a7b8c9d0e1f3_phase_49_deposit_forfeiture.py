"""phase 49 deposit forfeited due to no-show

Revision ID: a7b8c9d0e1f3
Revises: f6a7b8c9d0e2
Create Date: 2026-09-21 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7b8c9d0e1f3'
down_revision = 'f6a7b8c9d0e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL for every existing row: nothing is retroactively marked forfeited (same permanent rule as NO_SHOW itself).
    op.add_column('payments', sa.Column('forfeited_due_to_no_show_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('payments', 'forfeited_due_to_no_show_at')
