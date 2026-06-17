"""Books browse route — list books by title/author with highlight counts."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sa_func, or_
from app.database import get_db
from app.models import Highlight
from typing import Optional
import math

router = APIRouter(tags=["books"])

_jinja = None


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
        books.append({
            "title": row.book_title,
            "author": row.book_author or "Unknown",
            "highlight_count": row.highlight_count,
            "last_highlighted": row.last_highlighted.strftime("%Y-%m-%d") if row.last_highlighted else "",
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
