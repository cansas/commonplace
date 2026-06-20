"""Settings page routes + API token management."""
import json
import os
from fastapi import APIRouter, Depends, Request, Form, HTTPException, status, Header
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from app.database import get_db
from app.models import Highlight, Source, User, ApiToken
from app.auth import generate_api_token, hash_password, verify_password
from app.routes.share import get_share_token
from app.csrf import template_context, csrf_guard

router = APIRouter(tags=["settings"])

_jinja = None

_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", ".settings.json")
_settings = {"review_mode": "random", "review_count": 10, "theme": "modern"}
_last_mtime: float = 0.0


def _ensure_fresh():
    """Reload _settings from disk if the file's mtime has changed.

    Allows external edits to .settings.json to take effect without a
    server restart. Checks are cheap (one stat() call) when the file
    hasn't changed.
    """
    global _settings, _last_mtime
    try:
        current = os.path.getmtime(_SETTINGS_FILE)
        if current > _last_mtime:
            with open(_SETTINGS_FILE) as f:
                _settings = json.load(f)
            _last_mtime = current
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def get_theme() -> str:
    """Return the persisted theme preference ('modern' or 'reader')."""
    _ensure_fresh()
    return _settings.get("theme", "modern")


def get_hardcover_api_key() -> str:
    """Return the persisted Hardcover API key, or empty string."""
    _ensure_fresh()
    return _settings.get("hardcover_api_key", "")


def set_hardcover_api_key(value: str) -> None:
    """Persist a Hardcover API key (empty string to clear)."""
    _settings["hardcover_api_key"] = value
    _save_settings()


def get_settings() -> dict:
    """Return the full settings dict (read-only snapshot)."""
    _ensure_fresh()
    return dict(_settings)


def set_setting(key: str, value) -> None:
    """Set a single setting key and persist."""
    _settings[key] = value
    _save_settings()


def _load_settings():
    global _settings, _last_mtime
    try:
        if os.path.isfile(_SETTINGS_FILE):
            with open(_SETTINGS_FILE) as f:
                _settings = json.load(f)
            _last_mtime = os.path.getmtime(_SETTINGS_FILE)
    except Exception:
        pass


def _save_settings():
    global _last_mtime
    try:
        os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
        with open(_SETTINGS_FILE, "w") as f:
            json.dump(_settings, f)
        _last_mtime = os.path.getmtime(_SETTINGS_FILE)
    except Exception:
        pass


_load_settings()


def init(templates):
    global _jinja
    _jinja = templates


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    saved: str = "",
    new_token: str = "",
):
    _ensure_fresh()
    # Read new_token from session (more secure than URL param)
    if not new_token:
        new_token = request.session.pop("new_token", "")
    
    result = await db.execute(select(func.count(Highlight.id)))
    total = result.scalar() or 0

    result = await db.execute(select(func.count(func.distinct(Highlight.book_title))))
    books = result.scalar() or 0

    # Fetch API tokens for display
    user_id = request.session.get("user_id")
    tokens = []
    if user_id:
        result = await db.execute(
            select(ApiToken).where(ApiToken.user_id == user_id)
            .order_by(ApiToken.created_at.desc())
        )
        tokens = result.scalars().all()

    return _jinja.TemplateResponse(
        request,
        "settings.html",
        template_context(
            request,
            active_page="settings",
            tokens=tokens,
            total_highlights=total,
            total_books=books,
            review_count=_settings.get("review_count", 10),
            version="0.8.13",
            saved=saved,
            new_token=new_token,
            username=request.session.get("username", ""),
            hardcover_key=get_hardcover_api_key(),
            email_config={
                "mailjet_api_key": _settings.get("mailjet_api_key", ""),
                "mailjet_secret_key": _settings.get("mailjet_secret_key", ""),
                "email_from_name": _settings.get("email_from_name", "Commonplace"),
                "email_from_addr": _settings.get("email_from_addr", ""),
                "email_to_addr": _settings.get("email_to_addr", ""),
                "email_digest_enabled": _settings.get("email_digest_enabled", False),
                "email_digest_time": _settings.get("email_digest_time", "07:00"),
                "base_url": _settings.get("base_url", ""),
            },
        ),
    )


