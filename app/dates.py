"""Timezone helpers — Central time midnight for daily review resets."""

from datetime import datetime
from zoneinfo import ZoneInfo

_CENTRAL = ZoneInfo("America/Chicago")


def central_now() -> datetime:
    """Current time in America/Chicago."""
    return datetime.now(_CENTRAL)


def today_start_utc() -> datetime:
    """Midnight today Central time, returned as a UTC-naive datetime
    suitable for comparing against DB timestamps stored in UTC."""
    now_ct = central_now()
    midnight_ct = now_ct.replace(hour=0, minute=0, second=0, microsecond=0)
    # Convert to UTC and strip tzinfo for comparison with naive-UTC DB values
    return midnight_ct.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
