"""Daily review — random highlights with daily lock and today's log."""

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text as sqltext
from app.database import get_db
from app.models import Highlight, ReviewLog
from app.services.settings_service import get_review_count
from app.services.streaks import calculate_streaks
from app.services.achievements import check_and_unlock
from app.services.review_queue import get_or_create_queue, mark_reviewed
from app.csrf import template_context, csrf_guard
from app.dates import central_now, today_start_utc
from app.template import render
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import time
from typing import Optional

router = APIRouter(tags=["review"])




def _today_start() -> datetime:
    """Start of today in Central time (America/Chicago), returned as UTC-naive."""
    return today_start_utc()


async def _reviewed_today_count(db) -> int:
    """How many highlights have been reviewed so far today (UTC)."""
    today_start = _today_start()
    result = await db.execute(
        select(func.count(ReviewLog.id))
        .where(ReviewLog.reviewed_at >= today_start)
    )
    return result.scalar() or 0


async def _log_review(db, hl_id: int, rating: int | None = None):
    """Record a review. Does NOT commit — caller is responsible for committing."""
    log = ReviewLog(
        highlight_id=hl_id,
        rating=rating,
        reviewed_at=datetime.utcnow(),
    )
    db.add(log)


async def _get_today_reviews(db):
    """Return all reviews from today with their highlight data."""
    today_start = _today_start()
    result = await db.execute(
        select(ReviewLog, Highlight)
        .join(Highlight, ReviewLog.highlight_id == Highlight.id)
        .where(ReviewLog.reviewed_at >= today_start)
        .order_by(ReviewLog.reviewed_at.desc())
    )
    rows = []
    for review, hl in result.all():
        rows.append({
            "hl_id": hl.id,
            "text": hl.text[:200],
            "book_title": hl.book_title,
            "rating": review.rating,
            "reviewed_at": review.reviewed_at,
            "share_token": hl.share_token,
        })
    return rows


# ── Page routes ────────────────────────────────────────────────────────────


@router.get("/review", response_class=HTMLResponse)
async def review_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    daily_limit = get_review_count()
    streaks = await calculate_streaks(db)
    queue = await get_or_create_queue(daily_limit)

    # Find the first not-yet-reviewed entry
    current_entry = None
    current_idx = 0
    for i, entry in enumerate(queue):
        if not entry["reviewed"]:
            current_entry = entry
            current_idx = i + 1  # 1-based
            break

    # If no unreviewed entries left, you're done
    if not current_entry:
        today_reviews = await _get_today_reviews(db)
        return render(
            request,
            "review.html",
            template_context(
                request,
                active_page="review",
                highlight=None,
                current_index=len(queue),
                total_count=daily_limit,
                done=True,
                today_reviews=today_reviews,
                streaks=streaks,
            ),
        )

    return render(
        request,
        "review.html",
        template_context(
            request,
            active_page="review",
            highlight=current_entry,
            current_index=current_idx,
            total_count=daily_limit,
            done=False,
            streaks=streaks,
        ),
    )


