"""booking draft slot tracking

Revision ID: d2b3c4e5f6a7
Revises: c1a2b3d4e5f6
Create Date: 2026-09-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'd2b3c4e5f6a7'
down_revision = 'c1a2b3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('booking_draft_service_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('conversations', sa.Column('booking_draft_date', sa.String(length=10), nullable=True))
    op.add_column('conversations', sa.Column('booking_draft_time', sa.String(length=5), nullable=True))
    op.create_foreign_key(
        'fk_conversations_booking_draft_service_same_tenant',
        'conversations',
        'services',
        ['booking_draft_service_id', 'business_id'],
        ['id', 'business_id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_conversations_booking_draft_service_same_tenant', 'conversations', type_='foreignkey')
    op.drop_column('conversations', 'booking_draft_time')
    op.drop_column('conversations', 'booking_draft_date')
    op.drop_column('conversations', 'booking_draft_service_id')
