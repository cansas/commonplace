"""Login/logout routes — username/password session auth."""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User
from app.auth import verify_password

router = APIRouter(tags=["auth"])

_jinja = None


def init(templates):
    global _jinja
    _jinja = templates


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    return _jinja.TemplateResponse(request, "login.html", {"error": ""})


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()

    if user and verify_password(password, user.password_hash):
        request.session["user_id"] = user.id
        request.session["username"] = user.username
        return RedirectResponse(url="/", status_code=303)

    return _jinja.TemplateResponse(
        request, "login.html",
        {"error": "Invalid username or password."},
    )


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/api/session-status")
async def session_status(request: Request):
    return {
        "authenticated": request.session.get("user_id") is not None,
        "username": request.session.get("username"),
    }
