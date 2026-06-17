"""Highlight CRUD + search routes."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sa_func
from app.database import get_db
from app.models import Highlight, Tag
from app.schemas import HighlightOut, HighlightCreate, HighlightUpdate
from app.services.highlight_card import generate_card
from typing import Optional, List
from datetime import datetime
import math

router = APIRouter(tags=["highlights"])

# Set by main.py at startup
_jinja = None


def init(templates):
    global _jinja
    _jinja = templates


# ---- Web UI ----

@router.get("/highlights", response_class=HTMLResponse)
async def highlights_page(
    request: Request,
    search: Optional[str] = Query(default=""),
    source: Optional[str] = Query(default=""),
    book: Optional[str] = Query(default=""),
    favorites: Optional[str] = Query(default=""),
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    per_page = 20
    query = select(Highlight).order_by(Highlight.created_at.desc())

    if search:
        from sqlalchemy import text
        fts_q = text(
            "SELECT rowid FROM highlights_fts WHERE highlights_fts MATCH :q ORDER BY rank"
        )
        try:
            fts_r = await db.execute(fts_q, {"q": search.strip()})
            ids = [r[0] for r in fts_r.fetchall()]
            if ids:
                query = query.where(Highlight.id.in_(ids))
            else:
                query = query.where(Highlight.id == -1)  # No results
        except Exception:
            pass  # Fall back to no filter on bad query syntax
    if source:
        query = query.where(Highlight.source_type == source)
    if book:
        query = query.where(Highlight.book_title.ilike(f"%{book}%"))
    if favorites == "1":
        query = query.where(Highlight.favorite == 1)

    # Count total
    count_q = select(sa_func.count()).select_from(query.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0
    total_pages = max(1, math.ceil(total / per_page))

    # Fetch page
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    highlights = result.scalars().all()

    hl_list = []
    for h in highlights:
        hl_list.append({
            "id": h.id,
            "text": h.text,
            "note": h.note,
            "book_title": h.book_title,
            "book_author": h.book_author,
            "source_type": h.source_type,
            "highlighted_at": h.highlighted_at.strftime("%Y-%m-%d") if h.highlighted_at else "",
            "tags": [t.name for t in h.tags],
            "favorite": h.favorite,
            "share_token": h.share_token,
        })

    return _jinja.TemplateResponse(
        request,
        "highlights.html",
        {
            "active_page": "highlights",
            "highlights": hl_list,
            "search": search,
            "source_filter": source,
            "book": book,
            "favorites_filter": favorites,
            "page": page,
            "total_pages": total_pages,
            "total_count": total,
        },
    )


# ---- API ----

@router.post("/api/highlights", response_model=HighlightOut)
async def create_highlight(
    data: HighlightCreate,
    db: AsyncSession = Depends(get_db),
):
    hl = Highlight(
        text=data.text,
        note=data.note,
        page=data.page,
        chapter=data.chapter,
        source_type=data.source_type,
        source_id=data.source_id,
        book_title=data.book_title,
        book_author=data.book_author,
        book_url=data.book_url,
        category=data.category,
        color=data.color,
        highlighted_at=data.highlighted_at or datetime.utcnow(),
    )

    if data.tags:
        for tag_name in data.tags:
            result = await db.execute(select(Tag).where(Tag.name == tag_name))
            tag = result.scalar_one_or_none()
            if not tag:
                tag = Tag(name=tag_name)
                db.add(tag)
            hl.tags.append(tag)

    db.add(hl)
    await db.commit()
    await db.refresh(hl)
    return hl


@router.get("/api/highlights", response_model=List[HighlightOut])
async def list_highlights(
    skip: int = 0,
    limit: int = 50,
    since: Optional[str] = "",
    search: Optional[str] = "",
    db: AsyncSession = Depends(get_db),
):
    if search and search.strip():
        from sqlalchemy import text
        fts_query = text(
            "SELECT rowid FROM highlights_fts WHERE highlights_fts MATCH :q ORDER BY rank"
        )
        fts_result = await db.execute(fts_query, {"q": search.strip()})
        ids = [row[0] for row in fts_result.fetchall()]
        if not ids:
            return []
        query = select(Highlight).where(Highlight.id.in_(ids)).order_by(Highlight.created_at.desc())
    else:
        query = select(Highlight).order_by(Highlight.created_at.desc())
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query = query.where(Highlight.created_at >= since_dt)
        except (ValueError, TypeError):
            pass
    result = await db.execute(query.offset(skip).limit(limit))
    return result.scalars().all()


@router.get("/api/export")
async def export_highlights(
    since: Optional[str] = "",
    db: AsyncSession = Depends(get_db),
):
    """Export highlights grouped by book for Obsidian sync."""
    query = select(Highlight).order_by(Highlight.book_title, Highlight.highlighted_at)
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query = query.where(Highlight.created_at >= since_dt)
        except (ValueError, TypeError):
            pass

    result = await db.execute(query)
    all_highlights = result.scalars().all()

    # Group by book
    books = {}
    for h in all_highlights:
        key = (h.book_title, h.book_author or "")
        if key not in books:
            books[key] = {
                "title": h.book_title,
                "author": h.book_author or "",
                "highlights": [],
            }
        books[key]["highlights"].append({
            "id": h.id,
            "text": h.text,
            "note": h.note,
            "page": h.page,
            "chapter": h.chapter,
            "color": h.color,
            "favorite": bool(h.favorite),
            "highlighted_at": h.highlighted_at.isoformat() if h.highlighted_at else None,
            "created_at": h.created_at.isoformat() if h.created_at else None,
            "tags": [t.name for t in h.tags],
        })

    return {
        "books": list(books.values()),
        "total": len(all_highlights),
        "total_books": len(books),
    }


@router.delete("/api/highlights/{hl_id}")
async def delete_highlight(hl_id: int, db: AsyncSession = Depends(get_db)):
    hl = await db.get(Highlight, hl_id)
    if hl:
        await db.delete(hl)
        await db.commit()
    return {"ok": True}


@router.post("/api/highlights/{hl_id}/favorite")
async def toggle_favorite(hl_id: int, db: AsyncSession = Depends(get_db)):
    hl = await db.get(Highlight, hl_id)
    if not hl:
        return {"error": "Not found"}, 404
    hl.favorite = 0 if hl.favorite else 1
    await db.commit()
    return {"id": hl_id, "favorite": hl.favorite}


@router.put("/api/highlights/{hl_id}")
async def update_highlight(hl_id: int, data: HighlightUpdate, db: AsyncSession = Depends(get_db)):
    hl = await db.get(Highlight, hl_id)
    if not hl:
        return {"error": "Not found"}, 404
    
    update_data = data.model_dump(exclude_unset=True)
    tag_names = update_data.pop("tags", None)
    
    for key, value in update_data.items():
        setattr(hl, key, value)
    
    if tag_names is not None:
        hl.tags = []
        for tag_name in tag_names:
            result = await db.execute(select(Tag).where(Tag.name == tag_name))
            tag = result.scalar_one_or_none()
            if not tag:
                tag = Tag(name=tag_name)
                db.add(tag)
            hl.tags.append(tag)
    
    await db.commit()
    await db.refresh(hl)
    return {"ok": True, "id": hl.id}


@router.get("/api/highlights/{hl_id}/card")
async def highlight_card(hl_id: int, db: AsyncSession = Depends(get_db)):
    hl = await db.get(Highlight, hl_id)
    if not hl:
        return {"error": "Not found"}, 404
    
    svg = generate_card(
        highlight_text=hl.text or "",
        book_title=hl.book_title or "",
        book_author=hl.book_author or "",
        note=hl.note or "",
        highlight_id=hl.id,
    )
    from fastapi.responses import Response
    return Response(content=svg, media_type="image/svg+xml")
