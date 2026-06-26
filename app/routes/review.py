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
from app.csrf import template_context, csrf_guard
from app.dates import today_start_utc
from app.template import render
from datetime import datetime, timedelta
import random
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


async def _get_unreviewed_highlight(db):
    """Pick one random highlight not yet logged in ReviewLog today."""
    today_start = _today_start()
    count_q = (
        select(func.count(Highlight.id))
        .outerjoin(
            ReviewLog,
            (ReviewLog.highlight_id == Highlight.id) &
            (ReviewLog.reviewed_at >= today_start)
        )
        .where(ReviewLog.id.is_(None))
    )
    count_result = await db.execute(count_q)
    total = count_result.scalar() or 0
    if total == 0:
        return None
    offset = random.randint(0, total - 1)
    result = await db.execute(
        select(Highlight)
        .outerjoin(
            ReviewLog,
            (ReviewLog.highlight_id == Highlight.id) &
            (ReviewLog.reviewed_at >= today_start)
        )
        .where(ReviewLog.id.is_(None))
        .offset(offset)
        .limit(1)
    )
    return result.scalar_one_or_none()


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
    done_today = await _reviewed_today_count(db)
    streaks = await calculate_streaks(db)

    # If at or over daily limit, you're done for the day
    if done_today >= daily_limit:
        today_reviews = await _get_today_reviews(db)
        return render(
            request,
            "review.html",
            template_context(
                request,
                active_page="review",
                highlight=None,
                current_index=daily_limit,
                total_count=daily_limit,
                done=True,
                today_reviews=today_reviews,
                streaks=streaks,
            ),
        )

    hl = await _get_unreviewed_highlight(db)

    if not hl:
        today_reviews = await _get_today_reviews(db)
        return render(
            request,
            "review.html",
            template_context(
                request,
                active_page="review",
                highlight=None,
                current_index=done_today,
                total_count=daily_limit,
                done=True,
                today_reviews=today_reviews,
                streaks=streaks,
            ),
        )

    highlight_data = {
        "id": hl.id,
        "text": hl.text,
        "note": hl.note,
        "page": hl.page,
        "chapter": hl.chapter,
        "book_title": hl.book_title,
        "book_author": hl.book_author,
        "source_type": hl.source_type,
        "tags": [t.name for t in hl.tags],
        "favorite": hl.favorite,
    }

    return render(
        request,
        "review.html",
        template_context(
            request,
            active_page="review",
            highlight=highlight_data,
            current_index=done_today + 1,
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

    # Reviews per day for last 30 days
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    daily = await db.execute(
        select(
            func.date(ReviewLog.reviewed_at).label("day"),
            func.count(ReviewLog.id).label("count"),
        )
        .where(ReviewLog.reviewed_at >= thirty_days_ago)
        .group_by(func.date(ReviewLog.reviewed_at))
        .order_by(func.date(ReviewLog.reviewed_at))
    )
    rows = daily.all()

    # Build day-by-day for last 30 days, filling gaps
    day_labels = []
    day_counts = []
    max_count = 1
    for i in range(29, -1, -1):
        d = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
        day_labels.append((datetime.utcnow() - timedelta(days=i)).strftime("%a"))
        match = [r for r in rows if r.day == d]
        if match:
            r = match[0]
            day_counts.append(r.count)
            if r.count > max_count:
                max_count = r.count
        else:
            day_counts.append(0)

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
        "reviewed_today": done_today,
        "daily_limit": daily_limit,
        "remaining": remaining,
    }


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

    # Check for newly unlocked achievements
    streaks = await calculate_streaks(db)
    daily_limit = get_review_count()
    review_hour = datetime.utcnow().hour
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

    # Check for newly unlocked achievements
    streaks = await calculate_streaks(db)
    daily_limit = get_review_count()
    review_hour = datetime.utcnow().hour
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

    streaks = await calculate_streaks(db)
    daily_limit = get_review_count()
    review_hour = datetime.utcnow().hour
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

    streaks = await calculate_streaks(db)
    daily_limit = get_review_count()
    review_hour = datetime.utcnow().hour
    new_achievements = await check_and_unlock(db, streaks["current"], review_hour=review_hour, daily_limit=daily_limit)
    if new_achievements:
        request.session["new_achievements"] = new_achievements

    return RedirectResponse(url="/review", status_code=303)


# ── Review Heatmap ──────────────────────────────────────────────────────────


@router.get("/api/review/heatmap")
async def review_heatmap_data(
    year: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """Return daily review counts for a given year (default: this year)."""
    now = datetime.utcnow()
    target_year = year or now.year
    start = datetime(target_year, 1, 1)
    end = datetime(target_year + 1, 1, 1) - timedelta(seconds=1)

    rows = await db.execute(
        sqltext(
            "SELECT DATE(reviewed_at) as day, COUNT(*) as cnt "
            "FROM review_log "
            "WHERE reviewed_at >= :start AND reviewed_at < :end "
            "GROUP BY DATE(reviewed_at) "
            "ORDER BY day"
        ),
        {"start": start, "end": end},
    )
    data = [{"date": r[0], "count": r[1]} for r in rows.fetchall()]
    return {"data": data, "year": target_year, "total": sum(r["count"] for r in data)}


@router.get("/review/heatmap", response_class=HTMLResponse)
async def review_heatmap_page(
    request: Request,
    year: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    now = datetime.utcnow()
    target_year = year or now.year
    start = datetime(target_year, 1, 1)
    end = datetime(target_year + 1, 1, 1) - timedelta(seconds=1)

    rows = await db.execute(
        sqltext(
            "SELECT DATE(reviewed_at) as day, COUNT(*) as cnt "
            "FROM review_log "
            "WHERE reviewed_at >= :start AND reviewed_at < :end "
            "GROUP BY DATE(reviewed_at) "
            "ORDER BY day"
        ),
        {"start": start, "end": end},
    )
    counts_by_date = {r[0]: r[1] for r in rows.fetchall()}

    # Build the grid: 7 rows (Sun-Sat) × up to 53 weeks
    import calendar

    first_day = datetime(target_year, 1, 1)
    start_dow = first_day.weekday()
    start_offset = (start_dow + 1) % 7  # Shift so Sunday=0

    if target_year == now.year:
        total_days = (now - first_day).days + 1
    else:
        total_days = (datetime(target_year + 1, 1, 1) - first_day).days

    cells = []
    max_count = max(counts_by_date.values()) if counts_by_date else 1

    for day_offset in range(total_days):
        d = first_day + timedelta(days=day_offset)
        date_str = d.strftime("%Y-%m-%d")
        count = counts_by_date.get(date_str, 0)
        week = (day_offset + start_offset) // 7
        dow = (day_offset + start_offset) % 7
        level = min(4, int((count / max(1, max_count)) * 5)) if count > 0 else 0
        cells.append({
            "date": date_str,
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
    projected_year = round(total_reviews / max(1, (now - first_day).days + 1) * 365) if target_year == now.year else round(total_reviews / 365 * 365)

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
            next_year=target_year + 1 if target_year < now.year else None,
        ),
    )
