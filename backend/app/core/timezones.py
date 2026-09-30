"""Time zone names, cleaned up before they are stored.

Browsers report old IANA names for some zones (Chrome gives "Asia/Katmandu" for Nepal, "Asia/Calcutta" for India).
Many systems' tz databases, including the one in our API image, only ship the current names, so storing the old one
makes `ZoneInfo(business.timezone)` fail everywhere: open slots, reminders, reports. Every stored time zone goes
through `canonical_timezone` first.
"""

from zoneinfo import available_timezones

AVAILABLE_TIMEZONES = frozenset(available_timezones())

# Old name -> current name (from the tz database's "backward" file), limited to names browsers still report.
LEGACY_TIMEZONES = {
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


def canonical_timezone(name: str | None) -> str | None:
    """The name to store for `name`, or None when this server has no such zone."""
    if not name:
        return None
    name = name.strip()
    current = LEGACY_TIMEZONES.get(name)
    if current in AVAILABLE_TIMEZONES:
        return current
    return name if name in AVAILABLE_TIMEZONES else None
