"""Settings page routes + API token management."""
from fastapi import APIRouter, Depends, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from app.database import get_db
from app.models import Highlight, Source, User, ApiToken
from app.auth import generate_api_token, hash_password, verify_password
from app.routes.share import get_share_token

router = APIRouter(tags=["settings"])

_jinja = None

# In-memory settings (no DB for preferences yet)
_settings = {"review_mode": "random", "review_count": 10}


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
        {
            "active_page": "settings",
            "tokens": tokens,
            "total_highlights": total,
            "total_books": books,
            "review_mode": _settings.get("review_mode", "random"),
            "review_count": _settings.get("review_count", 10),
            "version": "0.4.0",
            "saved": saved,
            "new_token": new_token,
            "username": request.session.get("username", ""),
        },
    )


@router.post("/settings/review-mode")
async def set_review_mode(spaced_mode: str = Form(default="")):
    _settings["review_mode"] = "spaced" if spaced_mode == "1" else "random"
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/settings/review-count")
async def set_review_count(count: int = Form(default=10)):
    _settings["review_count"] = max(5, min(30, count))
    return RedirectResponse(url="/settings?saved=1", status_code=303)


# ── Password change ───────────────────────────────────────────────────────


@router.post("/settings/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if not verify_password(current_password, user.password_hash):
        return RedirectResponse(url="/settings?error=wrong-password", status_code=303)

    if len(new_password) < 4:
        return RedirectResponse(url="/settings?error=weak-password", status_code=303)

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
    token_name: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
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

    return RedirectResponse(
        url=f"/settings?new_token={plaintext}",
        status_code=303,
    )


@router.post("/settings/revoke-token/{token_id}")
async def revoke_token_form(
    request: Request,
    token_id: int,
    db: AsyncSession = Depends(get_db),
):
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
    confirm: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
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
