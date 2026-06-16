"""Login/logout routes for session-based web UI auth."""

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from app.auth import get_token

router = APIRouter(tags=["auth"])

_jinja = None


def init(templates):
    global _jinja
    _jinja = templates


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # If already authenticated, redirect to dashboard
    if request.session.get("authenticated"):
        return RedirectResponse(url="/", status_code=303)
    return _jinja.TemplateResponse(request, "login.html", {"error": ""})


@router.post("/login")
async def login(request: Request, token: str = Form(...)):
    stored = get_token()
    if token == stored:
        request.session["authenticated"] = True
        return RedirectResponse(url="/", status_code=303)
    return _jinja.TemplateResponse(
        request, "login.html",
        {"error": "Invalid token. Check your Commonplace Settings page."},
    )


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/api/session-status")
async def session_status(request: Request):
    return {"authenticated": request.session.get("authenticated", False)}
