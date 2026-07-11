"""Settings page routes + API token management.

Settings storage has moved to app.services.settings_service.
This module re-exports convenience functions for backward compat
and provides the web routes that configure them.
"""
from fastapi import APIRouter, Depends, Request, Form, HTTPException, status, Header
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from app.database import get_db
from app.models import Highlight, Source, User, ApiToken
from app.auth import generate_api_token, hash_password, verify_password
from app.routes.share import get_share_token
from app.csrf import template_context, csrf_guard
from app.services.settings_service import (
    get as _get,
    set as _set,
    get_all,
    set_setting,
    get_review_count,
    get_theme,
    set_theme as _set_theme,
    get_hardcover_api_key,
    set_hardcover_api_key,
    get_email_config,
    save_email_config,
)
from app.template import render
from io import BytesIO
import base64
import qrcode

router = APIRouter(tags=["settings"])


def generate_qr_data_url(base_url: str, token: str) -> str:
    """Return a base64 data URI of a QR code PNG encoding the deep-link URL.

    The QR encodes `commonplace://setup?server=<base_url>&token=<token>`
    so the iOS Camera app can open it via the custom URL scheme.
    """
    qr_data = f"commonplace://setup?server={base_url}&token={token}"
    img = qrcode.make(qr_data, box_size=10)
    buf = BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"




@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    saved: str = "",
    new_token: str = "",
):
    # Read new_token from session (more secure than URL param)
    if not new_token:
        new_token = request.session.pop("new_token", "")
    new_token_qr = request.session.pop("new_token_qr", "")
    
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

    # BookOrbit sync config
    from app.services.bookorbit_sync import get_sync_config
    bookorbit_config = get_sync_config()

    return render(
        request,
        "settings.html",
        template_context(
            request,
            active_page="settings",
            tokens=tokens,
            total_highlights=total,
            total_books=books,
            review_count=get_review_count(),
            saved=saved,
            new_token=new_token,
            new_token_qr=new_token_qr,
            username=request.session.get("username", ""),
            hardcover_key=get_hardcover_api_key(),
            email_config=get_email_config(),
            bookorbit_config=bookorbit_config,
        ),
    )


def get_bookorbit_config() -> dict:
    from app.services.bookorbit_sync import get_sync_config
    return get_sync_config()


# ── BookOrbit Sync Settings ────────────────────────────────────────────────


@router.post("/api/settings/bookorbit-sync")
async def save_bookorbit_sync_settings(
    request: Request,
    body: dict,
):
    """Save BookOrbit sync configuration."""
    from app.services.settings_service import set as _set

    allowed = {"bookorbit_url", "bookorbit_username", "bookorbit_password",
               "bookorbit_sync_enabled"}
    for k in allowed:
        if k in body:
            _set(k, body[k])
    # Clear any previous disabled reason when saving new settings
    if "bookorbit_password" in body or "bookorbit_sync_enabled" in body:
        _set("bookorbit_disabled_reason", "")
    return {"ok": True}


@router.post("/api/settings/bookorbit-test")
async def test_bookorbit_connection(
    request: Request,
    body: dict,
):
    """Test BookOrbit connection."""
    from app.services.bookorbit_sync import test_connection

    url = body.get("bookorbit_url", "").strip()
    username = body.get("bookorbit_username", "").strip()
    password = body.get("bookorbit_password", "").strip()

    # Fall back to stored values for fields not provided
    if not url:
        url = _get("bookorbit_url", "")
    if not username:
        username = _get("bookorbit_username", "")
    if not password:
        password = _get("bookorbit_password", "")

    result = await test_connection(url, username, password)
    return result


@router.post("/api/settings/bookorbit-sync-now")
async def trigger_bookorbit_sync(
    request: Request,
):
    """Manually trigger a BookOrbit sync."""
    from app.services.bookorbit_sync import sync_from_bookorbit

    result = await sync_from_bookorbit()
    return {"ok": True, "result": result}


# ── Password change ────────────────────────────────────────────────────────


@router.post("/settings/review-count")
async def set_review_count(
    request: Request,
    csrf_token: str = Form(default=""),
    count: int = Form(default=10),
):
    csrf_guard(request, csrf_token)
    n = max(5, min(30, count))
    _set("review_count", n)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/settings/theme")
