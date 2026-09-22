"""phase 16 per-business language mode (automatic | ask upfront)

Revision ID: d4e5f6a7b8c0
Revises: c3d4e5f6a7b9
Create Date: 2026-09-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c0'
down_revision = 'c3d4e5f6a7b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The native Postgres ENUM must be created explicitly before ADD COLUMN on an existing table (see phase 34's migration).
    sa.Enum('AUTOMATIC', 'ASK', name='business_language_mode').create(op.get_bind(), checkfirst=True)
    op.add_column('businesses', sa.Column('language_mode', sa.Enum('AUTOMATIC', 'ASK', name='business_language_mode'), server_default='AUTOMATIC', nullable=False))
    op.add_column('conversations', sa.Column('language_prompted', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('conversations', 'language_prompted')
    op.drop_column('businesses', 'language_mode')
    sa.Enum(name='business_language_mode').drop(op.get_bind(), checkfirst=True)
