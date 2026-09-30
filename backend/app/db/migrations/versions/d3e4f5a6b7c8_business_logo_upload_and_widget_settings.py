"""business logo upload + website widget settings

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-09-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Additive only: an existing business keeps its logo_url and gets an empty widget_settings, which the widget
    # config route fills with today's look (same name, colour and placement as before).
    op.add_column('businesses', sa.Column('logo_image', sa.LargeBinary(), nullable=True))
    op.add_column('businesses', sa.Column('logo_content_type', sa.String(length=32), nullable=True))
    op.add_column(
        'businesses',
        sa.Column('widget_settings', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
    )


def downgrade() -> None:
    op.drop_column('businesses', 'widget_settings')
    op.drop_column('businesses', 'logo_content_type')
    op.drop_column('businesses', 'logo_image')
