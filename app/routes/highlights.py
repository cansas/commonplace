"""Highlight CRUD + search routes."""

from fastapi import APIRouter, Depends, Query, Request, HTTPException, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sa_func, text, text as sqltext
from app.database import get_db
from app.models import Highlight, Tag, BookCover, ReviewLog, DailyReviewQueue
from app.schemas import HighlightOut, HighlightCreate, HighlightUpdate, ReadwiseBatchImport
from app.services.highlight_card import generate_card, fetch_cover_data
from app.routes.share import get_share_token
from app.csrf import template_context
from app.template import render
from typing import Optional, List
from datetime import datetime
import math
import hashlib
import random
import re
import time


def _escape_ilike(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

router = APIRouter(tags=["highlights"])


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
        except Exception as e:
            print(f"  FTS search error: {e}")
            query = query.where(Highlight.id == -1)  # No results
    if source and source != "all":
        query = query.where(Highlight.source_type == source)
    if book:
        query = query.where(Highlight.book_title.ilike(f"%{_escape_ilike(book)}%", escape="\\"))
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

    return render(
        request,
        "highlights.html",
        template_context(
            request,
            active_page="highlights",
            highlights=hl_list,
            search=search,
            source_filter=source,
            book=book,
            favorites_filter=favorites,
            page=page,
            total_pages=total_pages,
            total_count=total,
        ),
    )


# ---- API ----

@router.post("/api/highlights", response_model=HighlightOut)
async def create_highlight(
    data: HighlightCreate,
    db: AsyncSession = Depends(get_db),
):
    # Check fingerprint dedup
    text = (data.text or "").strip()
    book_title = data.book_title or "Untitled"
    book_author = data.book_author or ""
    fp = hashlib.sha256(
        f"{text}|{book_title}|{book_author}".encode("utf-8")
    ).hexdigest()
    result = await db.execute(
        sqltext("SELECT id FROM highlights WHERE fingerprint = :fp"),
        {"fp": fp},
    )
    existing = result.one_or_none()
    if existing:
        result = await db.execute(
            select(Highlight).where(Highlight.id == existing[0])
        )
        return result.scalar_one()

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
        share_token=get_share_token(),
        fingerprint=fp,
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
    book_title: Optional[str] = "",
    db: AsyncSession = Depends(get_db),
):
    if search and search.strip():
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
    if book_title:
        query = query.where(Highlight.book_title == book_title)
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
    offset: int = 0,
    limit: int = 10000,
    db: AsyncSession = Depends(get_db),
):
    """Export highlights grouped by book for Obsidian sync.
    
    When ``since`` is provided, returns ALL highlights for books that have
    ANY highlights created after that timestamp — not just the new ones.
    This lets client plugins overwrite per-book files safely without losing
    previously synced highlights.
    """
    base_q = select(Highlight).order_by(Highlight.book_title, Highlight.highlighted_at)

    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            # Find books with any highlights after since_dt
            changed_books_q = (
                select(Highlight.book_title)
                .where(Highlight.created_at >= since_dt)
                .distinct()
            )
            result = await db.execute(changed_books_q)
            changed_titles = [row[0] for row in result.fetchall()]
            if changed_titles:
                base_q = base_q.where(Highlight.book_title.in_(changed_titles))
            else:
                base_q = base_q.where(sqltext("1=0"))
        except (ValueError, TypeError):
            pass

    count_q = select(sa_func.count()).select_from(base_q.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    result = await db.execute(base_q.offset(offset).limit(limit))
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
        "total": total,
        "total_books": len(books),
        "offset": offset,
        "limit": limit,
    }


@router.delete("/api/highlights/{hl_id}")
async def delete_highlight(hl_id: int, db: AsyncSession = Depends(get_db)):
    hl = await db.get(Highlight, hl_id)
    if hl:
        # Detach hl and its loaded reviews from the session so ORM flush
        # doesn't try to cascade or update child rows (all FKs are NOT NULL).
        db.expunge(hl)
        for r in list(hl.reviews):
            db.expunge(r)
        # Delete child rows first, then the highlight itself
        await db.execute(
            ReviewLog.__table__.delete().where(ReviewLog.highlight_id == hl_id)
        )
        await db.execute(
            DailyReviewQueue.__table__.delete().where(DailyReviewQueue.highlight_id == hl_id)
        )
        await db.execute(
            Highlight.__table__.delete().where(Highlight.__table__.c.id == hl_id)
        )
        await db.commit()
    return {"ok": True}


