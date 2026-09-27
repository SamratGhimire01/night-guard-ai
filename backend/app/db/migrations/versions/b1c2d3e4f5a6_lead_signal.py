"""automatic buying-intent lead signal + summary for the inbox's Leads tab

Revision ID: b1c2d3e4f5a6
Revises: a9b8c7d6e5f4
Create Date: 2026-09-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1c2d3e4f5a6'
down_revision = 'a9b8c7d6e5f4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('lead_signal', sa.String(length=20), nullable=True))
    op.add_column('conversations', sa.Column('lead_summary', sa.Text(), nullable=True))
    op.add_column('conversations', sa.Column('lead_scored_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('conversations', 'lead_scored_at')
    op.drop_column('conversations', 'lead_summary')
    op.drop_column('conversations', 'lead_signal')
