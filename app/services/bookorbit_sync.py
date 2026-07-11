"""
BookOrbit → Commonplace sync engine.

Imports annotations (kobo, koreader, web) from a BookOrbit server
into Commonplace's local database using SHA256 fingerprint dedup
and watermark tracking.
"""

import logging
from datetime import datetime
from typing import Any

import httpx

from app.services.import_service import highlight_fingerprint
from app.services.settings_service import get as _get, set as _set

logger = logging.getLogger(__name__)

# Mapping from BookOrbit origin to Commonplace source_type
ORIGIN_SOURCE_TYPE = {
    "kobo": "kobo",
    "koreader": "koreader",
    "web": "web",
}

# Settings keys
_BOOKORBIT_URL = "bookorbit_url"
_BOOKORBIT_USERNAME = "bookorbit_username"
_BOOKORBIT_PASSWORD = "bookorbit_password"
_BOOKORBIT_SYNC_ENABLED = "bookorbit_sync_enabled"
_BOOKORBIT_LAST_ID = "bookorbit_last_synced_id"
_BOOKORBIT_LAST_AT = "bookorbit_last_synced_at"
_BOOKORBIT_DISABLED_REASON = "bookorbit_disabled_reason"

_PAGE_SIZE = 100
_LOGIN_TIMEOUT = 15
_ANNOTATION_TIMEOUT = 30


# ── Settings helpers ────────────────────────────────────────────────────────

def get_sync_config() -> dict:
    return {
        "url": _get(_BOOKORBIT_URL, ""),
        "username": _get(_BOOKORBIT_USERNAME, ""),
        "password": _get(_BOOKORBIT_PASSWORD, ""),
        "enabled": _get(_BOOKORBIT_SYNC_ENABLED, False),
        "last_synced_id": _get(_BOOKORBIT_LAST_ID, 0),
        "last_synced_at": _get(_BOOKORBIT_LAST_AT, ""),
        "disabled_reason": _get(_BOOKORBIT_DISABLED_REASON, ""),
    }


def save_sync_config(config: dict) -> None:
    allowed = {
        _BOOKORBIT_URL, _BOOKORBIT_USERNAME, _BOOKORBIT_PASSWORD,
        _BOOKORBIT_SYNC_ENABLED, _BOOKORBIT_DISABLED_REASON,
    }
    for k in allowed:
        if k in config:
            _set(k, config[k])


# ── HTTP helpers ────────────────────────────────────────────────────────────


async def _json_request(
    client: httpx.AsyncClient,
    url: str,
    method: str = "GET",
    json_data: dict | None = None,
    headers: dict | None = None,
) -> tuple[int, Any]:
    """Thin wrapper returning (status, parsed_body)."""
    try:
        resp = await client.request(
            method, url, json=json_data, headers=headers,
        )
        body = resp.json() if resp.text else {}
        return resp.status_code, body
    except httpx.TimeoutException:
        return 0, {"error": "Request timed out"}
    except httpx.RequestError as e:
        return 0, {"error": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}


# ── Public API ──────────────────────────────────────────────────────────────

async def test_connection(url: str, username: str, password: str) -> dict:
    """Test BookOrbit login credentials.

    Returns ``{"ok": True}`` on success, or ``{"ok": False, "error": "..."}``.
    """
    if not url or not username or not password:
        return {"ok": False, "error": "URL, username, and password are required"}

    clean_url = url.rstrip("/")
    async with httpx.AsyncClient(timeout=_LOGIN_TIMEOUT) as client:
        status, body = await _json_request(
            client,
            f"{clean_url}/api/v1/auth/login",
            method="POST",
            json_data={"username": username, "password": password},
        )
    if status == 200:
        return {"ok": True}
    msg = body.get("message") or body.get("error") or f"HTTP {status}"
    return {"ok": False, "error": msg}