@router.get("/review/today", response_class=HTMLResponse)
async def review_today_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Display all reviews from today with their ratings."""
    streaks = await calculate_streaks(db)
    today_reviews = await _get_today_reviews(db)
    daily_limit = get_review_count()

    return render(
        request,
        "review_today.html",
        template_context(
            request,
            active_page="review",
            today_reviews=today_reviews,
            streaks=streaks,
            done_today=len(today_reviews),
            total_count=daily_limit,
        ),
    )


@router.get("/review/stats", response_class=HTMLResponse)
async def review_stats_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Review statistics dashboard."""
    streaks = await calculate_streaks(db)

    # Reviews per day for last 30 days (in Central time)
    _CENTRAL = ZoneInfo("America/Chicago")
    now_ct = central_now()
    thirty_days_ago_ct = now_ct - timedelta(days=30)
    thirty_days_ago_utc = thirty_days_ago_ct.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    daily = await db.execute(
        select(ReviewLog.reviewed_at)
        .where(ReviewLog.reviewed_at >= thirty_days_ago_utc)
    )
    rows = daily.all()

    # Group by Central date
    counts_by_date = {}
    for row in rows:
        dt = row[0]
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        central_date = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(_CENTRAL).date()
        counts_by_date[central_date] = counts_by_date.get(central_date, 0) + 1

    # Build day-by-day for last 30 Central days, filling gaps
    day_labels = []
    day_counts = []
    max_count = 1
    for i in range(29, -1, -1):
        d = (now_ct - timedelta(days=i)).date()
        day_labels.append(d.strftime("%a"))
        count = counts_by_date.get(d, 0)
        day_counts.append(count)
        if count > max_count:
            max_count = count

    return render(
        request,
        "review_stats.html",
        template_context(
            request,
            active_page="review",
            streaks=streaks,
            day_labels=day_labels,
            day_counts=day_counts,
            max_count=max_count,
            total_reviews=sum(day_counts),
        ),
    )


# ── Rate limiting ──────────────────────────────────────────────────────────

_REVIEW_LIMIT_ENTRIES: dict = {}
_REVIEW_MAX_PER_MIN = 30


def _check_review_rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = 60
    _REVIEW_LIMIT_ENTRIES[ip] = [t for t in _REVIEW_LIMIT_ENTRIES.get(ip, []) if now - t < window]
    if len(_REVIEW_LIMIT_ENTRIES[ip]) >= _REVIEW_MAX_PER_MIN:
        raise HTTPException(status_code=429, detail="Too many review actions. Slow down.")
    _REVIEW_LIMIT_ENTRIES[ip].append(now)


# ── Rating action ──────────────────────────────────────────────────────────

_RATING_LABELS = {0: "Forgot", 1: "Hard", 2: "Good", 3: "Easy"}


@router.get("/api/review/stats")
async def review_stats(db: AsyncSession = Depends(get_db)):
    """Return review statistics for today."""
    streaks = await calculate_streaks(db)
    done_today = await _reviewed_today_count(db)
    daily_limit = get_review_count()
    remaining = max(0, daily_limit - done_today)
    return {
        "streak": streaks["current"],
        "best_streak": streaks["best"],
        "todayReviewCount": done_today,
        "dailyLimit": daily_limit,
        "remaining": remaining,
    }


@router.get("/api/review/today")
async def api_review_today(db: AsyncSession = Depends(get_db)):
    """Return today's reviewed highlights as JSON (for review log / sharing)."""
    rows = await _get_today_reviews(db)
    return [{
        "highlight_id": r["hl_id"],
        "text": r["text"],
        "book_title": r["book_title"],
        "rating": r["rating"],
        "reviewed_at": r["reviewed_at"].isoformat() if r["reviewed_at"] else None,
    } for r in rows]


