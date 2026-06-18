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

    query = "query SearchBooks($query: String!) { books(where: {title: {_ilike: $query}}, limit: 3) { id title image { url } } }"
    search_term = f"%{title.strip()}%"
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
        books = data.get("data", {}).get("books", [])
        print(f"  [covers] Hardcover found {len(books)} books for '{title}'")

        for book in books:
            img = book.get("image")
            if img and img.get("url"):
                print(f"  [covers] Hardcover cover: {img['url']}")
                return img["url"]

        # If no cover but books found, log why
        if books:
            for book in books:
                print(f"  [covers] Hardcover book '{book.get('title', '?')}' has image={bool(book.get('image'))}")

    except Exception as e:
        print(f"  [covers] Hardcover error for '{title}': {e}")
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
