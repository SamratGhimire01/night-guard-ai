"""phase 36 service knowledge document attachment

Revision ID: a0ec080bbff5
Revises: 1b540231b5fa
Create Date: 2026-09-06 07:38:23.220469

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a0ec080bbff5'
down_revision = '1b540231b5fa'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Hand-fixed ordering (autogenerate emitted this AFTER create_table, which fails —
    # the composite FK below needs this unique constraint to already exist):
    # a UNIQUE(id, business_id) on knowledge_documents, same pattern services/staff
    # already have, needed so ServiceKnowledgeDocument's composite FK can enforce
    # "this knowledge_document_id belongs to the same business_id" at the DB level.
    op.create_unique_constraint('uq_knowledge_documents_id_business_id', 'knowledge_documents', ['id', 'business_id'])
    op.create_table('service_knowledge_documents',
    sa.Column('service_id', sa.UUID(), nullable=False),
    sa.Column('knowledge_document_id', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('business_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['knowledge_document_id', 'business_id'], ['knowledge_documents.id', 'knowledge_documents.business_id'], name='fk_skd_knowledge_document_same_tenant', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['service_id', 'business_id'], ['services.id', 'services.business_id'], name='fk_skd_service_same_tenant', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('service_id', 'knowledge_document_id', name='uq_service_knowledge_document')
    )
    op.create_index(op.f('ix_service_knowledge_documents_business_id'), 'service_knowledge_documents', ['business_id'], unique=False)
    op.create_index(op.f('ix_service_knowledge_documents_knowledge_document_id'), 'service_knowledge_documents', ['knowledge_document_id'], unique=False)
    op.create_index(op.f('ix_service_knowledge_documents_service_id'), 'service_knowledge_documents', ['service_id'], unique=False)


def downgrade() -> None:
    # Reverse order from upgrade(): the table (and its FK referencing the unique
    # constraint below) must be dropped BEFORE that unique constraint, or Postgres
    # refuses to drop a constraint a live foreign key still depends on.
    op.drop_index(op.f('ix_service_knowledge_documents_service_id'), table_name='service_knowledge_documents')
    op.drop_index(op.f('ix_service_knowledge_documents_knowledge_document_id'), table_name='service_knowledge_documents')
    op.drop_index(op.f('ix_service_knowledge_documents_business_id'), table_name='service_knowledge_documents')
    op.drop_table('service_knowledge_documents')
    op.drop_constraint('uq_knowledge_documents_id_business_id', 'knowledge_documents', type_='unique')
