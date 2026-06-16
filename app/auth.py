import os
import secrets
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware

TOKEN = os.environ.get("MARGINALIA_TOKEN", "change-me")


def get_token() -> str:
    return TOKEN


def regenerate_token() -> str:
    global TOKEN
    TOKEN = secrets.token_urlsafe(32)
    return TOKEN


class AuthMiddleware(BaseHTTPMiddleware):
    """Token auth for API routes. Web UI pages are exempt (listed in DISPATCH)."""

    DISPATCH = {"/", "/books", "/highlights", "/review", "/import", "/settings", 
                 "/settings/reset", "/settings/review-mode", "/settings/review-count",
                 "/health"}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Web UI pages and health check are public
        if path in self.DISPATCH or path.startswith("/static"):
            return await call_next(request)
        # Highlight cards, edits, and favorites are public (for web UI + sharing)
        # Paths with a highlight ID (3+ segments like /api/highlights/42) bypass auth
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "highlights" and parts[2].isdigit():
            return await call_next(request)

        # API routes require token
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Token ") and auth[6:] == TOKEN:
            return await call_next(request)

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
