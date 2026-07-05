"""Streak tracking — daily review streaks and stat milestones."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models import ReviewLog
from app.services.settings_service import get_all as get_settings, set as set_setting

_CENTRAL = ZoneInfo("America/Chicago")


async def calculate_streaks(db: AsyncSession) -> dict:
    """Return current streak and best-ever streak based on ReviewLog.

    Both are calendar-day streaks in Central time (matching the daily
    review reset).  The current streak counts consecutive days ending
    with today *or* yesterday (so you don't lose it if you miss a day
    but haven't broken the habit).
    """
    # Fetch all raw reviewed_at datetimes (full precision, not func.date())
    result = await db.execute(
        select(ReviewLog.reviewed_at,)
        .order_by(ReviewLog.reviewed_at.desc())
    )
    rows = result.all()
    if not rows:
        return {"current": 0, "best": _load_best_streak()}

    # Convert each UTC datetime to Central date in Python
    central_dates = set()
    for row in rows:
        dt = row[0]
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        central_dates.add(
            dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(_CENTRAL).date()
        )

    # Sort unique central dates descending
    sorted_dates = sorted(central_dates, reverse=True)

    # --- Current streak ---
    today = datetime.now(_CENTRAL).date()
    yesterday = today - timedelta(days=1)
    current = 0

    if sorted_dates and sorted_dates[0] in (today, yesterday):
        current = 1
        for i in range(1, len(sorted_dates)):
            expected = sorted_dates[0] - timedelta(days=i)
            if sorted_dates[i] == expected:
                current += 1
            else:
                break

    # Persist best streak
    best = _load_best_streak()
    if current > best:
        best = current
        set_setting("best_streak", best)

    return {"current": current, "best": best}


def _load_best_streak() -> int:
    """Read the persisted best streak."""
    settings = get_settings()
    return settings.get("best_streak", 0)
