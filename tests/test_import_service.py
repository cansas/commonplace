"""Tests for the import pipeline service.

Tests the pure-logic layer (fingerprint, DedupService) and the
DB-backed layer (ImportService.save_highlights with db_session).
"""

import pytest
import pytest_asyncio

from app.services.import_service import (
    highlight_fingerprint,
    DedupService,
    ImportService,
)


# ── highlight_fingerprint ────────────────────────────────────────────────

class TestFingerprint:
    def test_deterministic(self):
        a = highlight_fingerprint("hello world", "Book Title")
        b = highlight_fingerprint("hello world", "Book Title")
        assert a == b
        assert isinstance(a, str)
        assert len(a) == 64  # SHA256 hex

    def test_different_text_differs(self):
        a = highlight_fingerprint("hello", "Book")
        b = highlight_fingerprint("world", "Book")
        assert a != b

    def test_different_book_differs(self):
        a = highlight_fingerprint("hello", "Book A")
        b = highlight_fingerprint("hello", "Book B")
        assert a != b

    def test_collision_resistance(self):
        """Same text+book across different timestamps = same fingerprint."""
        a = highlight_fingerprint("quote", "My Book")
        b = highlight_fingerprint("quote", "My Book")
        assert a == b

    def test_empty_text(self):
        fp = highlight_fingerprint("", "Book")
        assert isinstance(fp, str)
        assert len(fp) == 64


# ── DedupService ─────────────────────────────────────────────────────────

class TestDedupService:
    def test_fingerprints_matches_items(self):
        items = [
            {"text": "hello", "book_title": "A"},
            {"text": "world", "book_title": "B"},
        ]
        dedup = DedupService(items)
        assert len(dedup.fingerprints) == 2
        assert dedup.fingerprints[0] == highlight_fingerprint("hello", "A")

    def test_empty_items(self):
        dedup = DedupService([])
        assert dedup.fingerprints == []

    def test_missing_book_title_defaults(self):
        items = [{"text": "hello"}]
        dedup = DedupService(items)
        assert dedup.fingerprints[0] == highlight_fingerprint("hello", "Untitled")

    def test_is_duplicate_detects_matches(self):
        items = [
            {"text": "dup", "book_title": "X"},
            {"text": "new", "book_title": "X"},
        ]
        dedup = DedupService(items)
        dedup.existing = {dedup.fingerprints[0]}  # Mark first as existing
        assert dedup.is_duplicate(0) is True
        assert dedup.is_duplicate(1) is False


# ── ImportService (requires DB) ──────────────────────────────────────────

@pytest_asyncio.fixture
async def sample_items():
    return [
        {"text": "Quote one", "book_title": "Test Book", "book_author": "Author"},
        {"text": "Quote two", "book_title": "Test Book", "book_author": "Author"},
        {"text": "Quote three", "book_title": "Another Book", "book_author": "Writer"},
    ]


@pytest.mark.asyncio
async def test_basic_import(db_session, sample_items):
    result = await ImportService.save_highlights(
        db_session, sample_items, "test-import", "manual",
    )
    assert result.imported == 3
    assert result.skipped == 0
    assert result.dry_run is False
    assert result.errors == []


@pytest.mark.asyncio
async def test_skips_duplicates_on_reimport(db_session, sample_items):
    await ImportService.save_highlights(db_session, sample_items, "first", "manual")
    result = await ImportService.save_highlights(db_session, sample_items, "second", "manual")
    assert result.imported == 0
    assert result.skipped == 3


@pytest.mark.asyncio
async def test_import_dry_run(db_session, sample_items):
    result = await ImportService.save_highlights(
        db_session, sample_items, "dry", "manual", dry_run=True,
    )
    assert result.imported == 3
    assert result.skipped == 0
    assert result.dry_run is True

    from app.models import Highlight
    from sqlalchemy import select, func
    cnt = await db_session.execute(select(func.count(Highlight.id)))
    assert cnt.scalar() == 0


@pytest.mark.asyncio
async def test_dry_run_after_real_import(db_session, sample_items):
    await ImportService.save_highlights(db_session, sample_items, "real", "manual")
    result = await ImportService.save_highlights(
        db_session, sample_items, "dry-again", "manual", dry_run=True,
    )
    assert result.imported == 0
    assert result.skipped == 3
    assert result.dry_run is True


@pytest.mark.asyncio
async def test_partial_duplicates(db_session):
    await ImportService.save_highlights(
        db_session,
        [{"text": "existing", "book_title": "B"}],
        "first", "manual",
    )
    items = [
        {"text": "existing", "book_title": "B"},
        {"text": "new", "book_title": "B"},
    ]
    result = await ImportService.save_highlights(db_session, items, "second", "manual")
    assert result.imported == 1
    assert result.skipped == 1


@pytest.mark.asyncio
async def test_creates_source_record(db_session, sample_items):
    await ImportService.save_highlights(db_session, sample_items, "my-source", "kindle")
    from app.models import Source
    from sqlalchemy import select
    srcs = (await db_session.execute(select(Source))).scalars().all()
    names = [s.name for s in srcs]
    assert "my-source" in names
    match = [s for s in srcs if s.name == "my-source"][0]
    assert match.source_type == "kindle"
    assert match.highlights_imported == 3


@pytest.mark.asyncio
async def test_empty_items_import(db_session):
    result = await ImportService.save_highlights(db_session, [], "empty", "manual")
    assert result.imported == 0
    assert result.skipped == 0


@pytest.mark.asyncio
async def test_minimal_item(db_session):
    result = await ImportService.save_highlights(
        db_session,
        [{"text": "just text"}],
        "minimal", "manual",
    )
    assert result.imported == 1
    assert result.skipped == 0
