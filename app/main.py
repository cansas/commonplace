"""Commonplace — Self-hosted Readwise alternative."""

from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import os

from app.database import init_db, get_db, async_session
from app.models import Highlight, Source, BookCover
from app.auth import AuthMiddleware, ensure_admin
from app.routes import highlights, review, import_routes, settings as settings_routes, books, auth as auth_routes, share as share_routes
from app.services.resurface import get_dashboard_counts
from app.services.book_covers import batch_search

app = FastAPI(title="Commonplace", version="0.4.0")

# Ensure covers directory exists on the mounted volume
COVERS_DIR = os.environ.get("COVERS_DIR", "/app/data/covers")
os.makedirs(COVERS_DIR, exist_ok=True)
# Ensure covers dir is writable by appuser
try:
    os.chmod(COVERS_DIR, 0o755)
except Exception:
    pass

# Templates
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# Static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Uploaded cover images
app.mount("/static/covers", StaticFiles(directory=COVERS_DIR), name="covers")

# Auth middleware (inner — checks session, runs after Session populates it)
app.add_middleware(AuthMiddleware)

# Session middleware (outer — runs first, populates session cookie)
secret = os.environ.get("SESSION_SECRET") or os.urandom(32).hex()
app.add_middleware(SessionMiddleware, secret_key=secret, max_age=86400 * 30)  # 30 days

# Init route modules with templates
highlights.init(templates)
review.init(templates)
import_routes.init(templates)
settings_routes.init(templates)
books.init(templates)
share_routes.init(templates)

# Include routers
app.include_router(highlights.router)
app.include_router(review.router)
app.include_router(import_routes.router)
app.include_router(settings_routes.router)
app.include_router(books.router)
app.include_router(auth_routes.router)
app.include_router(share_routes.router)

# Expose templates to auth routes
auth_routes.init(templates)


@app.on_event("startup")
async def startup():
    await init_db()
    async with async_session() as db:
        await ensure_admin(db)

    # Backfill book covers in the background (don't block startup)
    async def _backfill_covers():
        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(Highlight.book_title, Highlight.book_author)
                .distinct()
            )
            all_books = [(r.book_title, r.book_author or "") for r in result.all()]

            need_cover = []
            for title, author in all_books:
                existing = await db.execute(
                    select(BookCover).where(
                        BookCover.book_title == title,
                        BookCover.book_author == author,
                    )
                )
                if not existing.scalar_one_or_none():
                    need_cover.append((title, author))

            if need_cover:
                print(f"  Fetching covers for {len(need_cover)} books...")
                covers = await batch_search(need_cover, rate_limit=1.0)
                for (title, author), url in covers.items():
                    if url:
                        db.add(BookCover(book_title=title, book_author=author, cover_url=url, cover_source="bookcover-api"))
                await db.commit()
                found = sum(1 for url in covers.values() if url)
                print(f"  Found covers for {found} of {len(need_cover)} books")

    import asyncio
    asyncio.create_task(_backfill_covers())


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
