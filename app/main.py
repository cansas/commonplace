"""Commonplace — Self-hosted Readwise alternative."""

from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import os

from app.database import init_db, get_db
from app.models import Highlight, Source
from app.auth import AuthMiddleware
from app.routes import highlights, review, import_routes, settings as settings_routes, books
from app.services.resurface import get_dashboard_counts

app = FastAPI(title="Commonplace", version="0.1.0")

# Templates
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# Static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Auth middleware
app.add_middleware(AuthMiddleware)

# Init route modules with templates
highlights.init(templates)
review.init(templates)
import_routes.init(templates)
settings_routes.init(templates)
books.init(templates)

# Include routers
app.include_router(highlights.router)
app.include_router(review.router)
app.include_router(import_routes.router)
app.include_router(settings_routes.router)
app.include_router(books.router)


@app.on_event("startup")
async def startup():
    await init_db()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    imported: int = 0,
    db: AsyncSession = Depends(get_db),
):
    total, books, pending = await get_dashboard_counts(db)

    result = await db.execute(
        select(Source).order_by(Source.last_import_at.desc().nullslast()).limit(5)
    )
    recent_sources = result.scalars().all()

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "active_page": "dashboard",
            "total_highlights": total,
            "total_books": books,
            "today_review_count": pending,
            "recent_sources": [
                {
                    "name": s.name,
                    "source_type": s.source_type,
                    "last_import_at": s.last_import_at.strftime("%Y-%m-%d %H:%M") if s.last_import_at else "",
                    "count": s.highlights_imported or 0,
                }
                for s in recent_sources
            ],
            "imported": imported,
        },
    )
