"""Push notification delivery — VAPID config and send-to-all."""

import asyncio
import json
import os
import warnings

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import PushSubscription

try:
    from pywebpush import webpush, WebPushException
except ImportError:
    webpush = None
    WebPushException = Exception
    warnings.warn(
        "pywebpush is not installed — push notifications are disabled. "
        "Install with: pip install pywebpush"
    )

_VAPID_KEYS = None
_VAPID_CLAIMS = None

VAPID_KEYS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "data", ".vapid_keys",
)


def _validate_vapid_key(public_key: str) -> bool:
    """Check if a VAPID public key is a valid 65-byte uncompressed EC point in base64url."""
    import base64
    try:
        padding = (4 - len(public_key) % 4) % 4
        b64 = (public_key + "=" * padding).replace("-", "+").replace("_", "/")
        decoded = base64.b64decode(b64)
        return len(decoded) == 65 and decoded[0] == 4
    except Exception:
        return False


def _ensure_vapid_keys():
    """Load or generate VAPID keys, cached in module globals."""
    global _VAPID_KEYS, _VAPID_CLAIMS

    if _VAPID_KEYS is not None:
        return _VAPID_KEYS, _VAPID_CLAIMS

    # Try env vars first
    public_key = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    private_key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    claim_email = os.environ.get("VAPID_CLAIM_EMAIL", "").strip()

    if public_key and private_key and _validate_vapid_key(public_key):
        _VAPID_KEYS = {"public_key": public_key, "private_key": private_key}
    else:
        # Try persisted file
        if os.path.isfile(VAPID_KEYS_FILE):
            with open(VAPID_KEYS_FILE) as f:
                _VAPID_KEYS = json.load(f)
            # Validate the persisted key — regenerate if invalid
            if not _validate_vapid_key(_VAPID_KEYS.get("public_key", "")):
                _VAPID_KEYS = None

    # Generate if still nothing
    if not _VAPID_KEYS:
        if webpush is None:
            raise ImportError("pywebpush is not installed — cannot generate VAPID keys")
        from cryptography.hazmat.primitives import serialization
        from base64 import urlsafe_b64encode
        from pywebpush import Vapid
        v = Vapid()
        v.generate_keys()
        # Public key for browser: raw 65-byte uncompressed EC point, base64url
        pub_bytes = v.public_key.public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        # Private key for server: PEM format (what webpush() accepts)
        private_key_pem = v.private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        _VAPID_KEYS = {
            "public_key": urlsafe_b64encode(pub_bytes).decode().rstrip("="),
            "private_key": private_key_pem.strip(),
        }
        os.makedirs(os.path.dirname(VAPID_KEYS_FILE), exist_ok=True)
        with open(VAPID_KEYS_FILE, "w") as f:
            json.dump(_VAPID_KEYS, f)

    _VAPID_CLAIMS = {"sub": claim_email or "mailto:admin@commonplace.local"}
    return _VAPID_KEYS, _VAPID_CLAIMS


def _build_subscription_info(sub: PushSubscription) -> dict:
    """Build the subscription_info dict pywebpush expects."""
    return {
        "endpoint": sub.endpoint,
        "keys": {
            "p256dh": sub.p256dh_key,
            "auth": sub.auth_key,
        },
    }


def get_vapid_public_key() -> str:
    """Return the VAPID public key, loading or generating as needed."""
    keys, _ = _ensure_vapid_keys()
    return keys.get("public_key", "")


async def send_push_to_all(
    title: str,
    body: str,
    db: AsyncSession,
    url: str = "/review",
    icon: str = "/static/logo-128.png",
) -> dict:
    """Send a push notification to every active subscription.

    webpush.send() is synchronous — each call is offloaded to a thread
    via asyncio.to_thread() to avoid blocking the event loop.
    Expired subscriptions are cleaned up atomically after delivery.

    Returns a summary dict: {sent, expired, errors}.
    """
    if webpush is None:
        return {"sent": 0, "expired": 0, "errors": ["pywebpush not installed"]}

    vapid_keys, vapid_claims = _ensure_vapid_keys()

    result = await db.execute(select(PushSubscription))
    subs = result.scalars().all()

    sent = 0
    expired_subs = []
    errors = []

    payload = json.dumps({
        "title": title,
        "body": body,
        "icon": icon,
        "url": url,
    })

    for sub in subs:
        try:
            await asyncio.to_thread(
                webpush,
                subscription_info=_build_subscription_info(sub),
                data=payload,
                vapid_private_key=vapid_keys["private_key"],
                vapid_claims=vapid_claims,
            )
            sent += 1
        except WebPushException as e:
            if getattr(e, "response", None) and e.response.status_code == 410:
                expired_subs.append(sub)
            else:
                errors.append(str(e))
        except Exception as e:
            errors.append(str(e))

    # Clean up expired subscriptions — always commit if any were found
    if expired_subs:
        try:
            for sub in expired_subs:
                await db.delete(sub)
            await db.commit()
        except Exception as e:
            errors.append(f"Failed to clean up expired subscriptions: {e}")
            await db.rollback()

    return {
        "sent": sent,
        "expired": len(expired_subs),
        "errors": errors,
    }
