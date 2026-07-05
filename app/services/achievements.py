"""Achievement definitions and unlock logic.

Achievements are awarded once per milestone and persisted in the
user_achievements table. Each has a key, label, and witty message.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models import UserAchievement, ReviewLog

# ── Achievement definitions ─────────────────────────────────────────────────

ACHIEVEMENTS = [
    {
        "key": "first_review",
        "label": "First Steps",
        "icon": "🐣",
        "check": "first_review",
        "threshold": None,
        "message": "You reviewed your first highlight! The highlight is so proud it told all its friends. They're all very impressed.",
    },
    {
        "key": "streak_7",
        "label": "Streak Starter",
        "icon": "🌱",
        "check": "streak",
        "threshold": 7,
        "message": "Seven days! You've officially outlasted a trial of a streaming service.",
    },
    {
        "key": "streak_30",
        "label": "Whole Month",
        "icon": "🌿",
        "check": "streak",
        "threshold": 30,
        "message": "30 days! You've been highlighting longer than most New Year's resolutions last.",
    },
    {
        "key": "streak_90",
        "label": "The Quarter Pounder",
        "icon": "🌳",
        "check": "streak",
        "threshold": 90,
        "message": "90 days! That's a full season of bad TV you could have watched. Good choice.",
    },
    {
        "key": "streak_180",
        "label": "Half a Year",
        "icon": "🏛️",
        "check": "streak",
        "threshold": 180,
        "message": "Six months! You are more committed than most houseplants get watered.",
    },
    {
        "key": "streak_365",
        "label": "The Yearling",
        "icon": "👑",
        "check": "streak",
        "threshold": 365,
        "message": "A full year! You have officially been consistent longer than the author's writing schedule.",
    },
    {
        "key": "centurion",
        "label": "Centurion",
        "icon": "⚔️",
        "check": "total_days",
        "threshold": 100,
        "message": "100 days of reviewing! That's more commitment than a Roman legionnaire marching through Gaul.",
    },
    {
        "key": "night_owl",
        "label": "Night Owl",
        "icon": "🦉",
        "check": "night_owl",
        "threshold": None,
        "message": "Reviewing past midnight? The highlights aren't going to read themselves. Go to bed.",
    },
    {
        "key": "completionist_7",
        "label": "Completionist",
        "icon": "🏅",
        "check": "completionist",
        "threshold": 7,
        "message": "7 straight days of clearing your queue! You have the discipline of a zen monk with a to-do list.",
    },
]


def _get_achievement(key: str) -> dict | None:
    """Look up an achievement definition by key."""
    for a in ACHIEVEMENTS:
        if a["key"] == key:
            return a
    return None


async def _is_unlocked(db: AsyncSession, key: str) -> bool:
    """Check if an achievement has already been unlocked."""
    result = await db.execute(
        select(UserAchievement).where(
            UserAchievement.user_id == 1,
            UserAchievement.achievement_key == key,
        )
    )
    return result.scalar_one_or_none() is not None


async def _award(db: AsyncSession, ach: dict) -> dict:
    """Record an unlocked achievement and return the payload."""
    db.add(UserAchievement(
        user_id=1,
        achievement_key=ach["key"],
        message=ach["message"],
    ))
    await db.commit()
    return {
        "key": ach["key"],
        "label": ach["label"],
        "icon": ach["icon"],
        "message": ach["message"],
    }


async def check_and_unlock(
    db: AsyncSession,
    current_streak: int,
    review_hour: int | None = None,
    daily_limit: int = 10,
) -> list[dict]:
    """Check if any new achievements should be unlocked.

    Called after each review submission. Idempotent — will not re-award.

    Args:
        current_streak: Current streak from calculate_streaks()
        review_hour: Hour of the current review in Central time (0-23)
        daily_limit: Review count limit from settings
    """
    newly_unlocked = []

    for ach in ACHIEVEMENTS:
        if await _is_unlocked(db, ach["key"]):
            continue

        unlocked = False

        if ach["check"] == "streak":
            unlocked = current_streak >= ach["threshold"]

        elif ach["check"] == "total_days":
            # Count distinct Central-timezone dates with reviews
            _CENTRAL = ZoneInfo("America/Chicago")
            result = await db.execute(select(ReviewLog.reviewed_at).distinct())
            dates = set()
            for row in result.all():
                dt = row[0]
                if isinstance(dt, str):
                    dt = datetime.fromisoformat(dt)
                dates.add(dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(_CENTRAL).date())
            total_days = len(dates)
            unlocked = total_days >= ach["threshold"]

        elif ach["check"] == "night_owl":
            # Reviewed between midnight and 5am Central time
            unlocked = review_hour is not None and 0 <= review_hour < 5

        elif ach["check"] == "completionist":
            # 7 consecutive Central-timezone days where reviews >= daily_limit
            _CENTRAL = ZoneInfo("America/Chicago")
            result = await db.execute(select(ReviewLog.reviewed_at))
            # Group by Central date in Python
            central_counts = {}
            for row in result.all():
                dt = row[0]
                if isinstance(dt, str):
                    dt = datetime.fromisoformat(dt)
                d = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(_CENTRAL).date()
                central_counts[d] = central_counts.get(d, 0) + 1
            # Sort descending by Central date
            sorted_dates = sorted(central_counts.keys(), reverse=True)[:ach["threshold"]]
            if len(sorted_dates) >= ach["threshold"]:
                unlocked = True
                for i, d in enumerate(sorted_dates):
                    if central_counts[d] < daily_limit:
                        unlocked = False
                        break
                    if i > 0:
                        prev = sorted_dates[i - 1]
                        if (prev - d).days != 1:
                            unlocked = False
                            break

        elif ach["check"] == "first_review":
            result = await db.execute(select(func.count(ReviewLog.id)))
            unlocked = (result.scalar() or 0) >= 1

        if unlocked:
            newly_unlocked.append(await _award(db, ach))

    return newly_unlocked


async def get_all_achievements(db: AsyncSession) -> list[dict]:
    """Return all achievement definitions with unlock status."""
    result = await db.execute(
        select(UserAchievement).where(UserAchievement.user_id == 1)
    )
    unlocked = {ua.achievement_key: ua for ua in result.scalars().all()}

    output = []
    for ach in ACHIEVEMENTS:
        ua = unlocked.get(ach["key"])
        output.append({
            "key": ach["key"],
            "label": ach["label"],
            "icon": ach["icon"],
            "message": ach["message"] if not ua else ua.message,
            "unlocked": ua is not None,
            "unlocked_at": ua.unlocked_at.isoformat() if ua else None,
        })
    return output


async def backfill_achievements(db: AsyncSession, current_streak: int) -> int:
    """On startup, check and award any achievements already earned.
    Returns the number of newly backfilled achievements.
    """
    count = 0
    for ach in ACHIEVEMENTS:
        if await _is_unlocked(db, ach["key"]):
            continue

        should_award = False
        if ach["check"] == "streak":
            should_award = current_streak >= ach["threshold"]
        elif ach["check"] == "total_days":
            # Count distinct Central-timezone dates with reviews
            _CENTRAL = ZoneInfo("America/Chicago")
            result = await db.execute(select(ReviewLog.reviewed_at).distinct())
            dates = set()
            for row in result.all():
                dt = row[0]
                if isinstance(dt, str):
                    dt = datetime.fromisoformat(dt)
                dates.add(dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(_CENTRAL).date())
            total_days = len(dates)
            should_award = total_days >= ach["threshold"]
        elif ach["check"] == "completionist":
            _CENTRAL = ZoneInfo("America/Chicago")
            result = await db.execute(select(ReviewLog.reviewed_at))
            # Group by Central date in Python
            central_counts = {}
            for row in result.all():
                dt = row[0]
                if isinstance(dt, str):
                    dt = datetime.fromisoformat(dt)
                d = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(_CENTRAL).date()
                central_counts[d] = central_counts.get(d, 0) + 1
            sorted_dates = sorted(central_counts.keys(), reverse=True)[:ach["threshold"]]
            if len(sorted_dates) >= ach["threshold"]:
                should_award = True
                for i, d in enumerate(sorted_dates):
                    if central_counts[d] < 1:  # Can't know daily_limit at startup, use 1
                        should_award = False
                        break
        elif ach["check"] == "first_review":
            result = await db.execute(select(func.count(ReviewLog.id)))
            should_award = (result.scalar() or 0) >= 1

        if should_award:
            db.add(UserAchievement(
                user_id=1,
                achievement_key=ach["key"],
                message=ach["message"],
            ))
            count += 1

    if count > 0:
        await db.commit()
    return count
