"""
Readeck → Commonplace sync engine.

Imports annotations from a self-hosted Readeck server (read-it-later)
into Commonplace's local database using SHA256 fingerprint dedup and
source_id tracking.

Readeck API (v0.22.x):
  GET /api/bookmarks?limit=&offset=&sort=     list bookmarks
  GET /api/bookmarks/{id}/annotations         list annotations per bookmark
  Auth: Authorization: Bearer <API token>     (token from Readeck profile)
"""

import asyncio
import logging
import secrets
from datetime import datetime
from typing import Any

import httpx

from app.services.import_service import highlight_fingerprint
from app.services.settings_service import get as _get, set as _set

logger = logging.getLogger(__name__)

# Settings keys
_READECK_URL = "readeck_url"
_READECK_API_TOKEN = "readeck_api_token"
_READECK_SYNC_ENABLED = "readeck_sync_enabled"
_READECK_LAST_SYNCED_AT = "readeck_last_synced_at"
_READECK_LAST_COUNT = "readeck_last_imported_count"
_READECK_DISABLED_REASON = "readeck_disabled_reason"

_PAGE_SIZE = 100
_TIMEOUT = 30
_FETCH_CONCURRENCY = 5  # parallel annotation fetches per sync pass


# ── Settings helpers ────────────────────────────────────────────────────────

def get_sync_config() -> dict:
    return {
        "url": _get(_READECK_URL, ""),
        "api_token": _get(_READECK_API_TOKEN, ""),
        "enabled": _get(_READECK_SYNC_ENABLED, False),
        "last_synced_at": _get(_READECK_LAST_SYNCED_AT, ""),
        "last_imported_count": _get(_READECK_LAST_COUNT, 0),
        "disabled_reason": _get(_READECK_DISABLED_REASON, ""),
    }


def save_sync_config(config: dict) -> None:
    allowed = {
        _READECK_URL, _READECK_API_TOKEN,
        _READECK_SYNC_ENABLED, _READECK_DISABLED_REASON,
    }
    for k in allowed:
        if k in config:
            _set(k, config[k])


# ── HTTP helpers ────────────────────────────────────────────────────────────


def _auth_headers(api_token: str) -> dict:
    return {"Authorization": f"Bearer {api_token}"}


async def _json_request(
    client: httpx.AsyncClient,
    url: str,
    method: str = "GET",
    headers: dict | None = None,
) -> tuple[int, Any]:
    """Thin wrapper returning (status, parsed_body)."""
    try:
        resp = await client.request(method, url, headers=headers)
        body = resp.json() if resp.text else {}
        return resp.status_code, body
    except httpx.TimeoutException:
        return 0, {"error": "Request timed out"}
    except httpx.RequestError as e:
        return 0, {"error": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}


async def _fetch_all_bookmarks(
    client: httpx.AsyncClient, clean_url: str, headers: dict,
) -> tuple[list[dict], int]:
    """Paginate GET /api/bookmarks. Returns (bookmarks, failed_page_count)."""
    bookmarks: list[dict] = []
    failed_pages = 0
    offset = 0
    while True:
        status, body = await _json_request(
            client,
            f"{clean_url}/api/bookmarks?limit={_PAGE_SIZE}&offset={offset}&sort=-created",
            headers=headers,
        )
        if status != 200 or not isinstance(body, list):
            failed_pages += 1
            logger.warning("Readeck bookmarks fetch failed (offset=%d): %s", offset, body)
            break
        if not body:
            break
        bookmarks.extend(body)
        if len(body) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return bookmarks, failed_pages


async def _fetch_annotations(
    client: httpx.AsyncClient, clean_url: str, bookmark_id: str, headers: dict,
) -> tuple[list[dict], bool]:
    """Fetch annotations for one bookmark. Returns (annotations, failed_flag)."""
    status, body = await _json_request(
        client,
        f"{clean_url}/api/bookmarks/{bookmark_id}/annotations",
        headers=headers,
    )
    if status != 200 or not isinstance(body, list):
        return [], True
    return body, False


# ── Public API ──────────────────────────────────────────────────────────────

async def test_connection(url: str, api_token: str) -> dict:
    """Test Readeck API token.

    Returns ``{"ok": True}`` on success, or ``{"ok": False, "error": "..."}``.
    """
    if not url or not api_token:
        return {"ok": False, "error": "URL and API token are required"}

    clean_url = url.rstrip("/")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        status, body = await _json_request(
            client,
            f"{clean_url}/api/bookmarks?limit=1&offset=0",
            headers=_auth_headers(api_token),
        )
    if status == 200:
        return {"ok": True}
    if status == 401:
        return {"ok": False, "error": "Invalid API token (HTTP 401)"}
    msg = body.get("error") or body.get("message") or f"HTTP {status}"
    return {"ok": False, "error": msg}