@router.post("/api/highlights/{hl_id}/favorite")
async def toggle_favorite(hl_id: int, db: AsyncSession = Depends(get_db)):
    hl = await db.get(Highlight, hl_id)
    if not hl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Highlight not found")
    hl.favorite = 0 if hl.favorite else 1
    await db.commit()
    return {"id": hl_id, "favorite": hl.favorite}


@router.put("/api/highlights/{hl_id}")
async def update_highlight(hl_id: int, data: HighlightUpdate, db: AsyncSession = Depends(get_db)):
    hl = await db.get(Highlight, hl_id)
    if not hl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Highlight not found")

    update_data = data.model_dump(exclude_unset=True)
    tag_names = update_data.pop("tags", None)

    # Drop FTS AU trigger to avoid content-matching issues
    await db.execute(sqltext("DROP TRIGGER IF EXISTS highlights_au"))

    # Build SET clause from non-None fields
    set_parts = []
    params = {"id": hl_id}
    for key in ("text", "note", "page", "chapter", "book_title", "book_author"):
        if key in update_data:
            set_parts.append(f"{key} = :{key}")
            params[key] = update_data[key]

    if set_parts:
        await db.execute(
            sqltext(f"UPDATE highlights SET {', '.join(set_parts)} WHERE id = :id"),
            params,
        )

    # Handle tags (need to manage highlight_tags junction table)
    if tag_names is not None:
        # Remove existing tag associations
        await db.execute(
            sqltext("DELETE FROM highlight_tags WHERE highlight_id = :id"),
            {"id": hl_id},
        )
        for tag_name in tag_names:
            tag_name = tag_name.strip()
            if not tag_name:
                continue
            # Upsert tag
            result = await db.execute(
                sqltext("SELECT id FROM tags WHERE name = :name"),
                {"name": tag_name},
            )
            row = result.one_or_none()
            if row:
                tag_id = row[0]
            else:
                result = await db.execute(
                    sqltext("INSERT INTO tags (name) VALUES (:name) RETURNING id"),
                    {"name": tag_name},
                )
                tag_id = result.scalar_one()
            await db.execute(
                sqltext("INSERT OR IGNORE INTO highlight_tags (highlight_id, tag_id) VALUES (:hid, :tid)"),
                {"hid": hl_id, "tid": tag_id},
            )

    # Rebuild FTS for this highlight
    row = await db.execute(
        sqltext("SELECT id, text, note, book_title, book_author FROM highlights WHERE id = :id"),
        {"id": hl_id},
    )
    hl_row = row.one_or_none()
    if hl_row:
        await db.execute(sqltext(
            "DELETE FROM highlights_fts WHERE rowid = :id"
        ), {"id": hl_id})
        await db.execute(sqltext(
            "INSERT INTO highlights_fts(rowid, text, note, book_title, book_author) "
            "VALUES (:id, :text, :note, :book_title, :book_author)"
        ), {
            "id": hl_row.id, "text": hl_row.text or "",
            "note": hl_row.note or "", "book_title": hl_row.book_title or "",
            "book_author": hl_row.book_author or "",
        })

    # Recreate FTS AU trigger
    await db.execute(sqltext(
        "CREATE TRIGGER highlights_au AFTER UPDATE OF text, note, book_title, book_author ON highlights BEGIN "
        "  INSERT INTO highlights_fts(highlights_fts, rowid, text, note, book_title, book_author) "
        "  VALUES ('delete', old.id, old.text, old.note, old.book_title, old.book_author); "
        "  INSERT INTO highlights_fts(rowid, text, note, book_title, book_author) "
        "  VALUES (new.id, new.text, new.note, new.book_title, new.book_author); "
        "END"
    ))

    await db.commit()
    return {"ok": True, "id": hl_id}


@router.get("/api/highlights/random")
async def random_highlight(db: AsyncSession = Depends(get_db)):
    """Return a single random highlight (for highlight-of-the-day display)."""
    result = await db.execute(select(sa_func.count(Highlight.id)))
    total = result.scalar() or 0
    if total == 0:
        return None
    offset = random.randint(0, total - 1)
    hl_result = await db.execute(select(Highlight).offset(offset).limit(1))
    hl = hl_result.scalar_one_or_none()
    if not hl:
        return None
    return {
        "id": hl.id,
        "text": hl.text,
        "note": hl.note,
        "book_title": hl.book_title,
        "book_author": hl.book_author or "",
        "favorite": hl.favorite,
        "created_at": hl.created_at.isoformat() if hl.created_at else None,
    }


