"""booking draft offered service

Revision ID: c7d8e9f0a1b2
Revises: d4e5f6a7b8c9
Create Date: 2026-09-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'c7d8e9f0a1b2'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('booking_draft_offered_service_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_conversations_booking_draft_offered_service_same_tenant',
        'conversations',
        'services',
        ['booking_draft_offered_service_id', 'business_id'],
        ['id', 'business_id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_conversations_booking_draft_offered_service_same_tenant', 'conversations', type_='foreignkey')
    op.drop_column('conversations', 'booking_draft_offered_service_id')
