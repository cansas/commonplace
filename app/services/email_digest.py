"""
Mailjet email digest service.

Sends daily review emails via Mailjet's REST API (free tier: 6k/mo, 200/day).
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

MAILJET_API = "https://api.mailjet.com/v3.1/send"

# ── Settings helpers (avoid circular import) ────────────────────────────────

_SETTINGS_FILE = None


def _get_settings():
    """Lazy-load email settings from .settings.json."""
    global _SETTINGS_FILE
    if _SETTINGS_FILE is None:
        import os
        _SETTINGS_FILE = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", ".settings.json"
        )
    try:
        with open(_SETTINGS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_settings(settings: dict):
    try:
        import os
        os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
        with open(_SETTINGS_FILE, "w") as f:
            json.dump(settings, f)
    except Exception as e:
        logger.warning("Failed to save email settings: %s", e)


def get_email_config() -> dict:
    s = _get_settings()
    return {
        "mailjet_api_key": s.get("mailjet_api_key", ""),
        "mailjet_secret_key": s.get("mailjet_secret_key", ""),
        "email_from_name": s.get("email_from_name", "Commonplace"),
        "email_from_addr": s.get("email_from_addr", ""),
        "email_to_addr": s.get("email_to_addr", ""),
        "email_digest_enabled": s.get("email_digest_enabled", False),
        "email_digest_time": s.get("email_digest_time", "07:00"),
    }


def save_email_config(config: dict):
    s = _get_settings()
    for key in ("mailjet_api_key", "mailjet_secret_key", "email_from_name",
                 "email_from_addr", "email_to_addr", "email_digest_enabled",
                 "email_digest_time"):
        if key in config:
            s[key] = config[key]
    _save_settings(s)


# ── Low-level Mailjet API ──────────────────────────────────────────────────


async def send_email_via_mailjet(
    api_key: str,
    secret_key: str,
    from_name: str,
    from_email: str,
    to_email: str,
    subject: str,
    html_content: str,
) -> dict:
    """Send a single email via Mailjet REST API. Returns response JSON."""
    payload = {
        "Messages": [
            {
                "From": {"Name": from_name, "Email": from_email},
                "To": [{"Email": to_email}],
                "Subject": subject,
                "HTMLPart": html_content,
            }
        ]
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            MAILJET_API,
            auth=(api_key, secret_key),
            json=payload,
        )
    result = resp.json()
    if resp.status_code != 200:
        error_detail = result.get("ErrorMessage", result.get("error", str(result)))
        raise RuntimeError(f"Mailjet error ({resp.status_code}): {error_detail}")
    return result


# ── Digest builder ─────────────────────────────────────────────────────────


async def build_digest_html(db) -> str:
    """Query highlights due for review and build an HTML email body.

    Falls back to random picks if no SM-2 scheduling data exists.
    """
    from sqlalchemy import select, func, text as sqltext
    from app.models import Highlight, ReviewLog

    # Try SM-2: highlights with next_review_at <= now, order by oldest
    now = datetime.utcnow()
    rows = await db.execute(
        select(Highlight)
        .outerjoin(ReviewLog, ReviewLog.highlight_id == Highlight.id)
        .where(
            (ReviewLog.next_review_at <= now) | (ReviewLog.next_review_at.is_(None))
        )
        .order_by(ReviewLog.next_review_at.asc().nullsfirst())
        .limit(5)
    )
    highlights = list(dict.fromkeys(r[0] for r in rows))  # deduplicate by id

    # If fewer than 2 SM-2 due, supplement with random
    if len(highlights) < 2:
        needed = 3 - len(highlights)
        existing_ids = [h.id for h in highlights]
        extra = await db.execute(
            sqltext(
                "SELECT * FROM highlights ORDER BY RANDOM() LIMIT :lim"
            ),
            {"lim": needed},
        )
        cols = [m[0] for m in extra.cursor.description] if extra.cursor else []
        for row in extra.fetchall():
            # Try mapping to ORM or skip
            pass
        # Simpler: random ids we haven't seen
        random_hls = await db.execute(
            select(Highlight)
            .where(Highlight.id.notin_(existing_ids) if existing_ids else True)
            .order_by(func.random())
            .limit(needed)
        )
        highlights.extend(random_hls.scalars().all())

    if not highlights:
        return "<p>No highlights to review today. Import some highlights to get started!</p>"

    items_html = ""
    for hl in highlights[:3]:
        text = hl.text or ""
        note = hl.note or ""
        items_html += f"""
        <div style="margin-bottom:24px;padding:16px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;">
            <p style="margin:0 0 4px;font-size:14px;line-height:1.6;color:#1e293b;font-style:italic;">{_escape_html(text)}</p>
            <div style="margin-top:8px;font-size:12px;color:#64748b;">
                <span>📖 {_escape_html(hl.book_title or "")}</span>
                {f'<span style="margin:0 4px;">·</span><span>✍️ {_escape_html(hl.book_author or "")}</span>' if hl.book_author else ''}
            </div>
        </div>
        """

    return f"""
    <div style="max-width:560px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
        <div style="text-align:center;padding:24px 0 16px;">
            <h1 style="font-size:20px;font-weight:700;color:#1e293b;margin:0;">📖 Your Daily Review</h1>
            <p style="font-size:14px;color:#64748b;margin:6px 0 0;">Highlights to reinforce today</p>
        </div>
        {items_html}
        <div style="text-align:center;padding:16px 0 24px;">
            <a href="{_get_base_url()}/review"
               style="display:inline-block;padding:12px 28px;background:#6366f1;color:#fff;font-size:14px;font-weight:600;border-radius:8px;text-decoration:none;">
                📝 Start Review Session
            </a>
        </div>
        <div style="text-align:center;padding:12px 0;font-size:11px;color:#94a3b8;border-top:1px solid #e2e8f0;">
            <p style="margin:0 0 4px;">Commonplace — self-hosted highlights</p>
            <p style="margin:0;">
                <a href="{_get_base_url()}/settings?tab=email" style="color:#94a3b8;text-decoration:underline;">Unsubscribe</a>
                · or disable in Settings
            </p>
        </div>
    </div>
    """


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _get_base_url() -> str:
    """Return the base URL from settings, or a sensible default."""
    s = _get_settings()
    return s.get("base_url", "http://localhost:8765")


# ── Send test email ────────────────────────────────────────────────────────


async def send_test_email(api_key: str, secret_key: str, from_name: str, from_email: str, to_email: str) -> dict:
    """Send a simple test email to verify Mailjet config."""
    html = """
    <div style="max-width:560px;margin:0 auto;font-family:sans-serif;padding:32px 0;text-align:center;">
        <h1 style="font-size:24px;color:#1e293b;">✅ Test Email</h1>
        <p style="font-size:14px;color:#64748b;">Your Mailjet configuration is working!</p>
        <p style="font-size:12px;color:#94a3b8;">Sent from Commonplace</p>
    </div>
    """
    return await send_email_via_mailjet(
        api_key, secret_key, from_name, from_email, to_email,
        "Commonplace — Test Email", html,
    )
