"""Import pipeline — dedup, persist, track.

Consolidates the duplicated dedup+save logic from import_routes.py.
Fixes the broken dedup key (was (text, book_title, highlighted_at) which
created duplicates on re-import with different timestamps) by using a
deterministic SHA256 fingerprint.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Highlight, Source
from app.routes.share import get_share_token


@dataclass
class ImportResult:
    """Structured result from an import operation."""
    imported: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)
    dry_run: bool = False


def highlight_fingerprint(text: str, book_title: str) -> str:
    """Deterministic hash for dedup.

    Same (text, book_title) always produces the same hash regardless
    of timestamp — so re-importing a highlight on a different day
    correctly skips it.
    """
    raw = f"{book_title}\x00{text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class DedupService:
    """Batch dedup against the fingerprint index.

    Usage::

        dedup = DedupService(items)
        await dedup.check(db)
        for i, item in enumerate(items):
            if dedup.is_duplicate(i):
                continue
    """

    def __init__(self, items: List[dict]):
        self.items = items
        self.fingerprints: List[str] = []
        self.existing: set = set()

        for item in items:
            text = item.get("text", "")
            title = item.get("book_title", "Untitled")
            self.fingerprints.append(highlight_fingerprint(text, title))

    async def check(self, db: AsyncSession) -> None:
        """Batch-query which fingerprints already exist in the DB."""
        if not self.fingerprints:
            return
        result = await db.execute(
            select(Highlight.fingerprint).where(
                Highlight.fingerprint.in_(self.fingerprints)
            )
        )
        self.existing = {row[0] for row in result.all()}

    def is_duplicate(self, index: int) -> bool:
        return self.fingerprints[index] in self.existing


class HighlightPersister:
    """Creates Highlight ORM rows from parsed dicts."""

    @staticmethod
    def build(item: dict, source_type: str, fingerprint: str) -> Highlight:
        return Highlight(
            text=item.get("text", ""),
            note=item.get("note"),
            page=item.get("page"),
            chapter=item.get("chapter"),
            source_type=source_type,
            source_id=item.get("source_id"),
            book_title=item.get("book_title", "Untitled"),
            book_author=item.get("book_author"),
            book_url=item.get("book_url"),
            category=item.get("category", "books"),
            color=item.get("color"),
            highlighted_at=item.get("highlighted_at") or datetime.now(timezone.utc),
            favorite=item.get("favorite", 0),
            share_token=get_share_token(),
            fingerprint=fingerprint,
        )


class ImportTracker:
    """Manages Source records for import history."""

    @staticmethod
    def record(source_name: str, source_type: str, imported_count: int) -> Source:
        return Source(
            name=source_name,
            source_type=source_type,
            last_import_at=datetime.now(timezone.utc),
            highlights_imported=imported_count,
        )


class ImportService:
    """Facade for the import pipeline — dedup + persist + track.

    Single entry point used by all import routes (file upload, API).
    """

    @staticmethod
    async def save_highlights(
        db: AsyncSession,
        items: List[dict],
        source_name: str,
        source_type: str,
        *,
        dry_run: bool = False,
    ) -> ImportResult:
        result = ImportResult(dry_run=dry_run)
        if not items:
            return result

        # Dedup
        dedup = DedupService(items)
        await dedup.check(db)

        # Persist (or count in dry-run mode)
        new_rows: List[Highlight] = []
        for i, item in enumerate(items):
            if dedup.is_duplicate(i):
                result.skipped += 1
                continue
            if dry_run:
                result.imported += 1
                continue
            hl = HighlightPersister.build(item, source_type, dedup.fingerprints[i])
            new_rows.append(hl)
            result.imported += 1

        if not dry_run and new_rows:
            db.add_all(new_rows)
            db.add(ImportTracker.record(source_name, source_type, len(new_rows)))
            await db.commit()

        return result
