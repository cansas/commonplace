"""Push notification subscription routes."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.database import get_db
from app.models import PushSubscription

router = APIRouter(prefix="/api/push", tags=["push"])


@router.post("/subscribe")
async def subscribe(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Register a browser push subscription."""
    body = await request.json()
    endpoint = body.get("endpoint", "").strip()
    keys = body.get("keys", {}) or {}
    user_id = request.session.get("user_id")

    if not user_id:
        return {"ok": False, "error": "Not authenticated"}

    if not endpoint:
        return {"ok": False, "error": "Missing endpoint"}
    if not keys.get("p256dh"):
        return {"ok": False, "error": "Missing keys.p256dh"}
    if not keys.get("auth"):
        return {"ok": False, "error": "Missing keys.auth"}

    # Upsert: replace existing subscription with same endpoint
    existing = await db.execute(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )
    sub = existing.scalar_one_or_none()
    if sub:
        sub.p256dh_key = keys["p256dh"]
        sub.auth_key = keys["auth"]
        sub.user_id = user_id
    else:
        sub = PushSubscription(
            endpoint=endpoint,
            p256dh_key=keys["p256dh"],
            auth_key=keys["auth"],
            user_id=user_id,
        )
        db.add(sub)

    await db.commit()
    return {"ok": True}


@router.delete("/subscribe")
async def unsubscribe(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Remove a browser push subscription for the current user."""
    body = await request.json()
    endpoint = body.get("endpoint", "").strip()
    user_id = request.session.get("user_id")

    if not endpoint:
        return {"ok": False, "error": "Missing endpoint"}
    if not user_id:
        return {"ok": False, "error": "Not authenticated"}

    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == endpoint,
            PushSubscription.user_id == user_id,
        )
    )
    await db.commit()
    return {"ok": True}