@router.post("/review/rate")
async def review_rate(
    request: Request,
    hl_id: int = Form(...),
    rating: int = Form(...),
    csrf_token: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    csrf_guard(request, csrf_token)
    _check_review_rate_limit(request)
    if rating not in (0, 1, 2, 3):
        raise HTTPException(status_code=400, detail="Invalid rating")
    await _log_review(db, hl_id, rating)
    await db.commit()
    await mark_reviewed(hl_id)

    # Check for newly unlocked achievements
    streaks = await calculate_streaks(db)
    daily_limit = get_review_count()
    review_hour = central_now().hour
    new_achievements = await check_and_unlock(db, streaks["current"], review_hour=review_hour, daily_limit=daily_limit)
    if new_achievements:
        # Store in session so the redirect can show them
        request.session["new_achievements"] = new_achievements

    return RedirectResponse(url="/review", status_code=303)


# ── Legacy actions (no rating — just log as "seen") ────────────────────────


@router.post("/review/next")
async def review_next(
    request: Request,
    hl_id: int = Form(...),
    csrf_token: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    csrf_guard(request, csrf_token)
    _check_review_rate_limit(request)
    await _log_review(db, hl_id)
    await db.commit()
    await mark_reviewed(hl_id)

    # Check for newly unlocked achievements
    streaks = await calculate_streaks(db)
    daily_limit = get_review_count()
    review_hour = central_now().hour
    new_achievements = await check_and_unlock(db, streaks["current"], review_hour=review_hour, daily_limit=daily_limit)
    if new_achievements:
        request.session["new_achievements"] = new_achievements

    return RedirectResponse(url="/review", status_code=303)


@router.post("/review/favorite")
async def review_favorite(
    request: Request,
    hl_id: int = Form(...),
    csrf_token: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    csrf_guard(request, csrf_token)
    _check_review_rate_limit(request)
    hl = await db.get(Highlight, hl_id)
    if hl:
        hl.favorite = 0 if hl.favorite else 1
    await _log_review(db, hl_id)
    await db.commit()
    await mark_reviewed(hl_id)

    streaks = await calculate_streaks(db)
    daily_limit = get_review_count()
    review_hour = central_now().hour
    new_achievements = await check_and_unlock(db, streaks["current"], review_hour=review_hour, daily_limit=daily_limit)
    if new_achievements:
        request.session["new_achievements"] = new_achievements

    return RedirectResponse(url="/review", status_code=303)


@router.post("/review/delete")
async def review_delete(
    request: Request,
    hl_id: int = Form(...),
    csrf_token: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    csrf_guard(request, csrf_token)
    _check_review_rate_limit(request)
    hl = await db.get(Highlight, hl_id)
    if hl:
        await db.delete(hl)
    await _log_review(db, hl_id)
    await db.commit()
    await mark_reviewed(hl_id)

    streaks = await calculate_streaks(db)
    daily_limit = get_review_count()
    review_hour = central_now().hour
    new_achievements = await check_and_unlock(db, streaks["current"], review_hour=review_hour, daily_limit=daily_limit)
    if new_achievements:
        request.session["new_achievements"] = new_achievements

    return RedirectResponse(url="/review", status_code=303)


# ── Review Heatmap ──────────────────────────────────────────────────────────


@router.get("/api/review/heatmap")
async def review_heatmap_data(
    year: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return daily review counts for a given year (default: this year).
    Counts are bucketed by Central timezone date.
    """
    _CENTRAL = ZoneInfo("America/Chicago")
    now_ct = central_now()
    target_year = year or now_ct.year
    # Year boundaries in Central time, converted to UTC-naive for DB
    year_start_ct = datetime(target_year, 1, 1, tzinfo=_CENTRAL)
    year_end_ct = datetime(target_year + 1, 1, 1, tzinfo=_CENTRAL)
    start_utc = year_start_ct.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    end_utc = year_end_ct.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    rows = await db.execute(
        sqltext(
            "SELECT reviewed_at FROM review_log "
            "WHERE reviewed_at >= :start AND reviewed_at < :end "
        ),
        {"start": start_utc, "end": end_utc},
    )
    # Group by Central date in Python
    counts_by_date = {}
    for row in rows.fetchall():
        dt = row[0]
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        central_date = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(_CENTRAL).date()
        counts_by_date[central_date] = counts_by_date.get(central_date, 0) + 1

    data = [{"date": d.isoformat(), "count": c} for d, c in sorted(counts_by_date.items())]
    return {"data": data, "year": target_year, "total": sum(r["count"] for r in data)}


@router.get("/review/heatmap", response_class=HTMLResponse)
async def review_heatmap_page(
    request: Request,
    year: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """GitHub-style contribution heatmap, bucketed by Central timezone date."""
    _CENTRAL = ZoneInfo("America/Chicago")
    now_ct = central_now()
    target_year = year or now_ct.year
    year_start_ct = datetime(target_year, 1, 1, tzinfo=_CENTRAL)
    year_end_ct = datetime(target_year + 1, 1, 1, tzinfo=_CENTRAL)
    start_utc = year_start_ct.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    end_utc = year_end_ct.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    rows = await db.execute(
        sqltext(
            "SELECT reviewed_at FROM review_log "
            "WHERE reviewed_at >= :start AND reviewed_at < :end "
        ),
        {"start": start_utc, "end": end_utc},
    )
    # Group by Central date
    counts_by_date = {}
    for row in rows.fetchall():
        dt = row[0]
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        central_date = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(_CENTRAL).date()
        counts_by_date[central_date] = counts_by_date.get(central_date, 0) + 1

    # Build the grid: 7 rows (Sun-Sat) × up to 53 weeks
    import calendar

    first_day = datetime(target_year, 1, 1)
    start_dow = first_day.weekday()
    start_offset = (start_dow + 1) % 7  # Shift so Sunday=0

    if target_year == now_ct.year:
        total_days = (now_ct - first_day).days + 1
    else:
        total_days = (datetime(target_year + 1, 1, 1) - first_day).days

    cells = []
    max_count = max(counts_by_date.values()) if counts_by_date else 1

    for day_offset in range(total_days):
        d = first_day + timedelta(days=day_offset)
        # Convert naive datetime to Central date for lookup
        d_ct = d.replace(tzinfo=_CENTRAL).date()
        count = counts_by_date.get(d_ct, 0)
        week = (day_offset + start_offset) // 7
        dow = (day_offset + start_offset) % 7
        level = min(4, int((count / max(1, max_count)) * 5)) if count > 0 else 0
        cells.append({
            "date": d_ct.isoformat(),
            "count": count,
            "week": week,
            "dow": dow,
            "level": level,
        })

    weeks = max(53, (cells[-1]["week"] + 1)) if cells else 53
    day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    total_reviews = sum(counts_by_date.values())
    active_days = len(counts_by_date)
    avg_per_day = round(total_reviews / max(1, active_days))
    projected_year = round(total_reviews / max(1, (now_ct - first_day).days + 1) * 365) if target_year == now_ct.year else round(total_reviews / 365 * 365)

    return render(
        request,
        "review_heatmap.html",
        template_context(
            request,
            active_page="review",
            cells=cells,
            weeks=weeks,
            year=target_year,
            total_reviews=total_reviews,
            total_days=active_days,
            avg_per_day=avg_per_day,
            projected_year=projected_year,
            day_names=day_names,
            prev_year=target_year - 1 if target_year > 2020 else None,
            next_year=target_year + 1 if target_year < now_ct.year else None,
        ),
    )


@router.get("/api/review/next")
async def api_review_next(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Return the next unreviewed highlight from today's queue as JSON."""
    daily_limit = get_review_count()
    queue = await get_or_create_queue(daily_limit)

    for entry in queue:
        if not entry["reviewed"]:
            return _review_entry_to_json(entry)

    return {"highlight_id": None, "done": True}


def _review_entry_to_json(entry: dict) -> dict:
    """Convert a queue entry to the JSON shape the iOS app expects."""
    return {
        "highlight_id": entry["id"],
        "text": entry.get("text", ""),
        "note": entry.get("note"),
        "page": entry.get("page"),
        "chapter": entry.get("chapter"),
        "book_title": entry.get("book_title", ""),
        "book_author": entry.get("book_author"),
        "source_type": entry.get("source_type", "manual"),
    }


@router.post("/api/review/rate")
async def api_review_rate(
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Rate a highlight (JSON API). Body: {\"highlight_id\": int, \"rating\": 0-3}"""
    hl_id = body.get("highlight_id")
    rating = body.get("rating")

    if not hl_id:
        raise HTTPException(status_code=400, detail="highlight_id is required")
    if rating is not None and rating not in (0, 1, 2, 3):
        raise HTTPException(status_code=400, detail="rating must be 0-3")

    _check_review_rate_limit(request)
    await _log_review(db, hl_id, rating)
    await db.commit()
    await mark_reviewed(hl_id)

    return {"ok": True, "highlight_id": hl_id, "rating": rating}
