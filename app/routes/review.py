"""Daily review — SM-2 flash cards with daily lock and today's log."""

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text as sqltext
from app.database import get_db
from app.models import Highlight, ReviewLog
from app.services.spaced_repetition import sm2_calc, get_next_review_date
from app.routes.settings import _settings as review_settings
from app.services.streaks import calculate_streaks
from app.services.achievements import check_and_unlock
from app.csrf import template_context, csrf_guard
from app.dates import today_start_utc
from datetime import datetime
import random
import time

router = APIRouter(tags=["review"])

_jinja = None


def init(templates):
    global _jinja
    _jinja = templates


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
    """Record a review with optional SM-2 rating.
    Does NOT commit — caller is responsible for committing."""
    # Calculate SM-2 values
    ease = 2.5
    interval = 0
    reps = 0
    next_review = None

    if rating is not None:
        # Get previous review for this highlight
        prev = await db.execute(
            select(ReviewLog)
            .where(ReviewLog.highlight_id == hl_id)
            .order_by(ReviewLog.reviewed_at.desc())
            .limit(1)
        )
        prev_log = prev.scalar_one_or_none()
        if prev_log:
            ease, interval, reps = sm2_calc(
                rating, prev_log.ease_factor,
                prev_log.interval, prev_log.repetitions
            )
        else:
            ease, interval, reps = sm2_calc(rating, 2.5, 0, 0)

        if reps > 0 and interval > 0:
            next_review = get_next_review_date(interval)

    log = ReviewLog(
        highlight_id=hl_id,
        rating=rating,
        ease_factor=ease,
        interval=interval,
        repetitions=reps,
        next_review_at=next_review,
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
        })
    return rows


# ── Page routes ────────────────────────────────────────────────────────────


@router.get("/review", response_class=HTMLResponse)
async def review_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    daily_limit = review_settings.get("review_count", 10)
    done_today = await _reviewed_today_count(db)
    streaks = await calculate_streaks(db)

    # If at or over daily limit, you're done for the day
    if done_today >= daily_limit:
        today_reviews = await _get_today_reviews(db)
        return _jinja.TemplateResponse(
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
        return _jinja.TemplateResponse(
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

    return _jinja.TemplateResponse(
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
    daily_limit = review_settings.get("review_count", 10)

    return _jinja.TemplateResponse(
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
    daily_limit = review_settings.get("review_count", 10)
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
    new_achievements = await check_and_unlock(db, streaks["current"])
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
    return RedirectResponse(url="/review", status_code=303)
