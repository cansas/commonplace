"""Centralized template rendering.

Replaces the ``_jinja = None`` + ``init(templates)`` pattern
that was duplicated across 11 route modules. Every route now
imports ``render`` from here instead.

Usage::

    from app.template import render

    return await render(request, "page.html", {
        "active_page": "dashboard",
        "total_highlights": total,
    })

CSRF token, user theme, and VAPID public key are injected automatically
(via setdefault so explicit template_context() calls are not overwritten).
"""

import os

from fastapi.templating import Jinja2Templates
from app.csrf import generate_csrf_token
from app.services.theme_service import discover_custom_themes, get_all_themes

_templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# Lazy-load VAPID public key — only imported when render() is first called
_vapid_public_key = None

def _get_vapid_public_key() -> str:
    global _vapid_public_key
    if _vapid_public_key is not None:
        return _vapid_public_key
    try:
        from app.services.push_service import get_vapid_public_key
        _vapid_public_key = get_vapid_public_key() or ""
    except Exception:
        _vapid_public_key = ""
    return _vapid_public_key


def render(request, template_name: str, context: dict = None, **kwargs):
    """Render a Jinja2 template with CSRF token and theme auto-injected.

    Args:
        request: FastAPI Request.
        template_name: Path to template relative to app/templates/.
        context: Dict of template variables. CSRF token and user theme
                 are added automatically if not already present.
        **kwargs: Extra keyword args forwarded to TemplateResponse
                  (e.g. ``status_code=404``).

    Returns:
        Starlette ``TemplateResponse``.
    """
    ctx = dict(context or {})
    ctx.setdefault("csrf_token", getattr(request.state, "csrf_token", None) or generate_csrf_token(request.session))
    ctx.setdefault("user_theme", request.session.get("theme", "modern"))
    # Version string for cache-busting (?v=) on static assets and the SW URL.
    # Without this, a browser can keep running last release's commonplace.js.
    ctx.setdefault("app_version", getattr(request.app, "version", "") or "")
    ctx.setdefault("vapid_public_key", _get_vapid_public_key())
    ctx.setdefault("custom_themes", discover_custom_themes())
    ctx.setdefault("all_themes", get_all_themes())
    return _templates.TemplateResponse(request, template_name, ctx, **kwargs)
