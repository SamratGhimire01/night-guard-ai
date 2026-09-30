"""website chat install detection (for the setup checklist)

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-09-30 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f5a6b7c8d9e0'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('businesses', sa.Column('widget_installed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('businesses', sa.Column('widget_installed_origin', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('businesses', 'widget_installed_origin')
    op.drop_column('businesses', 'widget_installed_at')
