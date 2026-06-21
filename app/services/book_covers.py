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


async def _open_library_isbn_lookup(isbn: str, client: httpx.AsyncClient) -> Optional[str]:
    """Look up a book cover by ISBN directly (most reliable method)."""
    try:
        resp = await client.get(
            "https://openlibrary.org/api/books",
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

    try:
        resp = await client.get("https://openlibrary.org/search.json", params=params)
        if resp.status_code != 200:
            return None
        data = resp.json()
        docs = data.get("docs", [])

        # Try to find the best match
        for doc in docs:
            cover_i = doc.get("cover_i")
            if cover_i:
                return f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg"

            # Fallback to ISBN-based cover
            isbns = doc.get("isbn", [])
            for isbn in isbns:
                if len(isbn) in (10, 13):
                    return f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"

    except Exception as e:
        print(f"  [covers] Open Library error for '{title}': {e}")
    return None


async def _hardcover_search(title: str, author: str, client: httpx.AsyncClient, api_key: str = "", known_id: int | None = None) -> tuple[str, int | None, str | None] | None:
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
        results = search_data.get("results") or {}
        if not isinstance(results, list):
            # results is a dict mapping ID -> object (Typesense format)
            results_list = list(results.values())
        else:
            results_list = results
        ids_list = ids if isinstance(ids, list) else list(ids.values()) if isinstance(ids, dict) else []
        print(f"  [covers] Hardcover search: {len(results_list)} results, {len(ids_list)} ids for '{title}'")
        if results_list:
            print(f"  [covers] First result type={type(results_list[0]).__name__}")

        for book in results_list:
            if not isinstance(book, dict):
                # HardCover returns each hit as Typesense array: [hit_obj, ...]
                # where hit_obj.document holds the actual book fields
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
                    print(f"  [covers] Hardcover cover from image field: {cover}")
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

        if results_list:
            print(f"  [covers] Hardcover first result keys: {list(results_list[0].keys())[:10] if isinstance(results_list[0], dict) else results_list[0]}")
        if ids_list and not results_list:
            print(f"  [covers] Hardcover IDs without results: {ids_list[:3]}")

    except Exception as e:
        import traceback
        print(f"  [covers] Hardcover error for '{title}': {e}")
        print(f"  [covers] Hardcover traceback: {traceback.format_exc()[:300]}")
    return None


async def search_cover(title: str, author: str = "", client: httpx.AsyncClient = None, hardcover_key: str = "", known_id: int | None = None, isbn: str | None = None) -> tuple[str | None, str, int | None, str | None]:
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

        # 3. Open Library (title search — largest catalog)
        url = await _open_library_search(title, author, client)
        if url:
            return url, "openlibrary", None, None

    finally:
        if _owns_client:
            await client.aclose()
    return None, "", None, None


async def batch_search(books: list[tuple[str, str]], rate_limit: float = 1.0, concurrency: int = 3, hardcover_key: str = "") -> dict:
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
