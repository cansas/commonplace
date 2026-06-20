"""Tests for the KOReader JSON parser — a pure function with no DB needed."""

from app.services.koreader_json import parse_koreader_json


SINGLE_BOOK = {
    "title": "The Great Divorce",
    "author": "C.S. Lewis",
    "entries": [
        {
            "text": "There are two kinds of people: those who say to God 'Thy will be done'",
            "page": 42,
            "chapter": "Chapter 3",
            "note": "Key theological insight",
            "time": 1700000000,
        },
        {
            "text": "A mind once stretched by a new idea never regains its original dimensions",
            "page": 87,
            "datetime": "2024-01-15 14:30:00",
        },
    ],
}

MULTI_BOOK = {
    "documents": [
        {
            "title": "Mere Christianity",
            "author": "C.S. Lewis",
            "entries": [
                {
                    "text": "Pride is spiritual cancer",
                    "page": 95,
                    "time": 1700000000,
                },
            ],
        },
        {
            "title": "The Abolition of Man",
            "author": "C.S. Lewis",
            "entries": [
                {
                    "text": "We make men without chests",
                    "page": 25,
                    "time": 1700100000,
                },
            ],
        },
    ],
}

NO_ENTRIES = {
    "title": "Empty Book",
    "author": "Nobody",
    "entries": [],
}


class TestParseSingleBook:
    """A single-book JSON export (no ``documents`` wrapper)."""

    def test_returns_highlights(self):
        result = parse_koreader_json(SINGLE_BOOK)
        assert len(result) == 2

    def test_sets_book_title_and_author(self):
        result = parse_koreader_json(SINGLE_BOOK)
        assert result[0]["book_title"] == "The Great Divorce"
        assert result[0]["book_author"] == "C.S. Lewis"

    def test_extracts_page_chapter_note(self):
        result = parse_koreader_json(SINGLE_BOOK)
        hl = result[0]
        assert hl["page"] == 42
        assert hl["chapter"] == "Chapter 3"
        assert hl["note"] == "Key theological insight"

    def test_parses_timestamp(self):
        result = parse_koreader_json(SINGLE_BOOK)
        assert result[0]["highlighted_at"] is not None
        assert result[0]["highlighted_at"].year == 2023

    def test_parses_datetime_string(self):
        result = parse_koreader_json(SINGLE_BOOK)
        assert result[1]["highlighted_at"] is not None
        assert result[1]["highlighted_at"].year == 2024

    def test_sets_source_type(self):
        result = parse_koreader_json(SINGLE_BOOK)
        assert result[0]["source_type"] == "koreader"
        assert result[1]["source_type"] == "koreader"


class TestParseMultiBook:
    """Multi-book export with a ``documents`` wrapper."""

    def test_returns_all_books(self):
        result = parse_koreader_json(MULTI_BOOK)
        assert len(result) == 2

    def test_per_book_titles(self):
        result = parse_koreader_json(MULTI_BOOK)
        titles = [r["book_title"] for r in result]
        assert "Mere Christianity" in titles
        assert "The Abolition of Man" in titles

    def test_per_book_authors(self):
        result = parse_koreader_json(MULTI_BOOK)
        for r in result:
            assert r["book_author"] == "C.S. Lewis"


class TestEdgeCases:
    """Boundary conditions the parser should handle gracefully."""

    def test_empty_entries(self):
        result = parse_koreader_json(NO_ENTRIES)
        assert result == []

    def test_empty_dict(self):
        result = parse_koreader_json({})
        assert result == []

    def test_missing_text(self):
        data = {
            "title": "Test",
            "entries": [
                {"text": "", "page": 1},
            ],
        }
        result = parse_koreader_json(data)
        assert len(result) == 1
        assert result[0]["text"] == ""

    def test_invalid_timestamp(self):
        """A bogus ``time`` value should not crash and should leave
        highlighted_at as None."""
        data = {
            "title": "Test",
            "entries": [
                {"text": "Hello", "time": -999999999999999},
            ],
        }
        result = parse_koreader_json(data)
        assert result[0]["highlighted_at"] is None

    def test_tags_defaults_to_empty_list(self):
        result = parse_koreader_json(SINGLE_BOOK)
        assert result[0]["tags"] == []
