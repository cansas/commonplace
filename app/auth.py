"""
Auth overhaul — three-layer auth: username/password web login, per-device API tokens,
independent session secret. See commonplace Hardening Prompt.md for the full spec.
"""
import hashlib
import os
import secrets
from datetime import datetime

import bcrypt
from fastapi import Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import User, ApiToken


# ── Password hashing ──────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


# ── API token generation ──────────────────────────────────────────────────

def _token_abbrev(name: str) -> str:
    """Short abbreviation from a device name, e.g. 'koreader' -> 'kr'."""
    words = name.replace("-", " ").replace("_", " ").split()
    if len(words) >= 2:
        return "".join(w[0] for w in words[:2]).lower()[:4]
    return name[:4].lower()


def generate_api_token(name: str) -> tuple[str, str, str]:
    """
    Create a new API token.

    Returns (plaintext_token, token_hash, token_prefix).
    The plaintext is shown exactly once; only the hash is stored.
    """
    abbrev = _token_abbrev(name)
    random_part = secrets.token_hex(16)  # 32 hex chars
    plaintext = f"cp_{abbrev}_{random_part}"
    token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    token_prefix = plaintext[:14] + "..."
    return plaintext, token_hash, token_prefix


async def verify_api_token(token: str, db: AsyncSession) -> ApiToken | None:
    """Look up a raw API token by its SHA256 hash."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    result = await db.execute(
        select(ApiToken).where(ApiToken.token_hash == token_hash)
    )
    return result.scalar_one_or_none()


# ── First-run admin creation ──────────────────────────────────────────────

async def ensure_admin(db: AsyncSession):
    """Create the admin user on first run from env vars or setup wizard."""
    result = await db.execute(select(User).limit(1))
    if result.scalar_one_or_none() is not None:
        return  # Already has a user

    username = os.environ.get("COMMONPLACE_USERNAME")
    password = os.environ.get("COMMONPLACE_PASSWORD")
    if not username or not password:
        return  # No env vars — setup wizard will handle first-run creation

    pwhash = hash_password(password)
    db.add(User(username=username, password_hash=pwhash))
    await db.commit()


# ── Middleware ─────────────────────────────────────────────────────────────

PUBLIC_PATHS = {"/login", "/health", "/setup"}


def _path_parts(path: str) -> list[str]:
    return [p for p in path.split("/") if p]


class AuthMiddleware:
    """
    Three-layer auth as ASGI middleware (not BaseHTTPMiddleware) to ensure
    session data set by route handlers propagates correctly through the
    outer SessionMiddleware. BaseHTTPMiddleware has known scope-isolation
    issues in Starlette 0.40+ that can silently drop session mutations.

      - Public paths (login, health, static) — always allowed.
      - API paths (/api/*) — verified via Authorization: Token <tok>
        against the ApiToken table. A few sub-paths (share cards,
        individual highlight items) are public.
      - Web paths — session must have 'user_id'.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        path = request.url.path
        parts = _path_parts(path)

        # ── Public paths ──────────────────────────────────────────────
        if path in PUBLIC_PATHS or path.startswith("/static"):
            await self.app(scope, receive, send)
            return

        # ── Share cards (public) ──────────────────────────────────────
        if len(parts) >= 2 and parts[0] == "share":
            await self.app(scope, receive, send)
            return

        # ── API routes ────────────────────────────────────────────────
        if parts and parts[0] == "api":
            # Highlight item routes (for share-card redirects) — public
            if (
                len(parts) >= 3
                and parts[1] == "highlights"
                and parts[2].isdigit()
            ):
                await self.app(scope, receive, send)
                return

            # Allow API calls from logged-in web sessions (no token needed)
            if request.session.get("user_id"):
                await self.app(scope, receive, send)
                return

            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Token "):
                response = JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Missing or malformed Authorization header"},
                    headers={"content-type": "application/json"},
                )
                await response(scope, receive, send)
                return

            raw_token = auth[6:]
            async with async_session() as db:
                tok = await verify_api_token(raw_token, db)
                if tok is None:
                    response = JSONResponse(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        content={"detail": "Invalid token"},
                        headers={"content-type": "application/json"},
                    )
                    await response(scope, receive, send)
                    return
                # Stamp last_used_at
                await db.execute(
                    update(ApiToken)
                    .where(ApiToken.id == tok.id)
                    .values(last_used_at=datetime.utcnow())
                )
                await db.commit()

            await self.app(scope, receive, send)
            return

        # ── Web UI routes ─────────────────────────────────────────────
        if request.session.get("user_id"):
            await self.app(scope, receive, send)
            return

        response = RedirectResponse(url="/login", status_code=303)
        await response(scope, receive, send)