@router.post("/settings/review-count")
async def set_review_count(
    request: Request,
    csrf_token: str = Form(default=""),
    count: int = Form(default=10),
):
    csrf_guard(request, csrf_token)
    _settings["review_count"] = max(5, min(30, count))
    _save_settings()
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/settings/theme")
async def set_theme(
    request: Request,
    csrf_token: str = Form(default=""),
    theme: str = Form(default="modern"),
):
    csrf_guard(request, csrf_token)
    theme = theme.strip().lower()
    if theme not in ("modern", "reader", "dark"):
        theme = "modern"
    _settings["theme"] = theme
    _save_settings()
    request.session["theme"] = theme
    return {"ok": True, "theme": theme}


@router.post("/settings/cover-source")
async def set_cover_source(
    request: Request,
    csrf_token: str = Form(default=""),
    hardcover_key: str = Form(default=""),
    action: str = Form(default="set"),
):
    csrf_guard(request, csrf_token)
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    if action == "clear":
        set_hardcover_api_key("")
        return {"ok": True, "message": "Hardcover API key removed"}

    # Validate the key looks plausible
    key = hardcover_key.strip()
    if key and len(key) < 4:
        raise HTTPException(status_code=400, detail="Key too short")
    if len(key) > 2048:
        raise HTTPException(status_code=400, detail="Key too long")

    set_hardcover_api_key(key)

    # Test the connection if a key was provided
    if key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                test_resp = await client.post(
                    "https://api.hardcover.app/v1/graphql",
                    json={"query": "{ me { id } }"},
                    headers={"Authorization": f"Bearer {key}"},
                )
            if test_resp.status_code == 200:
                return {"ok": True, "connected": True, "message": "Key saved and verified"}
            else:
                return {"ok": True, "connected": False, "message": "Key saved but connection test failed"}
        except Exception:
            return {"ok": True, "connected": False, "message": "Key saved but could not reach Hardcover API"}

    return {"ok": True, "connected": False, "message": "Key cleared"}


# ── Password change ───────────────────────────────────────────────────────


@router.post("/settings/change-password")
async def change_password(
    request: Request,
    csrf_token: str = Form(default=""),
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    csrf_guard(request, csrf_token)
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if not verify_password(current_password, user.password_hash):
        return RedirectResponse(url="/settings?error=wrong-password", status_code=303)

    if len(new_password) < 8:
        return RedirectResponse(url="/settings?error=weak-password", status_code=303)

    if new_password != confirm_password:
        return RedirectResponse(url="/settings?error=mismatch", status_code=303)

    user.password_hash = hash_password(new_password)
    await db.commit()

    return RedirectResponse(url="/settings?saved=1", status_code=303)


# ── Token management API ──────────────────────────────────────────────────


@router.get("/api/tokens")
async def list_tokens(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List device tokens (prefix only, no secrets)."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    result = await db.execute(
        select(ApiToken).where(ApiToken.user_id == user_id)
        .order_by(ApiToken.created_at.desc())
    )
    tokens = result.scalars().all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "prefix": t.token_prefix,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        }
        for t in tokens
    ]


@router.post("/api/tokens")
async def create_token(
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Create a new named device token. Returns plaintext exactly once."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Token name is required")
    if len(name) > 128:
        raise HTTPException(status_code=400, detail="Token name too long")

    plaintext, token_hash, token_prefix = generate_api_token(name)
    tok = ApiToken(
        user_id=user_id,
        name=name,
        token_hash=token_hash,
        token_prefix=token_prefix,
    )
    db.add(tok)
    await db.commit()

    return {"name": name, "prefix": token_prefix, "token": plaintext}


@router.delete("/api/tokens/{token_id}")
async def revoke_token(
    request: Request,
    token_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Revoke (delete) a device token."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    result = await db.execute(
        select(ApiToken).where(
            ApiToken.id == token_id,
            ApiToken.user_id == user_id,
        )
    )
    tok = result.scalar_one_or_none()
    if not tok:
        raise HTTPException(status_code=404, detail="Token not found")

    await db.delete(tok)
    await db.commit()
    return {"ok": True}


