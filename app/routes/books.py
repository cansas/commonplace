"""Books browse route — list books by title/author with highlight counts."""

from fastapi import APIRouter, Depends, Query, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sa_func, or_
from app.database import get_db
from app.models import Highlight, BookCover
from app.services.book_covers import search_cover
from typing import Optional
import math
import os

router = APIRouter(tags=["books"])

_jinja = None
COVERS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "covers")


def init(templates):
    global _jinja
    _jinja = templates


@router.get("/books", response_class=HTMLResponse)
async def books_page(
    request: Request,
    search: Optional[str] = Query(default=""),
    sort: str = Query(default="highlights"),
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    per_page = 30

    # Build query for distinct books with counts
    query = (
        select(
            Highlight.book_title,
            Highlight.book_author,
            sa_func.count(Highlight.id).label("highlight_count"),
            sa_func.max(Highlight.highlighted_at).label("last_highlighted"),
        )
        .group_by(Highlight.book_title, Highlight.book_author)
    )

    if search:
        query = query.where(
            or_(
                Highlight.book_title.ilike(f"%{search}%"),
                Highlight.book_author.ilike(f"%{search}%"),
            )
        )

    # Count total distinct books
    count_q = select(sa_func.count()).select_from(query.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0
    total_pages = max(1, math.ceil(total / per_page))

    # Sort
    if sort == "title":
        query = query.order_by(Highlight.book_title.asc())
    elif sort == "author":
        query = query.order_by(Highlight.book_author.asc().nullslast())
    elif sort == "recent":
        query = query.order_by(sa_func.max(Highlight.highlighted_at).desc().nullslast())
    else:  # highlights (default)
        query = query.order_by(sa_func.count(Highlight.id).desc())

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    rows = result.all()

    books = []
    for row in rows:
        cover_result = await db.execute(
            select(BookCover).where(
                BookCover.book_title == row.book_title,
                BookCover.book_author == (row.book_author or ""),
            )
        )
        cover = cover_result.scalar_one_or_none()
        books.append({
            "title": row.book_title,
            "author": row.book_author or "Unknown",
            "highlight_count": row.highlight_count,
            "last_highlighted": row.last_highlighted.strftime("%Y-%m-%d") if row.last_highlighted else "",
            "cover_url": cover.cover_url if cover else None,
            "cover_source": cover.cover_source if cover else "none",
        })

    return _jinja.TemplateResponse(
        request,
        "books.html",
        {
            "active_page": "books",
            "books": books,
            "search": search,
            "sort": sort,
            "page": page,
            "total_pages": total_pages,
            "total_books": total,
        },
    )


@router.post("/api/books/cover/fetch")
async def fetch_cover(title: str = Form(...), author: str = Form(default=""), source: str = Form(default="auto"), db: AsyncSession = Depends(get_db)):
    try:
        from app.services.book_covers import search_cover
        url = await search_cover(title, author)
        if not url:
            return {"ok": False, "error": "No cover found"}

        result = await db.execute(
            select(BookCover).where(
                BookCover.book_title == title,
                BookCover.book_author == author,
            )
        )
        cover = result.scalar_one_or_none()
        if cover:
            cover.cover_url = url
            cover.cover_source = "openlibrary"
        else:
            db.add(BookCover(book_title=title, book_author=author, cover_url=url, cover_source="openlibrary"))
        await db.commit()
        return {"ok": True, "cover_url": url}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@router.post("/api/books/cover/upload")
async def upload_cover(title: str = Form(...), author: str = Form(default=""), file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        return JSONResponse({"ok": False, "error": "Only JPG, PNG, and WebP are accepted"}, status_code=400)

    dest = os.path.join(COVERS_DIR, f"{title.replace('/', '-')}_{author.replace('/', '-')}{ext}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)
    cover_url = f"/static/covers/{os.path.basename(dest)}"

    result = await db.execute(
        select(BookCover).where(
            BookCover.book_title == title,
            BookCover.book_author == author,
        )
    )
    cover = result.scalar_one_or_none()
    if cover:
        cover.cover_url = cover_url
        cover.cover_source = "upload"
    else:
        db.add(BookCover(book_title=title, book_author=author, cover_url=cover_url, cover_source="upload"))
    await db.commit()
    return {"ok": True, "cover_url": cover_url}


@router.post("/api/books/cover/backfill")
async def backfill_covers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Highlight.book_title, Highlight.book_author)
        .distinct()
    )
    books = result.all()
    fetched = 0
    for row in books:
        existing = await db.execute(
            select(BookCover).where(
                BookCover.book_title == row.book_title,
                BookCover.book_author == (row.book_author or ""),
            )
        )
        if existing.scalar_one_or_none():
            continue
        url = await search_cover(row.book_title, row.book_author or "")
        if url:
            db.add(BookCover(book_title=row.book_title, book_author=row.book_author or "", cover_url=url, cover_source="openlibrary"))
            fetched += 1
            await db.commit()
    return {"ok": True, "fetched": fetched}
