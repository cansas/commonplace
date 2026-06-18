"""Book cover lookup — multi-source with fallback chain.

Priority:
  1. Hardcover.app API (requires API key, best quality for modern books)
  2. Open Library Covers API (free, no key, large catalog)
  3. OPDS catalog (self-hosted Booklore/Kavita/Calibre — requires URL + auth)
"""

import os
import asyncio
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import urlparse, quote as url_quote

import httpx

HARDCOVER_API_KEY = os.environ.get("HARDCOVER_API_KEY", "")
OPDS_URL = os.environ.get("OPDS_URL", "")
OPDS_USERNAME = os.environ.get("OPDS_USERNAME", "")
OPDS_PASSWORD = os.environ.get("OPDS_PASSWORD", "")
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
            return None
        data = resp.json()
        books = data.get("data", {}).get("books", [])

        for book in books:
            img = book.get("image")
            if img and img.get("url"):
                return img["url"]

    except Exception as e:
        print(f"  [covers] Hardcover error for '{title}': {e}")
    return None


OPDS_NS = {"atom": "http://www.w3.org/2005/Atom"}

# Shared covers directory (same as books.py)
_COVERS_DIR = os.environ.get("COVERS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "covers"))


async def _opds_search(title: str, author: str, client: httpx.AsyncClient) -> Optional[str]:
    """Search an OPDS catalog for a book cover.

    Requires OPDS_URL, OPDS_USERNAME, and OPDS_PASSWORD env vars.
    Downloads the image and saves it locally, returns a local /static/covers/ URL.
    """
    if not OPDS_URL:
        return None

    auth_creds = (OPDS_USERNAME, OPDS_PASSWORD) if OPDS_USERNAME else None
    search_url = f"{OPDS_URL.rstrip('/')}/catalog?q={url_quote(title.strip())}&size=5"

    try:
        resp = await client.get(search_url, auth=auth_creds, timeout=8.0)
        if resp.status_code != 200:
            return None

        root = ET.fromstring(resp.text)
        for entry in root.findall("atom:entry", OPDS_NS):
            entry_title = entry.find("atom:title", OPDS_NS)
            if entry_title is None or not entry_title.text:
                continue
            if title.strip().lower() not in entry_title.text.lower():
                continue
            for link in entry.findall("atom:link", OPDS_NS):
                rel = link.get("rel", "")
                href = link.get("href", "")
                if "image" not in rel or not href:
                    continue

                # Resolve absolute URL
                parsed = urlparse(href)
                if not parsed.scheme:
                    base = OPDS_URL.rstrip("/")
                    href = f"{base}{href}"

                # Download the cover image (follow redirects)
                img_resp = await client.get(href, auth=auth_creds, follow_redirects=True, timeout=10.0)
                if img_resp.status_code != 200:
                    continue

                img_bytes = img_resp.content
                if len(img_bytes) < 500:
                    continue

                # Quick content-type sanity check — must be an image
                ctype = img_resp.headers.get("content-type", "")
                if not any(t in ctype for t in ["image/", "octet-stream"]) and not ctype:
                    # If no mime from server, check magic bytes
                    if not (img_bytes[:2] == b"\xff\xd8" or img_bytes[:4] == b"\x89PNG" or img_bytes[:4] == b"RIFF"):
                        continue

                # Save to covers directory
                ext = ".jpg"
                content_type = img_resp.headers.get("content-type", "")
                if "png" in content_type:
                    ext = ".png"
                elif "webp" in content_type:
                    ext = ".webp"

                import hashlib
                safe_name = hashlib.md5(f"opds_{title}_{author}".encode()).hexdigest() + ext
                dest = os.path.join(_COVERS_DIR, safe_name)
                os.makedirs(_COVERS_DIR, exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(img_bytes)

                local_url = f"/static/covers/{safe_name}"
                return local_url
    except Exception as e:
        print(f"  [covers] OPDS error for '{title}': {e}")
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

        # 2. OPDS catalog (self-hosted, configured via env vars)
        url = await _opds_search(title, author, client)
        if url:
            return url, "opds"

        # 3. Open Library (free, largest catalog)
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
