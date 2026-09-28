"""phase 2: style_exemplars table + business persona card fields

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-09-28 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


# revision identifiers, used by Alembic.
revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Persona card: additive, nullable/defaulted columns only -- every existing
    # business keeps today's exact behavior (see intent.py._build_system_prompt,
    # which only appends anything for these when they differ from their default).
    op.add_column('businesses', sa.Column('business_type', sa.String(length=50), nullable=True))
    op.add_column('businesses', sa.Column('persona_name', sa.String(length=100), nullable=True))
    sa.Enum('CASUAL', 'NEUTRAL', 'FORMAL', name='business_formality').create(op.get_bind(), checkfirst=True)
    op.add_column(
        'businesses',
        sa.Column(
            'formality', sa.Enum('CASUAL', 'NEUTRAL', 'FORMAL', name='business_formality'),
            server_default='NEUTRAL', nullable=False,
        ),
    )
    sa.Enum('DEFAULT', 'NONE', name='business_emoji_policy').create(op.get_bind(), checkfirst=True)
    op.add_column(
        'businesses',
        sa.Column(
            'emoji_policy', sa.Enum('DEFAULT', 'NONE', name='business_emoji_policy'),
            server_default='DEFAULT', nullable=False,
        ),
    )
    op.add_column('businesses', sa.Column('sign_off', sa.String(length=200), nullable=True))

    # style_exemplars: fact-free, human-written example replies used to nudge tone/
    # register in intent.py's LLM-draft prompt ONLY -- see intent.py/orchestrator.py.
    # business_id nullable: null = shared/global (usable by any tenant, further
    # narrowed by business_type below); non-null = a real tenant-specific override.
    op.create_table(
        'style_exemplars',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('business_id', sa.UUID(), nullable=True),
        # A shared exemplar's flavor (e.g. "dental", "trekking") -- matched against
        # the retrieving tenant's own businesses.business_type. Null means truly
        # universal (matches every tenant regardless of type).
        sa.Column('business_type', sa.String(length=50), nullable=True),
        sa.Column('intent', sa.String(length=50), nullable=False),
        sa.Column('language', sa.String(length=20), nullable=False),
        sa.Column('register', sa.String(length=20), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_style_exemplars_business_id'), 'style_exemplars', ['business_id'], unique=False)
    op.create_index(op.f('ix_style_exemplars_language'), 'style_exemplars', ['language'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_style_exemplars_language'), table_name='style_exemplars')
    op.drop_index(op.f('ix_style_exemplars_business_id'), table_name='style_exemplars')
    op.drop_table('style_exemplars')
    op.drop_column('businesses', 'sign_off')
    op.drop_column('businesses', 'emoji_policy')
    sa.Enum(name='business_emoji_policy').drop(op.get_bind(), checkfirst=True)
    op.drop_column('businesses', 'formality')
    sa.Enum(name='business_formality').drop(op.get_bind(), checkfirst=True)
    op.drop_column('businesses', 'persona_name')
    op.drop_column('businesses', 'business_type')
