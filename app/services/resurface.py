"""Daily resurface logic — selects highlights for today's review session."""
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models import Highlight, ReviewLog
from app.routes.settings import _settings as review_settings
from app.dates import today_start_utc


async def get_random_highlights(db: AsyncSession, count: int = 10, exclude_ids: list = None):
    """Random selection for simple daily review mode."""
    query = select(Highlight).order_by(func.random()).limit(count)
    if exclude_ids:
        query = query.where(Highlight.id.notin_(exclude_ids))
    result = await db.execute(query)
    return result.scalars().all()


async def get_due_highlights(db: AsyncSession, count: int = 10):
    """SM-2 mode: highlights due for review today."""
    now = datetime.utcnow()
    query = (
        select(Highlight)
        .outerjoin(ReviewLog)
        .group_by(Highlight.id)
        .having(
            func.max(ReviewLog.next_review_at).is_(None) |
            (func.max(ReviewLog.next_review_at) <= now)
        )
        .order_by(func.random())
        .limit(count)
    )
    result = await db.execute(query)
    return result.scalars().all()


async def get_dashboard_counts(db: AsyncSession):
    """Return stats for the dashboard."""
    # Total highlights
    result = await db.execute(select(func.count(Highlight.id)))
    total = result.scalar() or 0

    # Distinct books
    result = await db.execute(select(func.count(func.distinct(Highlight.book_title))))
    books = result.scalar() or 0

    # Reviews done today
    today_start = today_start_utc()
    result = await db.execute(
        select(func.count(ReviewLog.id))
        .where(ReviewLog.reviewed_at >= today_start)
    )
    done_today = result.scalar() or 0

    # Daily remaining = min(limit - done, total_unreviewed)
    daily_limit = review_settings.get("review_count", 10)
    remaining = max(0, daily_limit - done_today)

    return total, books, remaining


async def get_recent_sources(db: AsyncSession, limit: int = 5):
    """Recent import sources."""
    from app.models import Source
    result = await db.execute(
        select(Source)
        .order_by(Source.last_import_at.desc().nullslast())
        .limit(limit)
    )
    return result.scalars().all()
