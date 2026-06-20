"""Books browse route — list books by title/author with highlight counts."""

from fastapi import APIRouter, Depends, Query, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sa_func, or_, text as sqltext
from app.database import get_db
from app.models import Highlight, BookCover
from app.services.book_covers import search_cover
from app.csrf import template_context
from app.services.settings_service import get_hardcover_api_key
from app.template import render
from typing import Optional
import hashlib
import math
import os
import re


def _escape_ilike(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

def _safe_filename(name: str) -> str:
    """Hash the name to avoid collisions and special chars."""
    return hashlib.md5(name.encode()).hexdigest()[:16]


router = APIRouter(tags=["books"])
COVERS_DIR = os.environ.get("COVERS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "covers"))




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
            sa_func.max(Highlight.id).label("sample_hl_id"),
        )
        .group_by(Highlight.book_title, Highlight.book_author)
    )

    if search:
        query = query.where(
            or_(
                Highlight.book_title.ilike(f"%{_escape_ilike(search)}%", escape="\\"),
                Highlight.book_author.ilike(f"%{_escape_ilike(search)}%", escape="\\"),
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

    # Bulk-fetch covers to avoid N+1
    cover_keys = [(row.book_title, row.book_author or "") for row in rows]
    cover_map = {}
    if cover_keys:
        cover_result = await db.execute(
            select(BookCover).where(
                or_(*[
                    (BookCover.book_title == t) & (BookCover.book_author == a)
                    for t, a in cover_keys
                ]) if cover_keys else False
            )
        )
        for cover in cover_result.scalars().all():
            cover_map[(cover.book_title, cover.book_author)] = cover

    books = []
    for row in rows:
        cover = cover_map.get((row.book_title, row.book_author or ""))
        books.append({
            "title": row.book_title,
            "author": row.book_author or "Unknown",
            "highlight_count": row.highlight_count,
            "last_highlighted": row.last_highlighted.strftime("%Y-%m-%d") if row.last_highlighted else "",
            "cover_url": cover.cover_url if cover else None,
            "cover_source": cover.cover_source if cover else "none",
            "highlight_id": row.sample_hl_id,
        })

    return render(
        request,
        "books.html",
        template_context(
            request,
            active_page="books",
            books=books,
            search=search,
            sort=sort,
            page=page,
            total_pages=total_pages,
            total_books=total,
        ),
    )


@router.post("/api/books/cover/fetch")
async def fetch_cover(title: str = Form(...), author: str = Form(default=""), source: str = Form(default="auto"), db: AsyncSession = Depends(get_db)):
    try:
        # Check for existing BookCover to pass known_id (skip fuzzy search)
        existing = await db.execute(
            select(BookCover).where(
                BookCover.book_title == title,
                BookCover.book_author == author,
            )
        )
        existing_cover = existing.scalar_one_or_none()
        known_id = existing_cover.hardcover_id if existing_cover else None

        hc_key = get_hardcover_api_key()
        url, cover_source, hc_id, isbn = await search_cover(title, author, hardcover_key=hc_key, known_id=known_id)
        if not url:
            return {"ok": False, "error": "No cover found on Open Library, Hardcover, or Goodreads"}

        result = await db.execute(
            select(BookCover).where(
                BookCover.book_title == title,
                BookCover.book_author == author,
            )
        )
        cover = result.scalar_one_or_none()
        if cover:
            cover.cover_url = url
            cover.cover_source = cover_source
            if hc_id is not None:
                cover.hardcover_id = hc_id
            if isbn is not None:
                cover.isbn = isbn
        else:
            db.add(BookCover(
                book_title=title, book_author=author,
                cover_url=url, cover_source=cover_source,
                hardcover_id=hc_id, isbn=isbn,
            ))
        await db.commit()
        return {"ok": True, "cover_url": url, "source": cover_source}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

# Magic bytes for image validation
_IMAGE_SIGNATURES = {
    b"\xff\xd8\xff": ".jpg",
    b"\x89PNG\r\n\x1a\n": ".png",
    b"RIFF": ".webp",  # WebP starts with RIFF
}


def _validate_image_header(data: bytes) -> str | None:
    """Check magic bytes and return detected extension, or None if invalid."""
    for sig, ext in _IMAGE_SIGNATURES.items():
        if data[:len(sig)] == sig:
            if ext == ".webp" and data[8:12] != b"WEBP":
                return None
            return ext
    return None


@router.post("/api/books/cover/upload")
async def upload_cover(title: str = Form(...), author: str = Form(default=""), file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    # Validate file extension
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        return JSONResponse({"ok": False, "error": "Only JPG, PNG, and WebP are accepted"}, status_code=400)

    # Read and validate size
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        return JSONResponse({"ok": False, "error": f"File too large ({len(content) // 1024 // 1024}MB). Max is 10MB."}, status_code=400)
    if len(content) < 100:
        return JSONResponse({"ok": False, "error": "File appears to be empty or too small"}, status_code=400)

    # Validate image magic bytes
    detected_ext = _validate_image_header(content)
    if not detected_ext:
        return JSONResponse({"ok": False, "error": "File is not a valid image (bad header bytes)"}, status_code=400)
    ext = detected_ext  # trust the actual bytes, not the extension

    # Build destination path
    dest = os.path.join(COVERS_DIR, f"{_safe_filename(title)}_{_safe_filename(author)}{ext}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    # Write file
    try:
        with open(dest, "wb") as f:
            f.write(content)
        if not os.path.isfile(dest):
            return JSONResponse({"ok": False, "error": "File write succeeded but file not found on disk"}, status_code=500)
    except OSError as e:
        return JSONResponse({"ok": False, "error": f"Failed to write file: {e}"}, status_code=500)

    cover_url = f"/static/covers/{os.path.basename(dest)}"

    # Update DB
    result = await db.execute(
        select(BookCover).where(
            BookCover.book_title == title,
            BookCover.book_author == author,
        )
    )
    cover = result.scalar_one_or_none()
    if cover:
        # Clean up old file if it exists and is different
        old_path = os.path.join(COVERS_DIR, os.path.basename(cover.cover_url or ""))
        if old_path != dest and os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass
        cover.cover_url = cover_url
        cover.cover_source = "upload"
    else:
        db.add(BookCover(book_title=title, book_author=author, cover_url=cover_url, cover_source="upload"))
    await db.commit()
    return {"ok": True, "cover_url": cover_url}


@router.post("/api/books/metadata")
async def set_book_metadata(
    title: str = Form(...),
    author: str = Form(default=""),
    hardcover_id: str = Form(default=""),
    isbn: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Manually set or update HardCover ID and ISBN for a book.

    Saves metadata to the BookCover record. If no BookCover exists yet,
    creates one. If a HardCover ID was provided, triggers an immediate
    cover lookup using that ID.
    """
    author = author or ""
    hc_id = None
    if hardcover_id.strip():
        try:
            hc_id = int(hardcover_id.strip())
        except ValueError:
            return {"ok": False, "error": "HardCover ID must be a number"}

    isbn_val = isbn.strip() or None

    result = await db.execute(
        select(BookCover).where(
            BookCover.book_title == title,
            BookCover.book_author == author,
        )
    )
    cover = result.scalar_one_or_none()
    if cover:
        cover.hardcover_id = hc_id
        cover.isbn = isbn_val
    else:
        cover = BookCover(
            book_title=title, book_author=author,
            hardcover_id=hc_id, isbn=isbn_val,
        )
        db.add(cover)
    await db.commit()

    # If a HardCover ID was set, do an immediate look-up
    url = cover.cover_url
    source = cover.cover_source
    if hc_id is not None:
        hc_key = get_hardcover_api_key()
        result = await search_cover(title, author, hardcover_key=hc_key, known_id=hc_id)
        new_url, new_source, _, _ = result
        if new_url:
            cover.cover_url = new_url
            cover.cover_source = new_source
            url = new_url
            source = new_source
            await db.commit()

    return {
        "ok": True,
        "hardcover_id": hc_id,
        "isbn": isbn_val,
        "cover_url": url,
        "cover_source": source,
    }


@router.post("/api/books/rename")
async def rename_book(
    old_title: str = Form(...),
    old_author: str = Form(default=""),
    new_title: str = Form(...),
    new_author: str = Form(default=""),
    merge: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Rename a book across all highlights. Merges if target already exists.

    If the target (new_title, new_author) already matches a different book,
    returns ``conflict: true`` with details on the first call.  On a second
    call with ``merge=true``, all highlights from the source book are
    reassigned to the existing target book (they merge naturally since they
    share the same title/author after the UPDATE), and the old BookCover
    is cleaned up.
    """
    if not new_title.strip():
        return JSONResponse({"ok": False, "error": "New title is required"}, status_code=400)

    old_author = old_author or ""
    new_author = new_author or ""
    do_merge = merge.strip().lower() == "true"

    # Count source highlights
    src_count = await db.execute(
        select(sa_func.count(Highlight.id)).where(
            Highlight.book_title == old_title,
            Highlight.book_author == old_author,
        )
    )
    affected = src_count.scalar() or 0

    if affected == 0:
        return JSONResponse({"ok": False, "error": "No highlights found with that title"}, status_code=404)

    # Check if target already exists (different book, same title/author)
    target_exists = False
    target_count = 0
    if new_title.strip() != old_title or new_author != old_author:
        tgt = await db.execute(
            select(sa_func.count(Highlight.id)).where(
                Highlight.book_title == new_title.strip(),
                Highlight.book_author == new_author,
            )
        )
        target_count = tgt.scalar() or 0
        target_exists = target_count > 0

    # If there's a conflict and user hasn't confirmed merge, ask
    if target_exists and not do_merge:
        return {
            "ok": False,
            "conflict": True,
            "existing_count": target_count,
            "new_title": new_title.strip(),
            "new_author": new_author,
            "message": f"\"{new_title.strip()}\" already exists with {target_count} highlight{'s' if target_count != 1 else ''}. "
                       f"Merge {affected} highlight{'s' if affected != 1 else ''} into it?",
        }

    # Temporarily drop the FTS AU trigger
    await db.execute(sqltext("DROP TRIGGER IF EXISTS highlights_au"))

    # Bulk rename (or merge — same operation: set all old titles to new values)
    await db.execute(
        sqltext(
            "UPDATE highlights SET book_title = :new_title, book_author = :new_author "
            "WHERE book_title = :old_title AND book_author = :old_author"
        ),
        {
            "new_title": new_title.strip(),
            "new_author": new_author,
            "old_title": old_title,
            "old_author": old_author,
        },
    )

    # Recreate the FTS AU trigger
    await db.execute(sqltext(
        "CREATE TRIGGER highlights_au AFTER UPDATE OF text, note, book_title, book_author ON highlights BEGIN "
        "  INSERT INTO highlights_fts(highlights_fts, rowid, text, note, book_title, book_author) "
        "  VALUES ('delete', old.id, old.text, old.note, old.book_title, old.book_author); "
        "  INSERT INTO highlights_fts(rowid, text, note, book_title, book_author) "
        "  VALUES (new.id, new.text, new.note, new.book_title, new.book_author); "
        "END"
    ))

    # Manually sync FTS for the target book — delete stale and re-insert
    # (DELETE+INSERT on individual rows can fail if FTS content doesn't
    # match exactly after a bulk UPDATE; a full clear+rebuild is simpler)
    await db.execute(sqltext("DELETE FROM highlights_fts"))
    await db.execute(sqltext(
        "INSERT INTO highlights_fts(rowid, text, note, book_title, book_author) "
        "SELECT id, text, note, book_title, book_author FROM highlights"
    ))

    # BookCover — if merge, prefer the existing target cover and remove the old
    if target_exists:
        # Delete old source cover (target cover already exists or will persist)
        await db.execute(
            sqltext("DELETE FROM book_covers WHERE book_title = :t AND book_author = :a"),
            {"t": old_title, "a": old_author},
        )
    else:
        # Simple rename: update the old cover to the new title
        cover = await db.execute(
            select(BookCover).where(
                BookCover.book_title == old_title,
                BookCover.book_author == old_author,
            )
        )
        cover_row = cover.scalar_one_or_none()
        if cover_row:
            cover_row.book_title = new_title.strip()
            cover_row.book_author = new_author

    await db.commit()

    total = affected + (target_count if target_exists else 0)
    msg = f"Merged {total} highlights" if target_exists else f"Renamed {affected} highlight{'s' if affected != 1 else ''}"

    return {
        "ok": True,
        "merged": target_exists,
        "affected": total,
        "old_title": old_title,
        "new_title": new_title.strip(),
        "message": msg,
    }


@router.post("/api/books/delete")
async def delete_book(
    title: str = Form(...),
    author: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Delete an entire book and all its highlights, with a two-step confirmation."""
    author = author or ""

    # Count what we're about to delete
    count_result = await db.execute(
        select(sa_func.count(Highlight.id)).where(
            Highlight.book_title == title,
            Highlight.book_author == author,
        )
    )
    count = count_result.scalar() or 0

    if count == 0:
        return JSONResponse({"ok": False, "error": "No highlights found for that book"}, status_code=404)

    # Drop FTS triggers to avoid content-matching issues during bulk delete
    await db.execute(sqltext("DROP TRIGGER IF EXISTS highlights_ai"))
    await db.execute(sqltext("DROP TRIGGER IF EXISTS highlights_ad"))
    await db.execute(sqltext("DROP TRIGGER IF EXISTS highlights_au"))

    # Delete highlights (no triggers to interfere)
    await db.execute(
        sqltext("DELETE FROM highlights WHERE book_title = :t AND book_author = :a"),
        {"t": title, "a": author},
    )

    # Delete BookCover
    await db.execute(
        sqltext("DELETE FROM book_covers WHERE book_title = :t AND book_author = :a"),
        {"t": title, "a": author},
    )

    # Rebuild FTS index from scratch (simpler than per-row deletion)
    await db.execute(sqltext("DELETE FROM highlights_fts"))
    await db.execute(sqltext(
        "INSERT INTO highlights_fts(rowid, text, note, book_title, book_author) "
        "SELECT id, text, note, book_title, book_author FROM highlights"
    ))

    # Recreate FTS triggers
    await db.execute(sqltext(
        "CREATE TRIGGER IF NOT EXISTS highlights_ai AFTER INSERT ON highlights BEGIN "
        "  INSERT INTO highlights_fts(rowid, text, note, book_title, book_author) "
        "  VALUES (new.id, new.text, new.note, new.book_title, new.book_author); "
        "END"
    ))
    await db.execute(sqltext(
        "CREATE TRIGGER IF NOT EXISTS highlights_ad AFTER DELETE ON highlights BEGIN "
        "  INSERT INTO highlights_fts(highlights_fts, rowid, text, note, book_title, book_author) "
        "  VALUES ('delete', old.id, old.text, old.note, old.book_title, old.book_author); "
        "END"
    ))
    await db.execute(sqltext(
        "CREATE TRIGGER highlights_au AFTER UPDATE OF text, note, book_title, book_author ON highlights BEGIN "
        "  INSERT INTO highlights_fts(highlights_fts, rowid, text, note, book_title, book_author) "
        "  VALUES ('delete', old.id, old.text, old.note, old.book_title, old.book_author); "
        "  INSERT INTO highlights_fts(rowid, text, note, book_title, book_author) "
        "  VALUES (new.id, new.text, new.note, new.book_title, new.book_author); "
        "END"
    ))

    await db.commit()
    return {"ok": True, "deleted": count, "title": title}


@router.post("/api/books/cover/backfill")
async def backfill_covers(db: AsyncSession = Depends(get_db)):
    hc_key = get_hardcover_api_key()
    result = await db.execute(
        select(Highlight.book_title, Highlight.book_author)
        .distinct()
    )
    books = result.all()

    # Bulk check which books already have covers — one query, not N
    existing_result = await db.execute(
        select(BookCover.book_title, BookCover.book_author)
    )
    existing_covers = {
        (r.book_title, r.book_author) for r in existing_result.all()
    }

    # Pre-load existing BookCover records that have hardcover_id
    existing_detail = await db.execute(
        select(BookCover)
    )
    cover_map = {
        (c.book_title, c.book_author): c for c in existing_detail.scalars().all()
    }

    fetched = 0
    for row in books:
        key = (row.book_title, row.book_author or "")
        cover_row = cover_map.get(key)

        if cover_row and cover_row.hardcover_id is not None:
            continue  # Already has an ID, skip fuzzy search

        if key in existing_covers and not cover_row:
            continue  # Already has a basic cover (no row in map edge case)

        known_id = cover_row.hardcover_id if cover_row else None
        url, cover_source, hc_id, isbn = await search_cover(
            row.book_title, row.book_author or "",
            hardcover_key=hc_key, known_id=known_id,
        )
        if url:
            if cover_row:
                cover_row.cover_url = url
                cover_row.cover_source = cover_source
                if hc_id is not None:
                    cover_row.hardcover_id = hc_id
                if isbn is not None:
                    cover_row.isbn = isbn
            else:
                db.add(BookCover(
                    book_title=row.book_title,
                    book_author=row.book_author or "",
                    cover_url=url, cover_source=cover_source,
                    hardcover_id=hc_id, isbn=isbn,
                ))
            fetched += 1
            await db.commit()
    return {"ok": True, "fetched": fetched}


@router.post("/api/books/cover/fetch/{hl_id}")
async def fetch_cover_by_hl(hl_id: int, db: AsyncSession = Depends(get_db)):
    hl = await db.get(Highlight, hl_id)
    if not hl:
        return {"ok": False, "error": "Highlight not found"}
    return await fetch_cover(title=hl.book_title, author=hl.book_author or "", source="auto", db=db)


@router.post("/api/books/cover/upload/{hl_id}")
async def upload_cover_by_hl(hl_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    hl = await db.get(Highlight, hl_id)
    if not hl:
        return JSONResponse({"ok": False, "error": "Highlight not found"}, status_code=404)
    return await upload_cover(title=hl.book_title, author=hl.book_author or "", file=file, db=db)
