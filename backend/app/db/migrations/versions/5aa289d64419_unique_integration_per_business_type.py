"""unique integration per business+type

Revision ID: 5aa289d64419
Revises: d2b3c4e5f6a7
Create Date: 2026-09-05 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '5aa289d64419'
down_revision = 'd2b3c4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_integrations_business_type", "integrations", ["business_id", "type"])


def downgrade() -> None:
    op.drop_constraint("uq_integrations_business_type", "integrations", type_="unique")