async def set_theme(
    request: Request,
    csrf_token: str = Form(default=""),
    theme: str = Form(default="modern"),
):
    csrf_guard(request, csrf_token)
    _set_theme(theme)
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

    # Generate QR data URL for mobile setup
    base_url = str(request.base_url).rstrip("/")
    qr_data_url = generate_qr_data_url(base_url, plaintext)

    return {"name": name, "prefix": token_prefix, "token": plaintext, "qr_data_url": qr_data_url}


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

    # Generate QR data URL for mobile setup
    base_url = str(request.base_url).rstrip("/")
    request.session["new_token_qr"] = generate_qr_data_url(base_url, plaintext)

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


# ── Deduplicate highlights ────────────────────────────────────────────────


@router.post("/api/settings/dedup")
async def dedup_highlights(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Find and merge duplicate highlights by (text, book_title, book_author)."""
    from sqlalchemy import text as sqltext
    import logging
    logger = logging.getLogger(__name__)

    try:
        rows = await db.execute(sqltext(
            "SELECT text, book_title, book_author, COUNT(*) as cnt "
            "FROM highlights "
            "GROUP BY text, book_title, book_author "
            "HAVING COUNT(*) > 1 "
            "ORDER BY cnt DESC"
        ))
        dup_groups = rows.mappings().all()

        merged = 0
        removed = 0
        for group in dup_groups:
            dup_rows = await db.execute(
                sqltext(
                    "SELECT id FROM highlights "
                    "WHERE text = :text AND book_title = :bt "
                    "AND (book_author = :ba OR (book_author IS NULL AND :ba = '')) "
                    "ORDER BY id ASC"
                ),
                {"text": group["text"], "bt": group["book_title"], "ba": group["book_author"] or ""},
            )
            ids = [r[0] for r in dup_rows.fetchall()]
            keep_id = ids[0]
            del_ids = ids[1:]

            for did in del_ids:
                await db.execute(
                    sqltext(
                        "INSERT OR IGNORE INTO highlight_tags (highlight_id, tag_id) "
                        "SELECT :keep, tag_id FROM highlight_tags WHERE highlight_id = :del"
                    ),
                    {"keep": keep_id, "del": did},
                )
            for did in del_ids:
                await db.execute(
                    sqltext("UPDATE review_log SET highlight_id = :keep WHERE highlight_id = :del"),
                    {"keep": keep_id, "del": did},
                )
            for did in del_ids:
                await db.execute(
                    sqltext("DELETE FROM highlight_tags WHERE highlight_id = :id"),
                    {"id": did},
                )
                await db.execute(
                    sqltext("DELETE FROM highlights WHERE id = :id"),
                    {"id": did},
                )

            merged += 1
            removed += len(del_ids)

        await db.commit()

        if removed > 0:
            await db.execute(sqltext("DELETE FROM highlights_fts"))
            await db.execute(sqltext(
                "INSERT INTO highlights_fts(rowid, text, note, book_title, book_author) "
                "SELECT id, text, note, book_title, book_author FROM highlights"
            ))
            await db.commit()

        return {"ok": True, "groups_merged": merged, "duplicates_removed": removed}

    except Exception as e:
        logger.exception("Dedup failed")
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ── Email Settings ─────────────────────────────────────────────────────────


@router.post("/api/digest/trigger")
async def trigger_digest(
    request: Request,
    x_digest_secret: str = Header(default=""),
):
    """Trigger a digest check on-demand (for external cron)."""
    from os import environ as _environ
    expected = _environ.get("DIGEST_SECRET", "")
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
    config = {k: v for k, v in body.items()
              if k in ("mailjet_api_key", "mailjet_secret_key", "email_from_name",
                       "email_from_addr", "email_to_addr", "email_digest_enabled",
                       "email_digest_time", "base_url")}
    save_email_config(config)
    return {"ok": True}


@router.post("/api/settings/email/test")
async def send_test_email(
    request: Request,
    body: dict,
):
    """Send a test email using current Mailjet config."""
    from app.services.email_digest import send_test_email as _send_test
    from os import environ

    api_key = body.get("mailjet_api_key") or _get("mailjet_api_key", "")
    secret_key = body.get("mailjet_secret_key") or _get("mailjet_secret_key", "")
    from_name = body.get("email_from_name") or _get("email_from_name", "Commonplace")
    from_email = body.get("email_from_addr") or _get("email_from_addr", "")
    to_email = body.get("email_to_addr") or _get("email_to_addr", "")

    if not api_key or not secret_key:
        raise HTTPException(status_code=400, detail="Mailjet API key and secret key are required")
    if not from_email or not to_email:
        raise HTTPException(status_code=400, detail="From and To email addresses are required")

    try:
        result = await _send_test(api_key, secret_key, from_name, from_email, to_email)
        return {"ok": True, "message": "Test email sent successfully"}
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
