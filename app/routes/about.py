"""About page — version info and quick reference."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models import Highlight, Tag, UserAchievement
from app.services.streaks import calculate_streaks
from app.services.settings_service import get_hardcover_api_key
from app.csrf import template_context
from app.template import render

router = APIRouter(tags=["about"])




@router.get("/about", response_class=HTMLResponse)
async def about_page(request: Request, db: AsyncSession = Depends(get_db)):
    """In-app about page with version, stats, and quick reference."""
    # Defer import to avoid circular import (main.py imports this module)
    from app.main import app

    version = app.version

    # Stats
    hl_count = (await db.execute(select(func.count(Highlight.id)))).scalar() or 0
    book_count = (
        await db.execute(select(func.count(func.distinct(Highlight.book_title))))
    ).scalar() or 0
    tag_count = (await db.execute(select(func.count(Tag.id)))).scalar() or 0
    ach_count = (
        await db.execute(select(func.count(UserAchievement.id)).where(UserAchievement.user_id == 1))
    ).scalar() or 0
    streaks = await calculate_streaks(db)
    hc_key = get_hardcover_api_key()

    return render(
        request,
        "about.html",
        template_context(
            request,
            active_page="about",
            version=version,
            hl_count=hl_count,
            book_count=book_count,
            tag_count=tag_count,
            ach_count=ach_count,
            streaks=streaks,
            has_hardcover_key=bool(hc_key),
        ),
    )


@router.get("/api/debug/streak")
async def debug_streak(db: AsyncSession = Depends(get_db)):
    """Debug endpoint to inspect what the streak calculator sees."""
    from zoneinfo import ZoneInfo
    from datetime import datetime, timedelta
    from app.models import ReviewLog
    from sqlalchemy import select, func

    _CENTRAL = ZoneInfo("America/Chicago")

    # What the streak calculator sees (using full datetimes, not func.date())
    result = await db.execute(
        select(ReviewLog.reviewed_at)
        .order_by(ReviewLog.reviewed_at.desc())
        .limit(50)
    )
    rows_raw = result.all()

    utc_preview = []
    central_dates = set()
    central_with_time = []
    for row in rows_raw:
        dt = row[0]
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        utc_preview.append(dt.isoformat())
        central_dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(_CENTRAL)
        central_dates.add(central_dt.date())
        central_with_time.append(central_dt.isoformat())

    sorted_dates = sorted(central_dates, reverse=True)
    now_ct = datetime.now(_CENTRAL)
    today = now_ct.date()
    yesterday = today - timedelta(days=1)

    return {
        "streak_calculator_now": now_ct.isoformat(),
        "today_ct": str(today),
        "yesterday_ct": str(yesterday),
        "most_recent_central": str(sorted_dates[0]) if sorted_dates else None,
        "most_recent_in_range": sorted_dates[0] in (today, yesterday) if sorted_dates else False,
        "server_now_utc": datetime.utcnow().isoformat(),
        "total_central_days": len(sorted_dates),
        "utc_datetimes_preview": utc_preview[:30],
        "central_datetimes_preview": central_with_time[:30],
        "central_dates_preview": [str(d) for d in sorted_dates[:30]],
    }


@router.get("/api/debug/digest")
async def debug_digest():
    """Debug endpoint to inspect digest scheduler state."""
    from app.services.settings_service import get_all
    from datetime import datetime
    from zoneinfo import ZoneInfo

    settings = get_all()
    _CENTRAL = ZoneInfo("America/Chicago")
    now_ct = datetime.now(_CENTRAL)

    # Mask secrets
    masked = dict(settings)
    for key in ("mailjet_api_key", "mailjet_secret_key"):
        val = masked.get(key, "")
        if val and len(val) > 8:
            masked[key] = val[:4] + "..." + val[-4:]
        elif val:
            masked[key] = "***"

    return {
        "server_time_ct": now_ct.isoformat(),
        "settings": {
            k: masked.get(k)
            for k in (
                "email_digest_enabled", "mailjet_api_key", "mailjet_secret_key",
                "email_from_addr", "email_to_addr", "email_digest_time",
                "last_digest_sent_date",
            )
        },
        "scheduler_running": True,  # best-effort: if this endpoint responds, scheduler might be
    }
