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
from zoneinfo import ZoneInfo
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
    file: UploadFile = File(None),
    content: str = Form(default=""),
    dry_run: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    csrf_guard(request, csrf_token)
    all_highlights = []
    errors = []
    is_dry_run = dry_run == "true"
    pasted = ""
    raw = ""

    if content.strip():
        try:
            parsed = parse_readwise_md(content, "pasted-content")
            all_highlights.extend(parsed)
            pasted = content
        except Exception as e:
            errors.append(f"Failed to parse pasted content: {e}")
        source_name = "Pasted Readwise content"
    elif file:
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
    else:
        errors.append("No file or content provided")
        source_name = "unknown"

    result = ImportResult(errors=errors) if errors else \
        await ImportService.save_highlights(
            db, all_highlights,
            source_name=source_name,
            source_type="readwise",
            dry_run=is_dry_run,
        )

    # For dry runs with files, carry the raw content through so the
    # "Looks good" confirmation form can re-submit it as hidden content.
    if is_dry_run and raw and not pasted:
        pasted = raw

    return await _render_import(
        request, db,
        _build_result(result, source_name, "readwise", "/import/readwise", pasted),
    )


@router.post("/import/koreader-json")
async def import_koreader_json(
    request: Request,
    csrf_token: str = Form(default=""),
    file: UploadFile = File(None),
    content: str = Form(default=""),
    dry_run: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    csrf_guard(request, csrf_token)
    is_dry_run = dry_run == "true"
    raw = ""
    parsed_data = []

    if content.strip():
        # Confirmation from dry run — re-parse the serialized JSON
        try:
            parsed_data = parse_koreader_json(json.loads(content))
        except (json.JSONDecodeError, Exception) as e:
            return await _render_import(request, db, {
                "success": False, "imported": 0, "skipped": 0,
                "errors": [f"Failed to re-parse JSON: {e}"],
                "dry_run": False, "source_name": "koreader-export.json",
                "source_type": "koreader", "action": "/import/koreader-json",
            })
        source_name = "koreader-export.json"
    elif file:
        try:
            raw = await file.read()
            content_json = json.loads(raw)
            parsed_data = parse_koreader_json(content_json)
        except json.JSONDecodeError as e:
            return await _render_import(request, db, {
                "success": False, "imported": 0, "skipped": 0,
                "errors": [f"Invalid JSON: {e}"],
                "dry_run": False, "source_name": file.filename or "unknown",
                "source_type": "koreader", "action": "/import/koreader-json",
            })
        source_name = file.filename or "koreader-export.json"
    else:
        return await _render_import(request, db, {
            "success": False, "imported": 0, "skipped": 0,
            "errors": ["No file or content provided"],
            "dry_run": False, "source_name": "unknown",
            "source_type": "koreader", "action": "/import/koreader-json",
        })

    result = await ImportService.save_highlights(
        db, parsed_data,
        source_name=source_name,
        source_type="koreader",
        dry_run=is_dry_run,
    )

    # For dry runs, serialize the JSON back to text so the
    # "Looks good" confirmation can re-submit it as hidden content.
    pasted = ""
    if is_dry_run and raw:
        pasted = raw.decode("utf-8", errors="replace")

    return await _render_import(
        request, db,
        _build_result(result, source_name,
                       "koreader", "/import/koreader-json", pasted),
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
        source_name=f"KOReader API ({datetime.now(ZoneInfo('America/Chicago')).strftime('%Y-%m-%d %H:%M')})",
        source_type="koreader",
    )
    return {"imported": result.imported, "skipped": result.skipped}