async def sync_from_readeck() -> dict:
    """Run a full sync pass. Returns stats dict.

    Returns:
        ``{"posted": N, "skipped": N, "errors": N}``
    """
    config = get_sync_config()
    if not config["enabled"]:
        return {"posted": 0, "skipped": 0, "errors": 0}
    if not config["url"] or not config["api_token"]:
        return {"posted": 0, "skipped": 0, "errors": 0}

    clean_url = config["url"].rstrip("/")
    headers = _auth_headers(config["api_token"])

    # Imported lazily to avoid circular imports at module level.
    from app.database import async_session
    from sqlalchemy import text as sqltext

    # ── 1. Verify token ─────────────────────────────────────────────────
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        status, body = await _json_request(
            client, f"{clean_url}/api/bookmarks?limit=1&offset=0", headers=headers,
        )
        if status == 401:
            _set(_READECK_DISABLED_REASON, "invalid_api_token")
            return {"posted": 0, "skipped": 0, "errors": 0}
        if status != 200:
            msg = body.get("error") or body.get("message") or f"HTTP {status}"
            _set(_READECK_DISABLED_REASON, f"connection_failed: {msg}")
            return {"posted": 0, "skipped": 0, "errors": 0}
        # Valid token clears any previous disabled reason
        _set(_READECK_DISABLED_REASON, "")

        # ── 2. Fetch bookmarks + annotations (concurrently) ────────────
        bookmarks, page_errors = await _fetch_all_bookmarks(client, clean_url, headers)

        sem = asyncio.Semaphore(_FETCH_CONCURRENCY)

        async def _fetch_one(bm: dict):
            async with sem:
                if bm.get("is_deleted"):
                    return bm, [], False
                anns, failed = await _fetch_annotations(
                    client, clean_url, str(bm.get("id")), headers
                )
                return bm, anns, failed

        results = await asyncio.gather(
            *[_fetch_one(bm) for bm in bookmarks],
            return_exceptions=True,
        )

    # ── 3. Build existing fingerprint/source_id sets ────────────────────
    posted = 0
    skipped = 0
    errors = page_errors

    async with async_session() as db:
        result = await db.execute(
            sqltext("SELECT fingerprint FROM highlights WHERE fingerprint IS NOT NULL")
        )
        existing_fingerprints = {row[0] for row in result.fetchall()}

        result = await db.execute(
            sqltext("SELECT source_id FROM highlights WHERE source_id LIKE 'readeck:%'")
        )
        existing_source_ids = {row[0] for row in result.fetchall()}

        for item in results:
            if isinstance(item, BaseException):
                errors += 1
                logger.warning("Readeck annotation fetch error: %s", item)
                continue

            bookmark, annotations, failed = item
            if failed:
                errors += 1
                logger.warning(
                    "Readeck annotation fetch failed for bookmark %s", bookmark.get("id")
                )
                continue
            if not annotations:
                continue

            book_title = (bookmark.get("title") or "Untitled").strip()
            authors = bookmark.get("authors") or []
            book_author = (authors[0] if authors else "") or (bookmark.get("site_name") or "")
            bookmark_id = str(bookmark.get("id") or "")

            for ann in annotations:
                ann_id = ann.get("id")
                source_id = f"readeck:{bookmark_id}:{ann_id}"

                # Exact-match dedup first
                if source_id in existing_source_ids:
                    skipped += 1
                    continue

                text = (ann.get("text") or "").strip()
                if not text:
                    skipped += 1
                    continue

                fp = highlight_fingerprint(text, book_title, book_author)
                if fp in existing_fingerprints:
                    skipped += 1
                    continue

                # ── 4. Import ──────────────────────────────────────────
                try:
                    highlighted_at = None
                    if ann.get("created"):
                        try:
                            highlighted_at = datetime.fromisoformat(
                                ann["created"].replace("Z", "+00:00")
                            )
                        except (ValueError, AttributeError):
                            pass

                    color = ann.get("color") or None
                    if color == "none":
                        color = None  # Readeck "none" means uncolored

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

                    await db.execute(stmt, {
                        "text": text,
                        "note": ann.get("note") or None,
                        "page": None,  # Readeck uses selectors, not page numbers
                        "chapter": None,
                        "source_type": "readeck",
                        "source_id": source_id,
                        "book_title": book_title,
                        "book_author": book_author,
                        "color": color,
                        "category": "articles",
                        "highlighted_at": highlighted_at,
                        "created_at": datetime.utcnow(),
                        "share_token": secrets.token_urlsafe(16),
                        "fingerprint": fp,
                    })

                    await db.commit()
                    posted += 1
                    existing_fingerprints.add(fp)
                    existing_source_ids.add(source_id)

                except Exception as e:
                    await db.rollback()
                    errors += 1
                    logger.warning("Failed to import Readeck annotation %s: %s", ann_id, e)

    # ── 5. Save sync state ──────────────────────────────────────────────
    if posted > 0:
        _set(_READECK_LAST_SYNCED_AT, datetime.utcnow().isoformat())
        _set(_READECK_LAST_COUNT, posted)

    logger.info(
        "Readeck sync complete: posted=%d skipped=%d errors=%d",
        posted, skipped, errors,
    )
    return {"posted": posted, "skipped": skipped, "errors": errors}
