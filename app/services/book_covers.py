"""Book cover lookup via Open Library API."""

import httpx
import asyncio
from typing import Optional

OPEN_LIBRARY_SEARCH = "https://openlibrary.org/search.json"
COVERS_BASE = "https://covers.openlibrary.org/b/id"


async def search_cover(title: str, author: str = "") -> Optional[str]:
    query = title.strip()
    if author:
        query += f" {author.strip()}"

    params = {"q": query, "limit": 5, "fields": "key,cover_i,title,author_name"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(OPEN_LIBRARY_SEARCH, params=params)
            resp.raise_for_status()
            data = resp.json()
            for doc in data.get("docs", []):
                cover_i = doc.get("cover_i")
                if cover_i:
                    return f"{COVERS_BASE}/{cover_i}-L.jpg"
    except Exception as e:
        print(f"  [covers] Open Library error for '{title}': {e}")
    return None


async def batch_search(books: list[tuple[str, str]], rate_limit: float = 1.0) -> dict:
    results = {}
    for title, author in books:
        url = await search_cover(title, author)
        results[(title, author)] = url
        await asyncio.sleep(rate_limit)
    return results
