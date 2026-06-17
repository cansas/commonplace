"""Import routes — Readwise Obsidian files, KOReader JSON, Readwise API format."""

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import Highlight, Source
from app.services.obsidian import parse_readwise_md
from app.services.koreader_json import parse_koreader_json
from app.schemas import HighlightCreate, ReadwiseBatchImport
from app.routes.share import get_share_token
from typing import List
from datetime import datetime
import json

router = APIRouter(tags=["import"])

_jinja = None


def init(templates):
    global _jinja
    _jinja = templates


@router.get("/import", response_class=HTMLResponse)
async def import_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Source).order_by(Source.last_import_at.desc().nullslast()).limit(10)
    )
    sources = result.scalars().all()

    return _jinja.TemplateResponse(
        request,
        "import.html",
        {
            "active_page": "import",
            "recent_imports": [
                {
                    "name": s.name,
                    "source_type": s.source_type,
                    "last_import_at": s.last_import_at.strftime("%Y-%m-%d %H:%M") if s.last_import_at else "",
                    "count": s.highlights_imported or 0,
                }
                for s in sources
            ],
        },
    )


async def _is_duplicate(db, text, book_title, highlighted_at):
    """Check if a highlight with the same text, book, and timestamp already exists."""
    from sqlalchemy import and_
    result = await db.execute(
        select(Highlight).where(
            and_(
                Highlight.text == text,
                Highlight.book_title == book_title,
                Highlight.highlighted_at == highlighted_at,
            )
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _save_highlights(db, highlights_list, source_name, source_type):
    """Bulk-save highlights and record source. Skips duplicates."""
    count = 0
    skipped = 0
    for item in highlights_list:
        text = item["text"]
        book_title = item.get("book_title", "Untitled")
        highlighted_at = item.get("highlighted_at")

        if await _is_duplicate(db, text, book_title, highlighted_at):
            skipped += 1
            continue

        hl = Highlight(
            text=text,
            note=item.get("note"),
            page=item.get("page"),
            chapter=item.get("chapter"),
            source_type=source_type,
            book_title=book_title,
            book_author=item.get("book_author"),
            category=item.get("category", "books"),
            color=item.get("color"),
            highlighted_at=highlighted_at or datetime.utcnow(),
            share_token=get_share_token(),
        )
        db.add(hl)
        count += 1

    # Record the import source
    src = Source(
        name=source_name,
        source_type=source_type,
        last_import_at=datetime.utcnow(),
        highlights_imported=count,
    )
    db.add(src)
    await db.commit()
    return count


@router.post("/import/readwise")
async def import_readwise(
    request: Request,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    all_highlights = []
    source_names = []
    for f in files:
        content = (await f.read()).decode("utf-8", errors="replace")
        parsed = parse_readwise_md(content, f.filename or "")
        all_highlights.extend(parsed)
        source_names.append(f.filename or "unknown")

    count = await _save_highlights(
        db, all_highlights,
        source_name=", ".join(source_names),
        source_type="readwise",
    )

    return RedirectResponse(url=f"/?imported={count}", status_code=303)


@router.post("/import/koreader-json")
async def import_koreader_json(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    content = json.loads(await file.read())
    parsed = parse_koreader_json(content)

    count = await _save_highlights(
        db, parsed,
        source_name=file.filename or "koreader-export.json",
        source_type="koreader",
    )

    return RedirectResponse(url=f"/?imported={count}", status_code=303)


# Readwise-compatible API endpoint (what KOReader Readwise plugin sends)
@router.post("/api/v2/highlights")
async def readwise_api_import(
    data: ReadwiseBatchImport,
    db: AsyncSession = Depends(get_db),
):
    count = 0
    skipped = 0
    for item in data.highlights:
        text = item.text
        book_title = item.book_title or "Untitled"
        highlighted_at = item.highlighted_at

        if await _is_duplicate(db, text, book_title, highlighted_at):
            skipped += 1
            continue

        hl = Highlight(
            text=text,
            note=item.note,
            page=item.page,
            chapter=item.chapter,
            source_type=item.source_type or "koreader",
            source_id=item.source_id,
            book_title=book_title,
            book_author=item.book_author,
            book_url=item.book_url,
            category=item.category or "books",
            color=item.color,
            highlighted_at=highlighted_at or datetime.utcnow(),
            share_token=get_share_token(),
        )
        db.add(hl)
        count += 1

    src = Source(
        name=f"KOReader API ({datetime.utcnow().strftime('%Y-%m-%d %H:%M')})",
        source_type="koreader",
        last_import_at=datetime.utcnow(),
        highlights_imported=count,
    )
    db.add(src)
    await db.commit()

    return {"imported": count, "skipped": skipped}
