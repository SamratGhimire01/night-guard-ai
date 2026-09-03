"""add unique constraint on business_users email

Revision ID: 5588d67a7cf6
Revises: 371630166e11
Create Date: 2026-09-03 17:40:00.827378

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '5588d67a7cf6'
down_revision = '371630166e11'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_business_users_email", "business_users", ["email"])


def downgrade() -> None:
    op.drop_constraint("uq_business_users_email", "business_users", type_="unique")
