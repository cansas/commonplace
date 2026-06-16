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
        # Highlight cards are public (for social media sharing)
        if path.startswith("/api/highlights/") and path.endswith("/card"):
            return await call_next(request)

        # API routes require token
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Token ") and auth[6:] == TOKEN:
            return await call_next(request)

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
