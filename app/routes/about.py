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

router = APIRouter(tags=["about"])

_jinja = None


def init(templates):
    global _jinja
    _jinja = templates


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

    return _jinja.TemplateResponse(
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
