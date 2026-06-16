import os
import secrets
from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

TOKEN = os.environ.get("MARGINALIA_TOKEN", "change-me")


def get_token() -> str:
    return TOKEN


def regenerate_token() -> str:
    global TOKEN
    TOKEN = secrets.token_urlsafe(32)
    return TOKEN


class AuthMiddleware(BaseHTTPMiddleware):
    """Session auth for web UI, token auth for API."""

    # Paths accessible without any auth
    PUBLIC = {"/login", "/health"}

    API_PREFIXES = ("/api/",)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Static files, login, health — always public
        if path in self.PUBLIC or path.startswith("/static"):
            return await call_next(request)

        # Share cards and highlight item routes — public
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "highlights" and parts[2].isdigit():
            return await call_next(request)

        # API routes — check Authorization header
        if parts and parts[0] == "api":
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Token ") and auth[6:] == TOKEN:
                return await call_next(request)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        # Web UI pages — check session cookie
        if request.session.get("authenticated"):
            return await call_next(request)

        # Not authenticated — redirect to login
        return RedirectResponse(url="/login", status_code=303)
