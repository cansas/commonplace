"""Import routes — Readwise Obsidian files, KOReader JSON, Readwise API format.

All persist logic lives in app.services.import_service.ImportService.
These routes handle parsing + rendering only.
"""

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import Source
from app.services.obsidian import parse_readwise_md
from app.services.koreader_json import parse_koreader_json
from app.services.import_service import ImportService, ImportResult
from app.schemas import ReadwiseBatchImport
from app.csrf import template_context, csrf_guard
from app.template import render
from datetime import datetime
import json

router = APIRouter(tags=["import"])




async def _render_import(request, db, import_result=None):
    """Render the import page with recent imports and optional import result."""
    result = await db.execute(
        select(Source).order_by(Source.last_import_at.desc().nullslast()).limit(10)
    )
    sources = result.scalars().all()

    return render(
        request,
        "import.html",
        template_context(
            request,
            active_page="import",
            import_result=import_result,
            recent_imports=[
                {
                    "name": s.name,
                    "source_type": s.source_type,
                    "last_import_at": s.last_import_at.strftime("%Y-%m-%d %H:%M") if s.last_import_at else "",
                    "count": s.highlights_imported or 0,
                }
                for s in sources
            ],
        ),
    )


@router.get("/import", response_class=HTMLResponse)
async def import_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    return await _render_import(request, db)


def _build_result(import_result, source_name: str, source_type: str, action: str, pasted_content: str = "") -> dict:
    """Build the result dict the import template expects."""
    r = {
        "success": len(import_result.errors) == 0,
        "imported": import_result.imported,
        "skipped": import_result.skipped,
        "errors": import_result.errors,
        "dry_run": import_result.dry_run,
        "source_name": source_name,
        "source_type": source_type,
        "action": action,
    }
    if import_result.dry_run and pasted_content:
        r["pasted_content"] = pasted_content
    return r


@router.post("/import/readwise")
async def import_readwise(
    request: Request,
    csrf_token: str = Form(default=""),
    file: UploadFile = File(...),
    content: str = Form(default=""),
    dry_run: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    csrf_guard(request, csrf_token)
    all_highlights = []
    errors = []
    is_dry_run = dry_run == "true"
    pasted = ""

    if content.strip():
        try:
            parsed = parse_readwise_md(content, "pasted-content")
            all_highlights.extend(parsed)
            pasted = content
        except Exception as e:
            errors.append(f"Failed to parse pasted content: {e}")
        source_name = "Pasted Readwise content"
    else:
        try:
            raw = (await file.read()).decode("utf-8", errors="replace")
        except Exception as e:
            errors.append(f"Failed to read file {file.filename}: {e}")
            raw = ""

        if raw and not errors:
            try:
                parsed = parse_readwise_md(raw, file.filename or "")
                all_highlights.extend(parsed)
            except Exception as e:
                errors.append(f"Failed to parse {file.filename}: {e}")

        source_name = file.filename or "unknown"

    result = ImportResult(errors=errors) if errors else \
        await ImportService.save_highlights(
            db, all_highlights,
            source_name=source_name,
            source_type="readwise",
            dry_run=is_dry_run,
        )

    return await _render_import(
        request, db,
        _build_result(result, source_name, "readwise", "/import/readwise", pasted),
    )


@router.post("/import/koreader-json")
async def import_koreader_json(
    request: Request,
    csrf_token: str = Form(default=""),
    file: UploadFile = File(...),
    dry_run: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    csrf_guard(request, csrf_token)
    is_dry_run = dry_run == "true"

    try:
        content = json.loads(await file.read())
    except json.JSONDecodeError as e:
        return await _render_import(request, db, {
            "success": False,
            "imported": 0, "skipped": 0,
            "errors": [f"Invalid JSON: {e}"],
            "dry_run": False, "source_name": file.filename or "unknown",
            "source_type": "koreader", "action": "/import/koreader-json",
        })

    parsed = parse_koreader_json(content)
    result = await ImportService.save_highlights(
        db, parsed,
        source_name=file.filename or "koreader-export.json",
        source_type="koreader",
        dry_run=is_dry_run,
    )

    return await _render_import(
        request, db,
        _build_result(result, file.filename or "koreader-export.json",
                       "koreader", "/import/koreader-json"),
    )


# Readwise-compatible API endpoint (what KOReader Readwise plugin sends)
@router.post("/api/v2/highlights")
async def readwise_api_import(
    data: ReadwiseBatchImport,
    db: AsyncSession = Depends(get_db),
):
    items = [item.model_dump() for item in data.highlights]
    result = await ImportService.save_highlights(
        db, items,
        source_name=f"KOReader API ({datetime.utcnow().strftime('%Y-%m-%d %H:%M')})",
        source_type="koreader",
    )
    return {"imported": result.imported, "skipped": result.skipped}
