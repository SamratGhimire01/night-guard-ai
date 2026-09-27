"""phase 52 message author + delivery status + idempotency key + thread index

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-09-21 15:10:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'a2b3c4d5e6f7'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('sent_by_user_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('messages', sa.Column('delivery_status', sa.String(length=20), nullable=True))
    op.add_column('messages', sa.Column('delivery_detail', sa.String(length=255), nullable=True))
    op.add_column('messages', sa.Column('client_msg_id', sa.String(length=64), nullable=True))
    op.create_foreign_key(
        'fk_messages_sent_by_user_id_business_users', 'messages', 'business_users',
        ['sent_by_user_id'], ['id'], ondelete='SET NULL',
    )
    op.create_unique_constraint('uq_messages_conversation_client_msg_id', 'messages', ['conversation_id', 'client_msg_id'])
    op.create_index('ix_messages_conversation_id_created_at', 'messages', ['conversation_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_messages_conversation_id_created_at', table_name='messages')
    op.drop_constraint('uq_messages_conversation_client_msg_id', 'messages', type_='unique')
    op.drop_constraint('fk_messages_sent_by_user_id_business_users', 'messages', type_='foreignkey')
    op.drop_column('messages', 'client_msg_id')
    op.drop_column('messages', 'delivery_detail')
    op.drop_column('messages', 'delivery_status')
    op.drop_column('messages', 'sent_by_user_id')
