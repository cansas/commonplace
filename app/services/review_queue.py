"""
Daily review queue — locks in a set of highlights to review each day.

Ensures the email digest and review page show the same highlights:
the first caller each day (digest at 7am or first page load) populates
the queue, and subsequent reads return the same entries in order.
"""

from datetime import date, datetime
from sqlalchemy import select, func
from app.database import async_session  # needed for digest scheduler
from app.models import Highlight, ReviewLog, DailyReviewQueue
from app.dates import today_start_utc


async def get_or_create_queue(daily_limit: int) -> list[dict]:
    """Get today's review queue, creating it from random unreviewed
    highlights if it doesn't exist yet.

    Returns a list of highlight dicts ordered by queue position.
    Each dict has keys: id, text, note, page, chapter, book_title,
    book_author, source_type, tags, favorite, share_token.
    """
    from app.dates import central_now

    today = central_now().date()

    async with async_session() as db:
        # 1. Check if queue already exists for today
        existing = await db.execute(
            select(DailyReviewQueue)
            .where(DailyReviewQueue.queue_date == today)
            .order_by(DailyReviewQueue.position)
        )
        rows = existing.scalars().all()

        if rows:
            # Queue exists — truncate if daily_limit was lowered since creation
            if len(rows) > daily_limit:
                excess = rows[daily_limit:]
                excess_ids = [r.id for r in excess]
                await db.execute(
                    DailyReviewQueue.__table__.delete()
                    .where(DailyReviewQueue.id.in_(excess_ids))
                )
                await db.commit()
                rows = rows[:daily_limit]

            # Fetch highlights and return in order
            hl_ids = [r.highlight_id for r in rows]
            hls = await db.execute(
                select(Highlight).where(Highlight.id.in_(hl_ids))
            )
            hl_map = {hl.id: hl for hl in hls.scalars().all()}
            return [
                _highlight_to_dict(hl_map[r.highlight_id], r.position, r.reviewed)
                for r in rows
                if r.highlight_id in hl_map
            ]

        # 2. No queue yet — create one from random unreviewed highlights
        today_start = today_start_utc()

        # Count unreviewed highlights
        count_q = (
            select(func.count(Highlight.id))
            .outerjoin(
                ReviewLog,
                (ReviewLog.highlight_id == Highlight.id)
                & (ReviewLog.reviewed_at >= today_start),
            )
            .where(ReviewLog.id.is_(None))
        )
        total = (await db.execute(count_q)).scalar() or 0
        limit = min(daily_limit, total)

        if limit == 0:
            await db.commit()
            return []

        # Pick random highlights
        all_ids = await db.execute(
            select(Highlight.id)
            .outerjoin(
                ReviewLog,
                (ReviewLog.highlight_id == Highlight.id)
                & (ReviewLog.reviewed_at >= today_start),
            )
            .where(ReviewLog.id.is_(None))
            .order_by(func.random())
            .limit(limit)
        )
        hl_ids = [row[0] for row in all_ids.all()]

        # Insert queue entries
        for i, hl_id in enumerate(hl_ids):
            db.add(
                DailyReviewQueue(
                    highlight_id=hl_id,
                    queue_date=today,
                    position=i + 1,
                    reviewed=False,
                )
            )

        await db.commit()

        # Re-query to get full data
        hls = await db.execute(
            select(Highlight).where(Highlight.id.in_(hl_ids))
        )
        hl_map = {hl.id: hl for hl in hls.scalars().all()}
        result = []
        for i, hl_id in enumerate(hl_ids):
            if hl_id in hl_map:
                result.append(
                    _highlight_to_dict(hl_map[hl_id], i + 1, False)
                )
        return result


async def mark_reviewed(highlight_id: int) -> None:
    """Mark the queue entry for this highlight as reviewed."""
    from app.dates import central_now

    today = central_now().date()
    async with async_session() as db:
        await db.execute(
            DailyReviewQueue.__table__.update()
            .where(
                DailyReviewQueue.queue_date == today,
                DailyReviewQueue.highlight_id == highlight_id,
            )
            .values(reviewed=True)
        )
        await db.commit()


async def get_queue_for_digest() -> list[dict]:
    """Get today's queue (max 3 entries) for the email digest.
    Creates the queue if it doesn't exist yet (first caller wins).
    """
    from app.services.settings_service import get_review_count

    return await get_or_create_queue(get_review_count())


def _highlight_to_dict(
    hl: Highlight, position: int, reviewed: bool
) -> dict:
    """Convert a Highlight ORM object + queue metadata to a dict."""
    return {
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
        "share_token": hl.share_token,
        "position": position,
        "reviewed": reviewed,
    }
