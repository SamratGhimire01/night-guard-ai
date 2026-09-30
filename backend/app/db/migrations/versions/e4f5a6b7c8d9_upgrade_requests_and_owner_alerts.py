"""upgrade requests + owner alert toggle

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-09-30 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e4f5a6b7c8d9'
down_revision = 'd3e4f5a6b7c8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('businesses', sa.Column('upgrade_requested_at', sa.DateTime(timezone=True), nullable=True))
    # On by default: an owner should hear about a customer waiting for them without having to find a setting first.
    op.add_column(
        'businesses', sa.Column('owner_alerts_enabled', sa.Boolean(), nullable=False, server_default='true')
    )


def downgrade() -> None:
    op.drop_column('businesses', 'owner_alerts_enabled')
    op.drop_column('businesses', 'upgrade_requested_at')