@router.get("/api/highlights/{hl_id}")
async def get_highlight(hl_id: int, db: AsyncSession = Depends(get_db)):
    """Return a single highlight with its tags."""
    hl = await db.get(Highlight, hl_id)
    if not hl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Highlight not found")
    return {
        "id": hl.id,
        "text": hl.text,
        "book_title": hl.book_title,
        "book_author": hl.book_author,
        "tags": [t.name for t in hl.tags],
        "favorite": hl.favorite,
    }


# ── Rate limiting for context queries ──

_CONTEXT_LIMIT: dict = {}
_CONTEXT_MAX_PER_MIN = 30


def _check_context_rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = 60
    _CONTEXT_LIMIT[ip] = [t for t in _CONTEXT_LIMIT.get(ip, []) if now - t < window]
    if len(_CONTEXT_LIMIT[ip]) >= _CONTEXT_MAX_PER_MIN:
        raise HTTPException(status_code=429, detail="Too many context requests.")
    _CONTEXT_LIMIT[ip].append(now)


@router.get("/api/highlights/{hl_id}/context")
async def highlight_context(hl_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Return up to 5 highlights before and after the given highlight within the same book."""
    _check_context_rate_limit(request)

    hl = await db.get(Highlight, hl_id)
    if not hl:
        raise HTTPException(status_code=404, detail="Highlight not found")

    title = hl.book_title or ""
    author = hl.book_author or ""

    # All highlights from the same book, ordered by highlighted_at then id
    rows = await db.execute(
        sqltext(
            "SELECT id, text, note, book_title, book_author, page, chapter, "
            "highlighted_at, favorite, share_token "
            "FROM highlights "
            "WHERE book_title = :title AND (book_author = :author OR (book_author IS NULL AND :author = '')) "
            "ORDER BY highlighted_at ASC, id ASC"
        ),
        {"title": title, "author": author},
    )
    book_hls = rows.mappings().all()

    # Find index of the requested highlight
    idx = None
    for i, row in enumerate(book_hls):
        if row["id"] == hl_id:
            idx = i
            break

    if idx is None:
        return {"before": [], "current": _serialize_context_hl(hl), "after": []}

    before = [_serialize_context_row(r) for r in book_hls[max(0, idx - 5) : idx]]
    after = [_serialize_context_row(r) for r in book_hls[idx + 1 : idx + 6]]
    current = _serialize_context_row(book_hls[idx])

    return {"before": before, "current": current, "after": after}


def _serialize_context_row(row) -> dict:
    raw_date = row["highlighted_at"]
    formatted_date = None
    if raw_date is not None:
        if isinstance(raw_date, str):
            try:
                formatted_date = datetime.fromisoformat(raw_date).strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                formatted_date = raw_date[:16] if len(raw_date) >= 16 else raw_date
        else:
            formatted_date = raw_date.strftime("%Y-%m-%d %H:%M")
    return {
        "id": row["id"],
        "text": row["text"],
        "note": row["note"],
        "book_title": row["book_title"],
        "book_author": row["book_author"],
        "page": row["page"],
        "chapter": row["chapter"],
        "favorite": bool(row["favorite"]),
        "share_token": row["share_token"],
        "highlighted_at": formatted_date,
    }


def _serialize_context_hl(hl) -> dict:
    return {
        "id": hl.id,
        "text": hl.text,
        "note": hl.note,
        "book_title": hl.book_title,
        "book_author": hl.book_author,
        "page": hl.page,
        "chapter": hl.chapter,
        "favorite": bool(hl.favorite),
        "share_token": hl.share_token,
        "highlighted_at": hl.highlighted_at.strftime("%Y-%m-%d %H:%M") if hl.highlighted_at else None,
    }


@router.get("/api/highlights/{hl_id}/card")
async def highlight_card(hl_id: int, db: AsyncSession = Depends(get_db)):
    hl = await db.get(Highlight, hl_id)
    if not hl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Highlight not found")

    # Look up cover image
    cover_uri = None
    if hl.book_title:
        cover_result = await db.execute(
            select(BookCover).where(
                BookCover.book_title == hl.book_title,
                BookCover.book_author == (hl.book_author or ""),
            )
        )
        cover = cover_result.scalar_one_or_none()
        if cover and cover.cover_url:
            cover_uri = await fetch_cover_data(cover.cover_url)

    svg = generate_card(
        highlight_text=hl.text or "",
        book_title=hl.book_title or "",
        book_author=hl.book_author or "",
        note=hl.note or "",
        highlight_id=hl.id,
        cover_data_uri=cover_uri,
    )
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/api/highlights/{hl_id}/cover-image")
async def highlight_cover_image(hl_id: int, db: AsyncSession = Depends(get_db)):
    """Return the book cover image for a highlight (raw bytes)."""
    hl = await db.get(Highlight, hl_id)
    if not hl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if not hl.book_title:
        raise HTTPException(status_code=404, detail="No book title")

    cover_result = await db.execute(
        select(BookCover).where(
            BookCover.book_title == hl.book_title,
            BookCover.book_author == (hl.book_author or ""),
        )
    )
    cover = cover_result.scalar_one_or_none()
    if not cover or not cover.cover_url:
        raise HTTPException(status_code=404, detail="No cover")

    uri = await fetch_cover_data(cover.cover_url)
    if not uri or not uri.startswith("data:image/"):
        raise HTTPException(status_code=404, detail="Cover not available")

    # Decode the data URI to raw bytes
    import base64
    mime = uri.split(";")[0].split(":")[1] if ";" in uri else "image/png"
    b64 = uri.split(",")[1] if "," in uri else ""
    try:
        raw = base64.b64decode(b64)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decode cover")

    return Response(content=raw, media_type=mime)


@router.post("/api/highlights/batch")
async def batch_import(
    data: ReadwiseBatchImport,
    db: AsyncSession = Depends(get_db),
):
    """Batch import highlights (Readwise-compatible format).

    Accepts an array of ``HighlightCreate`` items. Each item is
    fingerprinted for dedup (SHA256 of ``text|book_title|book_author``).
    Returns per-item results so the caller can distinguish new imports
    from skipped duplicates.

    Useful for BookOrbit sync and other bulk import tools.
    """
    imported = 0
    skipped = 0
    errors = 0
    items = []

    for i, hl_data in enumerate(data.highlights):
        try:
            # Compute fingerprint
            text = (hl_data.text or "").strip()
            book_title = hl_data.book_title or "Untitled"
            book_author = hl_data.book_author or ""
            fp = hashlib.sha256(
                f"{text}|{book_title}|{book_author}".encode("utf-8")
            ).hexdigest()

            # Check fingerprint
            result = await db.execute(
                sqltext("SELECT id FROM highlights WHERE fingerprint = :fp"),
                {"fp": fp},
            )
            if result.one_or_none():
                skipped += 1
                items.append({"index": i, "status": "skipped", "reason": "fingerprint_match"})
                continue

            # Create highlight (reuse ORM logic inline since we need
            # granular control per-item in a batch context)
            hl = Highlight(
                text=hl_data.text,
                note=hl_data.note,
                page=hl_data.page,
                chapter=hl_data.chapter,
                source_type=hl_data.source_type,
                source_id=hl_data.source_id,
                book_title=hl_data.book_title,
                book_author=hl_data.book_author,
                book_url=hl_data.book_url,
                category=hl_data.category or "books",
                color=hl_data.color,
                highlighted_at=hl_data.highlighted_at or datetime.utcnow(),
                share_token=get_share_token(),
                fingerprint=fp,
            )

            if hl_data.tags:
                for tag_name in hl_data.tags:
                    tag_result = await db.execute(
                        select(Tag).where(Tag.name == tag_name)
                    )
                    tag = tag_result.scalar_one_or_none()
                    if not tag:
                        tag = Tag(name=tag_name)
                        db.add(tag)
                    hl.tags.append(tag)

            db.add(hl)
            await db.flush()
            imported += 1
            items.append({"index": i, "status": "imported", "id": hl.id})

        except Exception as e:
            errors += 1
            items.append({"index": i, "status": "error", "error": str(e)})

    await db.commit()
    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "total": len(data.highlights),
        "items": items,
    }

