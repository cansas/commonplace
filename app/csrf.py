"""CSRF protection using double-submit cookie pattern.

Token is signed with itsdangerous and stored in a cookie on GET requests.
On POST requests, the middleware compares the cookie value with a form field
or header value without consuming the request body.
"""
import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired


_signer = None

CSRF_EXEMPT_PATHS = {"/login", "/health"}
CSRF_EXEMPT_PREFIXES = ("/static", "/share", "/api/", "/logout", "/health")
CSRF_COOKIE_NAME = "csrf_token"


def _get_signer():
    global _signer
    if _signer is None:
        secret = os.environ.get("SESSION_SECRET")
        if not secret:
            secret_file = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "data", ".session_secret",
            )
            if os.path.isfile(secret_file):
                secret = open(secret_file).read().strip()
            else:
                secret = "fallback-csrf-secret"
        _signer = URLSafeTimedSerializer(secret, salt="csrf-token")
    return _signer


def generate_csrf_token(session: dict) -> str:
    user_id = session.get("user_id", "")
    return _get_signer().dumps(str(user_id))


def verify_csrf_token(token: str, session: dict) -> bool:
    try:
        data = _get_signer().loads(token, max_age=86400)
        return str(session.get("user_id", "")) == data
    except (BadSignature, SignatureExpired):
        return False


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # On GET requests, set a signed CSRF cookie
        if request.method in ("GET", "HEAD", "OPTIONS"):
            token = generate_csrf_token(request.session)
            response.set_cookie(
                CSRF_COOKIE_NAME,
                token,
                httponly=True,
                samesite="lax",
                max_age=86400,
                path="/",
            )

        return response


def verify_csrf_request(request: Request) -> str | None:
    """Verify CSRF on state-changing requests. Returns error message or None if OK.

    Should be called from route handlers (not middleware) because the form
    body is parsed by FastAPI before this runs.
    """
    path = request.url.path
    for prefix in CSRF_EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return None
    if path in CSRF_EXEMPT_PATHS:
        return None

    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not cookie_token:
        return "Missing CSRF cookie"

    # Try header first (used by JS fetch)
    header_token = request.headers.get("x-csrf-token")
    if header_token:
        if not verify_csrf_token(header_token, request.session):
            return "Invalid CSRF token"
        if header_token != cookie_token:
            return "CSRF token mismatch"
        return None

    return "Missing CSRF token — use X-CSRF-Token header or csrf_token form field"


def template_context(request: Request, **kwargs) -> dict:
    """Build a template context dict with csrf_token and user_theme."""
    ctx = dict(kwargs)
    if request.session.get("user_id"):
        ctx["csrf_token"] = generate_csrf_token(request.session)
    else:
        ctx["csrf_token"] = ""
    # User theme preference (loaded from settings file on login, cached in session)
    ctx["user_theme"] = request.session.get("theme", "modern")
    return ctx


def csrf_guard(request: Request, csrf_token: str = "") -> None:
    """FastAPI dependency: raises 403 if CSRF token is invalid.

    Usage: add ``csrf_token: str = Form(default="")`` to the handler
    and ``Depends(csrf_guard)`` to the route's dependencies.
    """
    path = request.url.path
    for prefix in CSRF_EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return
    if path in CSRF_EXEMPT_PATHS:
        return

    if not csrf_token:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CSRF token")

    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not cookie_token or csrf_token != cookie_token or not verify_csrf_token(csrf_token, request.session):
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Sets security-related response headers for defense-in-depth."""

    HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "same-origin",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline' fonts.googleapis.com cdn.tailwindcss.com; "
            "font-src 'self' fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        ),
    }

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for name, value in self.HEADERS.items():
            response.headers[name] = value
        return response
