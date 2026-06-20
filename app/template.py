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

CSRF token and user theme are injected automatically (via setdefault
so explicit template_context() calls are not overwritten).
"""

import os

from fastapi.templating import Jinja2Templates
from app.csrf import generate_csrf_token

_templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


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
    return _templates.TemplateResponse(request, template_name, ctx, **kwargs)
