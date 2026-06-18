"""Daily review — flash-card style. Respects daily limit from settings."""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import Highlight, ReviewLog
from app.services.resurface import get_random_highlights
from app.routes.settings import _settings as review_settings
from datetime import datetime

router = APIRouter(tags=["review"])

_jinja = None


def init(templates):
    global _jinja
    _jinja = templates


def _today_start() -> datetime:
    """Start of today (midnight UTC)."""
    return datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


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
    reviewed_today = (
        select(ReviewLog.highlight_id)
        .where(ReviewLog.reviewed_at >= today_start)
    )
    result = await db.execute(
        select(Highlight)
        .where(Highlight.id.notin_(reviewed_today))
        .order_by(func.random())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _log_review(db, hl_id: int):
    """Record that a highlight was reviewed (seen) right now.
    Does NOT commit — caller is responsible for committing."""
    log = ReviewLog(
        highlight_id=hl_id,
        rating=None,  # no SM-2 rating in flash-card mode
        reviewed_at=datetime.utcnow(),
    )
    db.add(log)


@router.get("/review", response_class=HTMLResponse)
async def review_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    daily_limit = review_settings.get("review_count", 10)
    done_today = await _reviewed_today_count(db)

    # If at or over daily limit, you're done for the day
    if done_today >= daily_limit:
        return _jinja.TemplateResponse(
            request,
            "review.html",
            {
                "active_page": "review",
                "highlight": None,
                "current_index": daily_limit,
                "total_count": daily_limit,
            },
        )

    hl = await _get_unreviewed_highlight(db)

    if not hl:
        # All highlights have been reviewed — done for the day
        return _jinja.TemplateResponse(
            request,
            "review.html",
            {
                "active_page": "review",
                "highlight": None,
                "current_index": done_today,
                "total_count": daily_limit,
            },
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
        {
            "active_page": "review",
            "highlight": highlight_data,
            "current_index": done_today + 1,
            "total_count": daily_limit,
        },
    )


# ── Actions — each one logs the review and advances ──────────────────────


@router.post("/review/next")
async def review_next(
    hl_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    await _log_review(db, hl_id)
    await db.commit()
    return RedirectResponse(url="/review", status_code=303)


@router.post("/review/favorite")
async def review_favorite(
    hl_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    hl = await db.get(Highlight, hl_id)
    if hl:
        hl.favorite = 0 if hl.favorite else 1
    await _log_review(db, hl_id)
    await db.commit()
    return RedirectResponse(url="/review", status_code=303)


@router.post("/review/delete")
async def review_delete(
    hl_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    hl = await db.get(Highlight, hl_id)
    if hl:
        await db.delete(hl)
    await _log_review(db, hl_id)
    await db.commit()
    return RedirectResponse(url="/review", status_code=303)


from sqlalchemy import select, func
