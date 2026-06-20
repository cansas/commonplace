"""Achievements page routes."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.achievements import get_all_achievements, _get_achievement
from app.services.achievement_card import generate_achievement_card
from app.csrf import template_context
from app.template import render

router = APIRouter(tags=["achievements"])




@router.get("/api/achievements")
async def api_achievements(db: AsyncSession = Depends(get_db)):
    """Return all achievements with unlock status."""
    return await get_all_achievements(db)


@router.get("/achievements", response_class=HTMLResponse)
async def achievements_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Achievements display page."""
    achievements = await get_all_achievements(db)
    unlocked_count = sum(1 for a in achievements if a["unlocked"])

    # Check for new achievements from session
    new_achievements = request.session.pop("new_achievements", [])

    return render(
        request,
        "achievements.html",
        template_context(
            request,
            active_page="achievements",
            achievements=achievements,
            unlocked_count=unlocked_count,
            total_count=len(achievements),
            new_achievements=new_achievements,
        ),
    )


@router.get("/api/achievements/{key}/card")
async def achievement_card(key: str):
    """Return an SVG share card for an achievement definition."""
    achievement = _get_achievement(key)
    if achievement is None:
        return JSONResponse(status_code=404, content={"error": "Achievement not found"})

    svg = generate_achievement_card(
        label=achievement["label"],
        message=achievement["message"],
        icon=achievement["icon"],
    )
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )
