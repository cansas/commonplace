"""commonplace — Self-hosted Readwise alternative."""

from datetime import datetime
from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import asyncio
import os
import random

from app.database import init_db, get_db, async_session
from app.models import Highlight, Source, BookCover
from app.auth import AuthMiddleware, ensure_admin
from app.csrf import CSRFMiddleware, generate_csrf_token, template_context, SecurityHeadersMiddleware
from app.routes import highlights, review, import_routes, settings as settings_routes, books, auth as auth_routes, share as share_routes, backup as backup_routes, tags as tags_routes
from app.services.resurface import get_dashboard_counts
from app.services.book_covers import batch_search
from app.services.streaks import calculate_streaks
from app.routes.settings import get_hardcover_api_key

app = FastAPI(title="commonplace", version="0.6.7")

# Ensure covers directory exists on the mounted volume
COVERS_DIR = os.environ.get("COVERS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "covers"))
os.makedirs(COVERS_DIR, exist_ok=True)
# Ensure covers dir is writable by appuser
try:
    os.chmod(COVERS_DIR, 0o755)
except Exception:
    pass

# Templates
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# Uploaded cover images — mount BEFORE /static so covers take priority
app.mount("/static/covers", StaticFiles(directory=COVERS_DIR), name="covers")

# Static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# Session secret — use env var if set, otherwise generate and persist
def _get_or_create_session_secret() -> str:
    env_secret = os.environ.get("SESSION_SECRET")
    if env_secret:
        return env_secret
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    secret_file = os.path.join(data_dir, ".session_secret")
    if os.path.isfile(secret_file):
        return open(secret_file).read().strip()
    secret = os.urandom(32).hex()
    os.makedirs(data_dir, exist_ok=True)
    with open(secret_file, "w") as f:
        f.write(secret)
    os.chmod(secret_file, 0o600)
    print("  WARNING: SESSION_SECRET not set — generated a persistent secret in data/.session_secret")
    print("           Set SESSION_SECRET env var for production deployments.")
    return secret


secret = _get_or_create_session_secret()

# Auth middleware (inner — checks session, runs after Session populates it)
app.add_middleware(AuthMiddleware)

# CSRF middleware — sets CSRF cookie on GET, runs after session is available
app.add_middleware(CSRFMiddleware)

# Security headers
app.add_middleware(SecurityHeadersMiddleware)

# Session middleware (outer — runs first, populates session cookie)
_session_https = os.environ.get("SESSION_HTTPS_ONLY", "false").lower() == "true"
app.add_middleware(SessionMiddleware, secret_key=secret, max_age=86400 * 30, same_site="lax", https_only=_session_https)

# Init route modules with templates
highlights.init(templates)
review.init(templates)
import_routes.init(templates)
settings_routes.init(templates)
books.init(templates)
share_routes.init(templates)
backup_routes.init(templates)
tags_routes.init(templates)

# Include routers
app.include_router(highlights.router)
app.include_router(review.router)
app.include_router(import_routes.router)
app.include_router(settings_routes.router)
app.include_router(books.router)
app.include_router(auth_routes.router)
app.include_router(share_routes.router)
app.include_router(backup_routes.router)
app.include_router(tags_routes.router)

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
            result = await db.execute(
                select(Highlight.book_title, Highlight.book_author)
                .distinct()
            )
            all_books = [(r.book_title, r.book_author or "") for r in result.all()]

            # Bulk check existing covers — one query, not N
            existing_result = await db.execute(
                select(BookCover.book_title, BookCover.book_author)
            )
            existing_covers = {
                (r.book_title, r.book_author) for r in existing_result.all()
            }

            need_cover = [
                (t, a) for t, a in all_books if (t, a) not in existing_covers
            ]

            if need_cover:
                print(f"  Fetching covers for {len(need_cover)} books...")
                hc_key = get_hardcover_api_key()
                covers = await batch_search(need_cover, rate_limit=1.0, hardcover_key=hc_key)
                for (title, author), (url, source) in covers.items():
                    if url:
                        db.add(BookCover(book_title=title, book_author=author, cover_url=url, cover_source=source))
                await db.commit()
                found = sum(1 for url, _ in covers.values() if url)
                print(f"  Found covers for {found} of {len(need_cover)} books")

    asyncio.create_task(_backfill_covers())


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """Healthcheck — verifies DB connectivity and returns app status.

    Returns 200 with version and database status on success.
    Returns 503 if the database is unreachable (triggers Docker restart).
    """
    db_ok = False
    try:
        from sqlalchemy import text as sqltext
        await db.execute(sqltext("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    result = {
        "status": "ok" if db_ok else "degraded",
        "version": "0.6.7",
        "database": "connected" if db_ok else "unreachable",
    }

    if not db_ok:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=result)

    return result


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    imported: int = 0,
    db: AsyncSession = Depends(get_db),
):
    total, books, pending = await get_dashboard_counts(db)

    # Random highlight — use random offset instead of ORDER BY random() for efficiency
    random_hl = None
    if total > 0:
        offset = random.randint(0, total - 1)
        random_hl_result = await db.execute(
            select(Highlight).offset(offset).limit(1)
        )
        random_hl = random_hl_result.scalar_one_or_none()

    today_str = datetime.now().strftime("%A, %B %-d, %Y")

    # Streak tracking
    streak = await calculate_streaks(db)

    return templates.TemplateResponse(
        request,
        "index.html",
        template_context(
            request,
            active_page="dashboard",
            total_highlights=total,
            total_books=books,
            today_review_count=pending,
            today_date=today_str,
            streak=streak,
            random_highlight={
                "id": random_hl.id,
                "text": random_hl.text,
                "book_title": random_hl.book_title,
                "book_author": random_hl.book_author or "",
                "note": random_hl.note,
                "share_token": random_hl.share_token,
            } if random_hl else None,
            imported=imported,
        ),
    )
