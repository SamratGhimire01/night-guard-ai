"""store businesses' time zones under their current IANA names

Chrome reported "Asia/Katmandu" (and similar old names) at sign-up; the API image's tz database doesn't have them, so
those businesses couldn't compute open slots. New sign-ups are cleaned by app.core.timezones; this fixes old rows.

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-09-30 18:00:00.000000

"""
from zoneinfo import available_timezones

from alembic import op
import sqlalchemy as sa

# Frozen copy of app.core.timezones.LEGACY_TIMEZONES as of this migration.
_LEGACY = {
    "Asia/Katmandu": "Asia/Kathmandu",
    "Asia/Calcutta": "Asia/Kolkata",
    "Asia/Saigon": "Asia/Ho_Chi_Minh",
    "Asia/Rangoon": "Asia/Yangon",
    "Asia/Dacca": "Asia/Dhaka",
    "Asia/Thimbu": "Asia/Thimphu",
    "Asia/Ulan_Bator": "Asia/Ulaanbaatar",
    "Asia/Chongqing": "Asia/Shanghai",
    "Asia/Chungking": "Asia/Shanghai",
    "Asia/Harbin": "Asia/Shanghai",
    "Asia/Macao": "Asia/Macau",
    "Asia/Ujung_Pandang": "Asia/Makassar",
    "Asia/Ashkhabad": "Asia/Ashgabat",
    "Asia/Tel_Aviv": "Asia/Jerusalem",
    "Asia/Istanbul": "Europe/Istanbul",
    "Europe/Kiev": "Europe/Kyiv",
    "America/Godthab": "America/Nuuk",
    "America/Buenos_Aires": "America/Argentina/Buenos_Aires",
    "America/Indianapolis": "America/Indiana/Indianapolis",
    "America/Louisville": "America/Kentucky/Louisville",
    "Atlantic/Faeroe": "Atlantic/Faroe",
    "Pacific/Truk": "Pacific/Chuuk",
    "Pacific/Ponape": "Pacific/Pohnpei",
    "Pacific/Enderbury": "Pacific/Kanton",
    "US/Eastern": "America/New_York",
    "US/Central": "America/Chicago",
    "US/Mountain": "America/Denver",
    "US/Pacific": "America/Los_Angeles",
    "Etc/UTC": "UTC",
    "Etc/GMT": "UTC",
}


# revision identifiers, used by Alembic.
revision = 'a6b7c8d9e0f1'
down_revision = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    known = available_timezones()
    for old, current in _LEGACY.items():
        if current in known:
            bind.execute(sa.text("UPDATE businesses SET timezone = :current WHERE timezone = :old"), {"current": current, "old": old})


def downgrade() -> None:
    # The old names were never needed; nothing to restore.
    pass