@router.post("/settings/create-token")
async def create_token_form(
    request: Request,
    csrf_token: str = Form(default=""),
    token_name: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    csrf_guard(request, csrf_token)
    """Create a token from the settings page form."""
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    name = token_name.strip()
    if not name:
        return RedirectResponse(url="/settings?error=Name+required", status_code=303)

    plaintext, token_hash, token_prefix = generate_api_token(name)
    tok = ApiToken(
        user_id=user_id,
        name=name,
        token_hash=token_hash,
        token_prefix=token_prefix,
    )
    db.add(tok)
    await db.commit()

    request.session["new_token"] = plaintext
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/settings/revoke-token/{token_id}")
async def revoke_token_form(
    request: Request,
    token_id: int,
    csrf_token: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    csrf_guard(request, csrf_token)
    """Revoke a token from the settings page form."""
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    result = await db.execute(
        select(ApiToken).where(
            ApiToken.id == token_id,
            ApiToken.user_id == user_id,
        )
    )
    tok = result.scalar_one_or_none()
    if tok:
        await db.delete(tok)
        await db.commit()

    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/settings/reset")
async def reset_database(
    request: Request,
    csrf_token: str = Form(default=""),
    confirm: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    csrf_guard(request, csrf_token)
    """Delete all highlights and review history. Requires typing 'reset'."""
    if confirm.strip().lower() != "reset":
        return RedirectResponse(url="/settings?error=Type+%22reset%22+to+confirm", status_code=303)

    from app.models import Highlight, ReviewLog, Source, Tag, highlight_tags
    await db.execute(highlight_tags.delete())
    await db.execute(ReviewLog.__table__.delete())
    await db.execute(Highlight.__table__.delete())
    await db.execute(Tag.__table__.delete())
    await db.execute(Source.__table__.delete())
    await db.commit()
    return RedirectResponse(url="/", status_code=303)


# ── Email Settings ─────────────────────────────────────────────────────────


@router.post("/api/digest/trigger")
async def trigger_digest(
    request: Request,
    x_digest_secret: str = Header(default=""),
):
    """Trigger a digest check on-demand (for external cron)."""
    expected = os.environ.get("DIGEST_SECRET", "")
    if expected and x_digest_secret != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid digest secret")

    from app.services.digest_scheduler import check_and_send_digest
    await check_and_send_digest()
    return {"ok": True}


@router.post("/api/settings/email")
async def save_email_settings(
    request: Request,
    body: dict,
):
    """Save email/Mailjet configuration."""
    from app.services.email_digest import save_email_config

    allowed = {
        "mailjet_api_key", "mailjet_secret_key", "email_from_name",
        "email_from_addr", "email_to_addr", "email_digest_enabled",
        "email_digest_time", "base_url",
    }
    config = {k: v for k, v in body.items() if k in allowed}
    save_email_config(config)
    return {"ok": True}


@router.post("/api/settings/email/test")
async def send_test_email(
    request: Request,
    body: dict,
):
    """Send a test email using current Mailjet config."""
    from app.services.email_digest import send_test_email as _send_test

    _ensure_fresh()
    api_key = body.get("mailjet_api_key") or _settings.get("mailjet_api_key", "")
    secret_key = body.get("mailjet_secret_key") or _settings.get("mailjet_secret_key", "")
    from_name = body.get("email_from_name") or _settings.get("email_from_name", "Commonplace")
    from_email = body.get("email_from_addr") or _settings.get("email_from_addr", "")
    to_email = body.get("email_to_addr") or _settings.get("email_to_addr", "")

    if not api_key or not secret_key:
        raise HTTPException(status_code=400, detail="Mailjet API key and secret key are required")
    if not from_email or not to_email:
        raise HTTPException(status_code=400, detail="From and To email addresses are required")

    try:
        result = await _send_test(api_key, secret_key, from_name, from_email, to_email)
        return {"ok": True, "message": "Test email sent successfully"}
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
