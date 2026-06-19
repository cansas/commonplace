"""Tag management routes — list, rename, merge, delete tags."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete as sa_delete, text as sqltext
from app.database import get_db
from app.models import Tag, Highlight, highlight_tags
from app.csrf import template_context, csrf_guard

router = APIRouter(tags=["tags"])

_jinja = None


def init(templates):
    global _jinja
    _jinja = templates


# ── API endpoints ──────────────────────────────────────────────────────────


@router.get("/api/tags")
async def list_tags(db: AsyncSession = Depends(get_db)):
    """List all tags with highlight counts."""
    result = await db.execute(
        select(
            Tag.id,
            Tag.name,
            func.count(highlight_tags.c.highlight_id).label("count"),
        )
        .outerjoin(highlight_tags, Tag.id == highlight_tags.c.tag_id)
        .group_by(Tag.id, Tag.name)
        .order_by(Tag.name)
    )
    return [
        {"id": row.id, "name": row.name, "count": row.count}
        for row in result.all()
    ]


@router.put("/api/tags/{tag_id}")
async def rename_tag(
    tag_id: int,
    name: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Rename a tag."""
    tag = await db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if len(name) > 128:
        raise HTTPException(status_code=400, detail="Name too long")

    # Check for duplicate
    existing = await db.execute(select(Tag).where(Tag.name == name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A tag with that name already exists")

    tag.name = name
    await db.commit()
    return {"ok": True, "id": tag_id, "name": name}


@router.post("/api/tags/merge")
async def merge_tags(
    source_id: int = Form(...),
    target_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Merge source tag into target tag. Source tag is deleted."""
    if source_id == target_id:
        raise HTTPException(status_code=400, detail="Cannot merge a tag into itself")

    source = await db.get(Tag, source_id)
    target = await db.get(Tag, target_id)
    if not source or not target:
        raise HTTPException(status_code=404, detail="Tag not found")

    # Reassign all highlight_tags entries from source to target
    await db.execute(
        sqltext(
            "INSERT OR IGNORE INTO highlight_tags (highlight_id, tag_id) "
            "SELECT highlight_id, :target_id FROM highlight_tags WHERE tag_id = :source_id"
        ),
        {"target_id": target_id, "source_id": source_id},
    )
    # Remove source entries
    await db.execute(
        sa_delete(highlight_tags).where(highlight_tags.c.tag_id == source_id)
    )
    # Delete the source tag
    await db.delete(source)
    await db.commit()

    return {"ok": True, "merged_into": target.name, "target_id": target_id}


@router.delete("/api/tags/{tag_id}")
async def delete_tag(
    tag_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a tag and remove it from all highlights."""
    tag = await db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    # Remove join table entries first
    await db.execute(
        sa_delete(highlight_tags).where(highlight_tags.c.tag_id == tag_id)
    )
    await db.delete(tag)
    await db.commit()
    return {"ok": True}


@router.post("/api/highlights/{hl_id}/tags")
async def set_highlight_tags(
    hl_id: int,
    tag_ids: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Set the tags on a highlight. tag_ids is a comma-separated list of tag IDs."""
    hl = await db.get(Highlight, hl_id)
    if not hl:
        raise HTTPException(status_code=404, detail="Highlight not found")

    # Clear existing tags
    await db.execute(
        sa_delete(highlight_tags).where(highlight_tags.c.highlight_id == hl_id)
    )

    # Add new tags
    if tag_ids.strip():
        ids = [int(x) for x in tag_ids.split(",") if x.strip()]
        for tid in ids:
            await db.execute(
                sqltext(
                    "INSERT OR IGNORE INTO highlight_tags (highlight_id, tag_id) "
                    "VALUES (:hl_id, :tag_id)"
                ),
                {"hl_id": hl_id, "tag_id": tid},
            )

    await db.commit()
    return {"ok": True}


# ── UI pages ───────────────────────────────────────────────────────────────


@router.get("/tags", response_class=HTMLResponse)
async def tags_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Tag browser page."""
    result = await db.execute(
        select(
            Tag.id,
            Tag.name,
            func.count(highlight_tags.c.highlight_id).label("count"),
        )
        .outerjoin(highlight_tags, Tag.id == highlight_tags.c.tag_id)
        .group_by(Tag.id, Tag.name)
        .order_by(Tag.name)
    )
    tags = [
        {"id": row.id, "name": row.name, "count": row.count}
        for row in result.all()
    ]

    return _jinja.TemplateResponse(
        request,
        "tags.html",
        template_context(
            request,
            active_page="tags",
            tags=tags,
        ),
    )


@router.get("/tags/{tag_id}", response_class=HTMLResponse)
async def tag_detail(
    tag_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Show all highlights with a given tag."""
    tag = await db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    result = await db.execute(
        select(Highlight)
        .join(highlight_tags, Highlight.id == highlight_tags.c.highlight_id)
        .where(highlight_tags.c.tag_id == tag_id)
        .order_by(Highlight.created_at.desc())
    )
    highlights = result.scalars().all()

    return _jinja.TemplateResponse(
        request,
        "highlights.html",
        template_context(
            request,
            active_page="tags",
            highlights=highlights,
            tag_filter=tag.name,
            tag_id=tag.id,
            search="",
            book_filter="",
        ),
    )
