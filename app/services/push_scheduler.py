"""
Scheduler for push notification review reminders.

Uses APScheduler to check every 5 minutes whether a reminder or
streak-at-risk alert should be sent. Tracks last-sent dates in
.settings.json to avoid multiple sends per day.
"""
import json
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

_CENTRAL = ZoneInfo("America/Chicago")

logger = logging.getLogger(__name__)

_SCHEDULER = None

_SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", ".settings.json"
)


def _read_settings() -> dict:
    try:
        with open(_SETTINGS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_settings(s: dict):
    try:
        os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
        with open(_SETTINGS_FILE, "w") as f:
            json.dump(s, f)
    except Exception as e:
        logger.warning("Failed to write settings: %s", e)


async def _check_reminder():
    """Send a review reminder push if it's time and user hasn't reviewed today."""
    settings = _read_settings()

    if not settings.get("push_enabled", False):
        return

    today_str = datetime.now(_CENTRAL).date().isoformat()
    if settings.get("last_push_reminder_sent") == today_str:
        return  # Already sent today

    # Check if current time >= configured reminder time
    now = datetime.now(_CENTRAL)
    reminder_time = settings.get("push_reminder_time", "09:00")
    try:
        hour, minute = map(int, reminder_time.split(":"))
    except (ValueError, AttributeError):
        return

    if now.hour < hour or (now.hour == hour and now.minute < minute):
        return  # Too early

    # ── Time to check! ──
    from app.database import async_session
    from app.routes.review import _reviewed_today_count
    from app.services.push_service import send_push_to_all

    async with async_session() as db:
        done = await _reviewed_today_count(db)
        if done > 0:
            # Already reviewed — nothing to remind about
            settings["last_push_reminder_sent"] = today_str
            _write_settings(settings)
            return

        result = await send_push_to_all(
            title="⏰ Time for your daily review!",
            body="You haven't reviewed any highlights today. Keep your streak alive!",
            db=db,
            url="/review",
        )
        logger.info("Push reminder sent: %s", result)

    settings["last_push_reminder_sent"] = today_str
    _write_settings(settings)


async def _check_streak_alert():
    """Send a streak-at-risk push if it's evening and user hasn't reviewed."""
    settings = _read_settings()

    if not settings.get("push_streak_alert_enabled", False):
        return

    today_str = datetime.now(_CENTRAL).date().isoformat()
    if settings.get("last_push_streak_alert_sent") == today_str:
        return

    # Check if current time >= configured alert time (default 20:00)
    now = datetime.now(_CENTRAL)
    alert_time = settings.get("push_streak_alert_time", "20:00")
    try:
        hour, minute = map(int, alert_time.split(":"))
    except (ValueError, AttributeError):
        return

    if now.hour < hour or (now.hour == hour and now.minute < minute):
        return  # Too early

    # ── Time to check! ──
    from app.database import async_session
    from app.routes.review import _reviewed_today_count
    from app.services.streaks import calculate_streaks
    from app.services.push_service import send_push_to_all

    async with async_session() as db:
        streaks = await calculate_streaks(db)
        current_streak = streaks.get("current", 0)
        if current_streak == 0:
            return  # No streak to protect

        done = await _reviewed_today_count(db)
        if done > 0:
            return  # Already reviewed

        result = await send_push_to_all(
            title="🔥 Your streak is at risk!",
            body=f"You'll lose your {current_streak}-day streak! Just one highlight can save it.",
            db=db,
            url="/review",
        )
        logger.info("Push streak alert sent: %s", result)

    settings["last_push_streak_alert_sent"] = today_str
    _write_settings(settings)


async def _check_all():
    """Run both push checks — called by the scheduler every 5 minutes."""
    try:
        await _check_reminder()
    except Exception as e:
        logger.error("Push reminder check failed: %s", e)
    try:
        await _check_streak_alert()
    except Exception as e:
        logger.error("Push streak alert check failed: %s", e)


def start_scheduler():
    """Start the background scheduler that checks for push delivery."""
    global _SCHEDULER
    if _SCHEDULER is not None:
        return

    _SCHEDULER = AsyncIOScheduler()
    _SCHEDULER.add_job(_check_all, "interval", minutes=5, id="push_check")
    _SCHEDULER.start()
    logger.info("Push scheduler started (checking every 5 minutes)")


def stop_scheduler():
    """Shut down the scheduler cleanly."""
    global _SCHEDULER
    if _SCHEDULER:
        _SCHEDULER.shutdown(wait=False)
        _SCHEDULER = None
        logger.info("Push scheduler stopped")
