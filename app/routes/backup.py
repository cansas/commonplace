"""Backup & Restore routes — ZIP download of DB + covers, and restore from ZIP."""

import io
import os
import zipfile
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, RedirectResponse
from starlette.responses import Response

from app.database import DATABASE_URL, async_session
from app.csrf import template_context, csrf_guard
from app.template import render

router = APIRouter(tags=["backup"])

# DB path from the DATABASE_URL
# Format: sqlite+aiosqlite:////app/data/commonplace.db
# Extract the path after the triple slash
_DB_PATH = DATABASE_URL.replace("sqlite+aiosqlite:///", "", 1)
if _DB_PATH.startswith("/"):
    pass  # Already absolute
elif _DB_PATH.startswith("///"):
    _DB_PATH = _DB_PATH[2:]  # Strip extra slashes

# Covers dir
_COVERS_DIR = os.environ.get(
    "COVERS_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "covers"),
)




def _backup_filename() -> str:
    """Generate a backup filename with today's date."""
    date_str = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    return f"commonplace-{date_str}.zip"


@router.get("/api/backup")
async def download_backup(request: Request):
    """Download a ZIP containing the SQLite database and cover images."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add the database file
        if os.path.isfile(_DB_PATH):
            zf.write(_DB_PATH, "commonplace.db")
        else:
            raise HTTPException(status_code=500, detail="Database file not found on disk")

        # Add cover images
        if os.path.isdir(_COVERS_DIR):
            for entry in os.listdir(_COVERS_DIR):
                file_path = os.path.join(_COVERS_DIR, entry)
                if os.path.isfile(file_path):
                    zf.write(file_path, os.path.join("covers", entry))

    buf.seek(0)
    filename = _backup_filename()

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/backup/restore")
async def restore_backup(
    request: Request,
    file: UploadFile = File(...),
    csrf_token: str = Form(default=""),
):
    """Restore from a ZIP backup file. Replaces the current database."""
    csrf_guard(request, csrf_token)

    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted")

    contents = await file.read()

    # Track what we extracted
    has_db = False
    covers_dir_restored = False
    covers_count = 0

    try:
        zf = zipfile.ZipFile(io.BytesIO(contents), "r")
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP file")

    # Validate that the ZIP contains a .db file
    names = zf.namelist()
    db_in_zip = any(n.endswith(".db") for n in names)
    if not db_in_zip:
        raise HTTPException(status_code=400, detail="ZIP file must contain a .db file")

    # Backup the current database before replacing
    bak_path = _DB_PATH + ".bak" if os.path.isfile(_DB_PATH) else None
    if bak_path:
        shutil.copy2(_DB_PATH, bak_path)

    try:
        # Validate each path stays within the target directory (zip slip prevention)
        db_dir = os.path.dirname(_DB_PATH)
        for name in names:
            resolved = os.path.realpath(os.path.join(db_dir, name))
            if not resolved.startswith(os.path.realpath(db_dir) + os.sep) and resolved != os.path.realpath(db_dir):
                raise HTTPException(
                    status_code=400,
                    detail=f"ZIP entry '{name}' attempts path traversal — rejected",
                )

        # Extract to a temporary location first, then swap
        zf.extractall(path=db_dir)

        # Rename extracted db if the zip contains it at root
        for name in names:
            if name.endswith(".db"):
                extracted_db = os.path.join(db_dir, name)
                if extracted_db != _DB_PATH and os.path.isfile(extracted_db):
                    # Move extracted db to the expected location
                    if os.path.isfile(_DB_PATH):
                        os.remove(_DB_PATH)
                    shutil.move(extracted_db, _DB_PATH)
                has_db = True
                break

        # Extract covers if present
        for name in names:
            if name.startswith("covers/") or name.startswith("covers\\"):
                covers_count += 1
                if not covers_dir_restored:
                    os.makedirs(_COVERS_DIR, exist_ok=True)
                    covers_dir_restored = True

    except Exception as e:
        # Restore from backup on failure
        if os.path.isfile(bak_path):
            shutil.copy2(bak_path, _DB_PATH)
        raise HTTPException(status_code=500, detail=f"Restore failed: {str(e)}")
    finally:
        # Clean up .bak file
        if bak_path and os.path.isfile(bak_path):
            try:
                os.remove(bak_path)
            except Exception:
                pass

    if not has_db:
        raise HTTPException(status_code=400, detail="Could not find a .db file in the archive")

    return {
        "ok": True,
        "restored_db": os.path.basename(_DB_PATH),
        "restored_covers": covers_count,
        "message": "Database restored. A restart is recommended for FTS index consistency.",
    }
