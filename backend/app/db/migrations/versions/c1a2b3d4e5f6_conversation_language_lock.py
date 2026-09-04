"""conversation language lock

Revision ID: c1a2b3d4e5f6
Revises: 7bf5f90d0620
Create Date: 2026-09-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1a2b3d4e5f6'
down_revision = '7bf5f90d0620'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('detected_language', sa.String(length=20), nullable=True))
    op.add_column(
        'conversations',
        sa.Column('language_switch_streak', sa.Integer(), server_default='0', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('conversations', 'language_switch_streak')
    op.drop_column('conversations', 'detected_language')
