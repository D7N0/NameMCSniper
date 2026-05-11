"""
Parsing helpers for NameMC drop-window timestamps.
"""

import re
from datetime import datetime, timezone

NAMEMC_TIME_FORMAT = "M/D/YYYY • H:MM:SS AM/PM"

_NAMEMC_TIME_RE = re.compile(
    r"^\s*"
    r"(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})"
    r"\s*•\s*"
    r"(?P<hour>\d{1,2})[:∶](?P<minute>\d{2})[:∶](?P<second>\d{2})"
    r"\s*(?P<period>AM|PM)"
    r"\s*$",
    re.IGNORECASE,
)


def parse_namemc_time(drop_window: str) -> datetime:
    """
    Parse a NameMC timestamp as local time and return UTC.

    Accepts both the regular colon format NameMC commonly copies today:
    "6/7/2026 • 6:06:50 PM"

    and the older mathematical-colon variant:
    "6/7/2026 • 6∶06∶50 PM"
    """
    if not drop_window:
        raise ValueError(f"Expected NameMC time format: {NAMEMC_TIME_FORMAT}")

    match = _NAMEMC_TIME_RE.match(drop_window)
    if not match:
        raise ValueError(
            f"Expected NameMC time format: {NAMEMC_TIME_FORMAT} "
            f"(example: 6/7/2026 • 6:06:50 PM)"
        )

    parts = match.groupdict()
    hour = int(parts["hour"])
    minute = int(parts["minute"])
    second = int(parts["second"])
    period = parts["period"].upper()

    if hour < 1 or hour > 12:
        raise ValueError("Hour must be between 1 and 12")

    if period == "AM":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12

    try:
        local_time = datetime(
            int(parts["year"]),
            int(parts["month"]),
            int(parts["day"]),
            hour,
            minute,
            second,
        )
    except ValueError as exc:
        raise ValueError(f"Invalid date/time in NameMC timestamp: {exc}") from exc

    # For a naive datetime, astimezone() treats it as system local time and
    # applies the OS timezone/DST rules for that date.
    return local_time.astimezone().astimezone(timezone.utc)


def display_namemc_time(drop_window: str) -> str:
    """Return a cleaned display version with regular colons."""
    return drop_window.replace("∶", ":").strip()
