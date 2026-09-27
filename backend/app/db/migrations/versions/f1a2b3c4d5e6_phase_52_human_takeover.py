"""phase 52 human takeover on conversations

Revision ID: f1a2b3c4d5e6
Revises: b8c9d0e1f2a4
Create Date: 2026-09-21 14:40:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = 'b8c9d0e1f2a4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('human_takeover_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('conversations', sa.Column('human_takeover_by', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_conversations_human_takeover_by_business_users', 'conversations', 'business_users',
        ['human_takeover_by'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_conversations_human_takeover_by_business_users', 'conversations', type_='foreignkey')
    op.drop_column('conversations', 'human_takeover_by')
    op.drop_column('conversations', 'human_takeover_until')
