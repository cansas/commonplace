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


async def _hardcover_search(title: str, author: str, client: httpx.AsyncClient) -> Optional[str]:
    """Search Hardcover.app for a book cover using GraphQL API."""
    if not HARDCOVER_API_KEY:
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
            headers={"Authorization": f"Bearer {HARDCOVER_API_KEY}"},
        )
        if resp.status_code != 200:
            print(f"  [covers] Hardcover HTTP {resp.status_code} for '{title}': {resp.text[:300]}")
            return None
        data = resp.json()
        search_data = data.get("data", {}).get("search", {})
        ids = search_data.get("ids") or []
        results = search_data.get("results") or []
        print(f"  [covers] Hardcover search: {len(results)} results, {len(ids)} ids for '{title}'")
        if results:
            print(f"  [covers] First result type={type(results[0]).__name__}, value={results[0]}")
        if ids:
            print(f"  [covers] First ids: {ids[:3]}")

        # Handle both object results and ID-only results
        for book in results:
            if not isinstance(book, dict):
                continue
            # Try direct cover image field
            cover = book.get("image") or book.get("cover_url")
            if cover:
                if isinstance(cover, dict):
                    cover = cover.get("url")
                if cover:
                    print(f"  [covers] Hardcover cover from image field: {cover}")
                    return cover

            # Construct from slug
            slug = book.get("slug")
            if slug:
                cover = f"https://hardcovercdn.com/books/{slug}.jpg"
                print(f"  [covers] Hardcover cover from slug: {cover}")
                return cover

        # Fallback: try querying books by ID
        if ids:
            bid = ids[0]
            book_query = "{ book: books_by_pk(id: " + str(bid) + ") { id title slug image { url } } }"
            book_resp = await client.post(
                "https://api.hardcover.app/v1/graphql",
                json={"query": book_query},
                headers={"Authorization": f"Bearer {HARDCOVER_API_KEY}"},
            )
            if book_resp.status_code == 200:
                book_data = book_resp.json().get("data", {}).get("book", {})
                if book_data:
                    slug = book_data.get("slug")
                    if slug:
                        return f"https://hardcovercdn.com/books/{slug}.jpg"
                    img = book_data.get("image")
                    if img and isinstance(img, dict) and img.get("url"):
                        return img["url"]

        if results:
            print(f"  [covers] Hardcover first result: {results[0]}")
        if ids and not results:
            print(f"  [covers] Hardcover IDs without results: {ids[:3]}")

    except Exception as e:
        import traceback
        print(f"  [covers] Hardcover error for '{title}': {e}")
        print(f"  [covers] Hardcover traceback: {traceback.format_exc()[:300]}")
    return None


async def search_cover(title: str, author: str = "", client: httpx.AsyncClient = None) -> tuple[Optional[str], str]:
    """Search for a book cover across multiple sources with fallback.

    Returns (cover_url, source_name) or (None, "") if no source has a cover.
    """
    _owns_client = client is None
    if _owns_client:
        client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
    try:
        # 1. Hardcover.app (needs API key, best for newer/modern books)
        url = await _hardcover_search(title, author, client)
        if url:
            return url, "hardcover"

        # 2. Open Library (free, largest catalog)
        url = await _open_library_search(title, author, client)
        if url:
            return url, "openlibrary"

    finally:
        if _owns_client:
            await client.aclose()
    return None, ""


async def batch_search(books: list[tuple[str, str]], rate_limit: float = 1.0, concurrency: int = 3) -> dict:
    """Search for covers for multiple books concurrently.

    Returns dict mapping (title, author) -> (url, source).
    """
    results = {}
    sem = asyncio.Semaphore(concurrency)

    async def _fetch(client, title, author):
        async with sem:
            url, source = await search_cover(title, author, client=client)
            results[(title, author)] = (url, source)
            await asyncio.sleep(rate_limit)

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        await asyncio.gather(*[_fetch(client, t, a) for t, a in books])
    return results
