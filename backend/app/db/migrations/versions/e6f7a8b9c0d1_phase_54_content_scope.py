"""phase 54 per-business content scope (single_business | aggregator)

Revision ID: e6f7a8b9c0d1
Revises: b3c4d5e6f7a8
Create Date: 2026-09-22 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e6f7a8b9c0d1'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The native Postgres ENUM must be created explicitly before ADD COLUMN on an existing table (see phase 34's migration).
    sa.Enum('SINGLE_BUSINESS', 'AGGREGATOR', name='business_content_scope').create(op.get_bind(), checkfirst=True)
    op.add_column(
        'businesses',
        sa.Column(
            'content_scope',
            sa.Enum('SINGLE_BUSINESS', 'AGGREGATOR', name='business_content_scope'),
            server_default='SINGLE_BUSINESS',
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column('businesses', 'content_scope')
    sa.Enum(name='business_content_scope').drop(op.get_bind(), checkfirst=True)
