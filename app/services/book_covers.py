"""Book cover lookup — multi-source with fallback chain.

Priority:
  1. Hardcover.app API (requires API key, best quality for modern books)
  2. Open Library Covers API (free, no key, large catalog)
"""

import os
import asyncio
from typing import Optional

import httpx

HARDCOVER_API_KEY = os.environ.get("HARDCOVER_API_KEY", "")
REQUEST_TIMEOUT = 12.0

OL_COVERS = "https://covers.openlibrary.org"
OL_API = "https://openlibrary.org"

# ── Cover result type ──────────────────────────────────────────────────

CoverResult = dict  # {"cover_url": str, "source": str, "cover_id": ...}


def _ol_cover_url(cover_id: int, size: str = "L") -> str:
    return f"{OL_COVERS}/b/id/{cover_id}-{size}.jpg"


def _ol_isbn_cover_url(isbn: str, size: str = "L") -> str:
    return f"{OL_COVERS}/b/isbn/{isbn}-{size}.jpg"


# ── Open Library ───────────────────────────────────────────────────────

async def _open_library_isbn_lookup(isbn: str, client: httpx.AsyncClient) -> Optional[str]:
    """Look up a book cover by ISBN directly (most reliable method)."""
    try:
        resp = await client.get(
            f"{OL_API}/api/books",
            params={"bibkeys": f"ISBN:{isbn}", "format": "json", "jscmd": "data"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        key = f"ISBN:{isbn}"
        book = data.get(key)
        if not book:
            return None
        cover = book.get("cover")
        if cover and isinstance(cover, dict):
            return cover.get("large") or cover.get("medium") or cover.get("small")
    except Exception as e:
        print(f"  [covers] ISBN lookup error for {isbn}: {e}")
    return None


async def _open_library_search(title: str, author: str, client: httpx.AsyncClient) -> Optional[str]:
    """Search Open Library for a book and return the cover URL."""
    params = {
        "title": title.strip(),
        "fields": "key,title,author_name,isbn,cover_i",
        "limit": 5,
    }
    if author:
        params["author"] = author.strip()

    results = await _open_library_search_multi(title, author, client)
    if results:
        return results[0].get("cover_url")
    return None


async def _open_library_search_multi(
    title: str, author: str, client: httpx.AsyncClient, limit: int = 5
) -> list[CoverResult]:
    """Search Open Library and return multiple cover options, including from editions."""
    params = {
        "title": title.strip(),
        "fields": "key,title,author_name,isbn,cover_i",
        "limit": str(limit),
    }
    if author:
        params["author"] = author.strip()

    seen: set[int] = set()
    results: list[CoverResult] = []

    try:
        resp = await client.get(f"{OL_API}/search.json", params=params)
        if resp.status_code != 200:
            return []

        data = resp.json()
        docs = data.get("docs", [])

        # ── Phase 1: collect cover IDs from search results + editions ──
        edition_keys: list[str] = []
        for doc in docs:
            cover_i = doc.get("cover_i")
            if cover_i and cover_i not in seen:
                seen.add(cover_i)
                results.append({
                    "cover_url": _ol_cover_url(cover_i),
                    "source": "openlibrary",
                    "cover_id": cover_i,
                })

            # Collect keys for editions fallback
            key = doc.get("key")
            if key and key.startswith("/works/"):
                edition_keys.append(key)

            # ISBN-based cover as alternative
            isbns = doc.get("isbn", [])
            for isbn in isbns:
                if len(isbn) in (10, 13):
                    url = _ol_isbn_cover_url(isbn)
                    isbn_key = f"isbn:{isbn}"
                    if isbn_key not in [r.get("_id") for r in results]:
                        results.append({
                            "cover_url": url,
                            "source": "openlibrary",
                            "source_type": "isbn",
                            "cover_id": isbn_key,
                            "isbn": isbn,
                            "_id": isbn_key,
                        })
                    break  # one ISBN per doc is enough

        # ── Phase 2: editions fallback (KoInsight pattern) ──
        for key in edition_keys[:3]:  # limit parallel fetches
            try:
                ed_resp = await client.get(
                    f"{OL_API}{key}/editions.json",
                    params={"limit": "10"},
                    timeout=REQUEST_TIMEOUT,
                )
                if ed_resp.status_code != 200:
                    continue
                ed_data = ed_resp.json()
                for entry in ed_data.get("entries", []):
                    for cid in entry.get("covers", []):
                        if cid not in seen:
                            seen.add(cid)
                            results.append({
                                "cover_url": _ol_cover_url(cid),
                                "source": "openlibrary",
                                "source_type": "edition",
                                "cover_id": cid,
                            })
            except Exception as e:
                print(f"  [covers] Editions fallback error for {key}: {e}")

    except Exception as e:
        print(f"  [covers] Open Library error for '{title}': {e}")

    return results


# ── Hardcover ──────────────────────────────────────────────────────────

async def _hardcover_search(
    title: str, author: str, client: httpx.AsyncClient,
    api_key: str = "", known_id: int | None = None
) -> tuple[str, int | None, str | None] | None:
    """Search Hardcover.app for a book cover using GraphQL API.

    Returns (cover_url, hardcover_id, isbn) or None if no cover found.
    If known_id is provided, skips the fuzzy search and queries by ID directly.
    """
    key = api_key or HARDCOVER_API_KEY
    if not key:
        return None

    # If we already have a known HardCover ID, skip fuzzy search entirely
    if known_id is not None:
        book_query = """
        query BookById($id: Int!) {
          book: books_by_pk(id: $id) {
            id title slug isbn image { url }
          }
        }
        """
        payload = {"query": book_query, "variables": {"id": known_id}}
        try:
            resp = await client.post(
                "https://api.hardcover.app/v1/graphql",
                json=payload,
                headers={"Authorization": f"Bearer {key}"},
            )
            if resp.status_code == 200:
                book_data = resp.json().get("data", {}).get("book", {})
                if book_data:
                    img = book_data.get("image")
                    if img and isinstance(img, dict) and img.get("url"):
                        return (img["url"], book_data.get("id"), book_data.get("isbn"))
                    slug = book_data.get("slug")
                    if slug:
                        return (f"https://hardcovercdn.com/books/{slug}.jpg", book_data.get("id"), book_data.get("isbn"))
        except Exception as e:
            print(f"  [covers] HardCover books_by_pk({known_id}) error: {e}")
        return None

    query = """query SearchBooks($query: String!) {
      search(query: $query, query_type: "Book", per_page: 5, page: 1) {
        ids
        results
      }
    }"""
    search_term = title.strip()
    payload = {"query": query, "variables": {"query": search_term}}

    try:
        resp = await client.post(
            "https://api.hardcover.app/v1/graphql",
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
        )
        if resp.status_code != 200:
            print(f"  [covers] Hardcover HTTP {resp.status_code} for '{title}': {resp.text[:300]}")
            return None
        data = resp.json()
        search_data = data.get("data", {}).get("search", {})
        ids = search_data.get("ids") or []
        results_raw = search_data.get("results") or {}
        if not isinstance(results_raw, list):
            results_list = list(results_raw.values())
        else:
            results_list = results_raw
        ids_list = ids if isinstance(ids, list) else list(ids.values()) if isinstance(ids, dict) else []

        for book in results_list:
            if not isinstance(book, dict):
                if isinstance(book, list):
                    for item in book:
                        if isinstance(item, dict):
                            doc = item.get("document") or item
                            if isinstance(doc, dict):
                                book = doc
                                break
                    else:
                        continue
                else:
                    continue
            # Try direct cover image field
            cover = book.get("image") or book.get("cover_url")
            if cover:
                if isinstance(cover, dict):
                    cover = cover.get("url")
                if cover:
                    first_id = ids_list[0] if ids_list else None
                    return (cover, first_id, book.get("isbn"))

            # Note: slug-based URL construction (~hardcovercdn.com) is unreliable
            # and often blocked by hotlink protection. Fall through to Open Library.

        # Fallback: try querying books by ID
        if ids_list:
            bid = ids_list[0]
            book_query = "{ book: books_by_pk(id: " + str(bid) + ") { id title slug isbn image { url } } }"
            book_resp = await client.post(
                "https://api.hardcover.app/v1/graphql",
                json={"query": book_query},
                headers={"Authorization": f"Bearer {key}"},
            )
            if book_resp.status_code == 200:
                book_data = book_resp.json().get("data", {}).get("book", {})
                if book_data:
                    img = book_data.get("image")
                    if img and isinstance(img, dict) and img.get("url"):
                        return (img["url"], book_data.get("id"), book_data.get("isbn"))
                    slug = book_data.get("slug")
                    if slug:
                        return (f"https://hardcovercdn.com/books/{slug}.jpg", book_data.get("id"), book_data.get("isbn"))

    except Exception as e:
        import traceback
        print(f"  [covers] Hardcover error for '{title}': {e}")
        print(f"  [covers] Hardcover traceback: {traceback.format_exc()[:300]}")
    return None


# ── Multi-result search for cover selector ────────────────────────────

async def list_cover_options(
    title: str, author: str = "",
    hardcover_key: str = "", known_id: int | None = None,
) -> list[CoverResult]:
    """Search all sources and return multiple cover options for the picker UI.

    Returns a list of dicts, each with at least ``cover_url`` and ``source``.
    Deduplicates by cover_url.
    """
    seen_urls: set[str] = set()
    results: list[CoverResult] = []

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        # 1. Open Library search with editions fallback
        ol_results = await _open_library_search_multi(title, author, client)
        for r in ol_results:
            url = r.get("cover_url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                results.append(r)

        # 2. Hardcover search (if key available)
        key = hardcover_key or HARDCOVER_API_KEY
        if key:
            # For the selector, we want the search result, not just the best match
            # Reuse the existing search function for the best, but also add non-duplicate results
            hc_result = await _hardcover_search(title, author, client, api_key=key, known_id=known_id)
            if hc_result:
                url, hc_id, isbn = hc_result
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    entry: CoverResult = {
                        "cover_url": url,
                        "source": "hardcover",
                    }
                    if hc_id is not None:
                        entry["hardcover_id"] = hc_id
                    if isbn is not None:
                        entry["isbn"] = isbn
                    results.append(entry)

    return results


# ── Single best-match search (existing) ────────────────────────────────

async def search_cover(
    title: str, author: str = "",
    client: httpx.AsyncClient | None = None,
    hardcover_key: str = "",
    known_id: int | None = None,
    isbn: str | None = None,
) -> tuple[str | None, str, int | None, str | None]:
    """Search for a book cover across multiple sources with fallback.

    Returns (cover_url, source_name, hardcover_id, isbn) or (None, "", None, None) if no source has a cover.
    Priority:
      1. ISBN lookup (most reliable — Open Library direct)
      2. HardCover by known_id (skips fuzzy search)
      3. HardCover title search (needs API key)
      4. Open Library title search (free, largest catalog)
    """
    _owns_client = client is None
    if _owns_client:
        client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
    try:
        # 1. ISBN-based lookup (most reliable)
        if isbn:
            url = await _open_library_isbn_lookup(isbn, client)
            if url:
                return url, "openlibrary", None, isbn

        # 2. Hardcover.app (by known ID or title search)
        result = await _hardcover_search(title, author, client, api_key=hardcover_key, known_id=known_id)
        if result:
            url, hc_id, isbn = result
            return url, "hardcover", hc_id, isbn

        # 3. Open Library (title search — with editions fallback)
        url = await _open_library_search(title, author, client)
        if url:
            return url, "openlibrary", None, None

    finally:
        if _owns_client:
            await client.aclose()
    return None, "", None, None


# ── Batch backfill ─────────────────────────────────────────────────────

async def batch_search(
    books: list[tuple[str, str]], rate_limit: float = 1.0,
    concurrency: int = 3, hardcover_key: str = "",
) -> dict:
    """Search for covers for multiple books concurrently.

    Returns dict mapping (title, author) -> (url, source).
    """
    results = {}
    sem = asyncio.Semaphore(concurrency)

    async def _fetch(client, title, author):
        async with sem:
            url, source, hc_id, isbn = await search_cover(title, author, client=client, hardcover_key=hardcover_key)
            results[(title, author)] = (url, source)
            await asyncio.sleep(rate_limit)

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        await asyncio.gather(*[_fetch(client, t, a) for t, a in books])
    return results