async def sync_from_bookorbit() -> dict:
    """Run a full sync pass. Returns stats dict.

    Returns:
        ``{"posted": N, "skipped": N, "errors": N, "last_id": M}``
    """
    config = get_sync_config()
    if not config["enabled"]:
        return {"posted": 0, "skipped": 0, "errors": 0, "last_id": config["last_synced_id"]}
    if not config["url"] or not config["username"] or not config["password"]:
        return {"posted": 0, "skipped": 0, "errors": 0, "last_id": config["last_synced_id"]}

    clean_url = config["url"].rstrip("/")
    watermark = config["last_synced_id"]

    # We'll build an in-memory set of existing fingerprints to avoid DB queries per-item.
    # Importing lazily to avoid circular imports at module level.
    from app.database import async_session
    from sqlalchemy import select, text as sqltext

    async with httpx.AsyncClient(timeout=_ANNOTATION_TIMEOUT) as client:
        # ── 1. Login ────────────────────────────────────────────────────
        status, body = await _json_request(
            client,
            f"{clean_url}/api/v1/auth/login",
            method="POST",
            json_data={"username": config["username"], "password": config["password"]},
        )
        if status != 200:
            msg = body.get("message") or body.get("error") or f"HTTP {status}"
            logger.warning("BookOrbit login failed: %s", msg)
            _set(_BOOKORBIT_DISABLED_REASON, f"login_failed: {msg}")
            return {"posted": 0, "skipped": 0, "errors": 0, "last_id": watermark}

        # Successful login clears any previous disabled reason
        _set(_BOOKORBIT_DISABLED_REASON, "")

        # ── 2. Fetch annotations (all origins) ─────────────────────────
        all_annotations = []
        page = 1
        while True:
            url = (
                f"{clean_url}/api/v1/annotations"
                f"?status=active&sortBy=createdAt&sortDir=asc"
                f"&page={page}&pageSize={_PAGE_SIZE}"
            )
            status, body = await _json_request(client, url)
            if status != 200:
                logger.warning("BookOrbit annotations fetch failed (page=%d): %s", page, body)
                break

            items = body.get("items", [])
            if not items:
                break
            all_annotations.extend(items)

            total = body.get("total", 0)
            if page * _PAGE_SIZE >= total:
                break
            page += 1

    # ── 3. Build existing fingerprint set ───────────────────────────────
    posted = 0
    skipped = 0
    errors = 0
    max_id = watermark

    async with async_session() as db:
        # Fetch all existing fingerprints in one query
        result = await db.execute(
            sqltext("SELECT fingerprint FROM highlights WHERE fingerprint IS NOT NULL")
        )
        existing_fingerprints = {row[0] for row in result.fetchall()}

        # Also build existing source_id set for exact-match dedup
        result = await db.execute(
            sqltext("SELECT source_id FROM highlights WHERE source_id LIKE 'bookorbit:%'")
        )
        existing_source_ids = {row[0] for row in result.fetchall()}

        for ann in all_annotations:
            ann_id = int(ann["id"])
            if ann_id <= watermark:
                continue  # Already past this watermark

            # Check source_id exact match first
            source_id = f"bookorbit:{ann_id}"
            if source_id in existing_source_ids:
                if ann_id > max_id:
                    max_id = ann_id
                skipped += 1
                continue

            text = (ann.get("text") or "").strip()
            if not text:
                skipped += 1
                continue

            book_title = ann.get("bookTitle") or "Untitled"
            book_author = ann.get("author") or ""
            fp = highlight_fingerprint(text, book_title, book_author)

            # Check fingerprint
            if fp in existing_fingerprints:
                if ann_id > max_id:
                    max_id = ann_id
                skipped += 1
                continue

            # ── 4. Import ──────────────────────────────────────────────
            origin = ann.get("origin", "kobo")
            source_type = ORIGIN_SOURCE_TYPE.get(origin, origin)

            try:
                highlighted_at = None
                if ann.get("createdAt"):
                    try:
                        highlighted_at = datetime.fromisoformat(ann["createdAt"].replace("Z", "+00:00"))
                    except (ValueError, AttributeError):
                        pass

                stmt = sqltext("""
                    INSERT INTO highlights
                        (text, note, page, chapter, source_type, source_id,
                         book_title, book_author, color, category, favorite,
                         highlighted_at, created_at, share_token, fingerprint)
                    VALUES
                        (:text, :note, :page, :chapter, :source_type, :source_id,
                         :book_title, :book_author, :color, :category, 0,
                         :highlighted_at, :created_at, :share_token, :fingerprint)
                """)

                import secrets
                await db.execute(stmt, {
                    "text": text,
                    "note": ann.get("note") or None,
                    "page": None,  # BookOrbit doesn't expose page numbers directly
                    "chapter": ann.get("chapterTitle") or None,
                    "source_type": source_type,
                    "source_id": source_id,
                    "book_title": book_title,
                    "book_author": book_author,
                    "color": ann.get("color") or None,
                    "category": "books",
                    "highlighted_at": highlighted_at,
                    "created_at": datetime.utcnow(),
                    "share_token": secrets.token_urlsafe(16),
                    "fingerprint": fp,
                })

                await db.commit()
                posted += 1
                existing_fingerprints.add(fp)
                existing_source_ids.add(source_id)
                if ann_id > max_id:
                    max_id = ann_id

            except Exception as e:
                await db.rollback()
                errors += 1
                logger.warning("Failed to import BookOrbit annotation %d: %s", ann_id, e)

    # ── 5. Save watermark ───────────────────────────────────────────────
    if posted > 0 or max_id > watermark:
        _set(_BOOKORBIT_LAST_ID, max_id)
        _set(_BOOKORBIT_LAST_AT, datetime.utcnow().isoformat())

    logger.info(
        "BookOrbit sync complete: posted=%d skipped=%d errors=%d last_id=%d",
        posted, skipped, errors, max_id,
    )
    return {"posted": posted, "skipped": skipped, "errors": errors, "last_id": max_id}
