"""Login/logout routes — username/password session auth."""
import time
from collections import defaultdict
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db, async_session
from app.models import User
from app.auth import verify_password, hash_password, ensure_admin
from app.csrf import template_context, csrf_guard, generate_csrf_token
from app.services.settings_service import get_theme
from app.template import render

router = APIRouter(tags=["auth"])

# Login rate limiting: 5 attempts per 5 minutes per IP
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW = 300  # 5 minutes in seconds
_MAX_RATE_LIMIT_ENTRIES = 10000
_login_attempts = defaultdict(list)




@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    # Redirect to setup if no admin user exists yet
    result = await db.execute(select(User).limit(1))
    if result.scalar_one_or_none() is None:
        return RedirectResponse(url="/setup", status_code=303)
    return render(request, "login.html", template_context(request, error=""))


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Rate limit check
    ip = request.client.host if request.client else "unknown"
    now = time.time()

    # Evict oldest entries if dict grows too large
    if len(_login_attempts) > _MAX_RATE_LIMIT_ENTRIES:
        _login_attempts.clear()

    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < LOGIN_WINDOW]
    if len(_login_attempts[ip]) >= LOGIN_MAX_ATTEMPTS:
        return render(
            request, "login.html",
            template_context(request, error="Too many login attempts. Try again in 5 minutes."),
        )
    
    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()

    if user and verify_password(password, user.password_hash):
        request.session["user_id"] = user.id
        request.session["username"] = user.username
        request.session["theme"] = get_theme()
        return RedirectResponse(url="/", status_code=303)

    _login_attempts[ip].append(now)
    return render(
        request, "login.html",
        template_context(request, error="Invalid username or password."),
    )


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/api/session-status")
async def session_status(request: Request):
    return {
        "authenticated": request.session.get("user_id") is not None,
        "username": request.session.get("username"),
    }


# ── First-run setup wizard ─────────────────────────────────────────────


async def _needs_setup(db: AsyncSession = None) -> bool:
    """Check if any user exists."""
    if db is None:
        async with async_session() as session:
            result = await session.execute(select(User).limit(1))
            return result.scalar_one_or_none() is None
    else:
        result = await db.execute(select(User).limit(1))
        return result.scalar_one_or_none() is None


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, db: AsyncSession = Depends(get_db)):
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    if not await _needs_setup(db):
        return RedirectResponse(url="/login", status_code=303)
    return render(request, "setup.html", template_context(request, error=""))


@router.post("/setup")
async def setup_admin(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm: str = Form(...),
    csrf_token: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    csrf_guard(request, csrf_token)

    if not await _needs_setup(db):
        return RedirectResponse(url="/login", status_code=303)

    errors = []
    username = username.strip()
    if len(username) < 2:
        errors.append("Username must be at least 2 characters.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if password != confirm:
        errors.append("Passwords do not match.")
    if errors:
        return render(
            request, "setup.html",
            template_context(request, error=" | ".join(errors)),
        )

    pwhash = hash_password(password)
    db.add(User(username=username, password_hash=pwhash))
    await db.commit()

    # Log them in immediately
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user:
        request.session["user_id"] = user.id
        request.session["username"] = user.username
        request.session["theme"] = get_theme()

    return RedirectResponse(url="/", status_code=303)
