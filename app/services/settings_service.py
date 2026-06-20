"""Typed settings service backed by data/.settings.json.

Moved from app/routes/settings.py to break the circular-ish dependency
where route modules imported _settings directly from a routes module.
Now any module can import from app.services.settings_service without
pulling in route infrastructure.

For test isolation, call ``_use_in_memory()`` in conftest to swap the
JSON file backend for a plain dict.
"""

import json
import os
from typing import Any

_SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", ".settings.json",
)

# Module-level storage — swapped for testing via _use_in_memory()
_storage: dict = {}
_last_mtime: float = 0.0


# ── Internal I/O ──────────────────────────────────────────────────────────

def _load():
    global _storage, _last_mtime
    try:
        if os.path.isfile(_SETTINGS_FILE):
            with open(_SETTINGS_FILE) as f:
                _storage = json.load(f)
            _last_mtime = os.path.getmtime(_SETTINGS_FILE)
    except Exception:
        pass


def _save():
    global _last_mtime
    try:
        os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
        with open(_SETTINGS_FILE, "w") as f:
            json.dump(_storage, f)
        _last_mtime = os.path.getmtime(_SETTINGS_FILE)
    except Exception:
        pass


def _ensure_fresh():
    """Reload from disk if the file's mtime has changed."""
    global _storage, _last_mtime
    try:
        current = os.path.getmtime(_SETTINGS_FILE)
        if current > _last_mtime:
            with open(_SETTINGS_FILE) as f:
                _storage = json.load(f)
            _last_mtime = current
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


# ── Public API ────────────────────────────────────────────────────────────

def get(key: str, default: Any = None) -> Any:
    _ensure_fresh()
    return _storage.get(key, default)


def set(key: str, value: Any) -> None:
    _storage[key] = value
    _save()


def get_all() -> dict:
    _ensure_fresh()
    return dict(_storage)


def get_review_count() -> int:
    return get("review_count", 10)


def set_review_count(n: int) -> None:
    set("review_count", max(5, min(30, n)))


def get_theme() -> str:
    return get("theme", "modern")


def set_theme(t: str) -> None:
    t = t.strip().lower()
    if t not in ("modern", "reader", "dark"):
        t = "modern"
    set("theme", t)


def get_hardcover_api_key() -> str:
    return get("hardcover_api_key", "")


def set_hardcover_api_key(key: str) -> None:
    set("hardcover_api_key", key)


# Backward-compat alias
set_setting = set


# ── Test hook ─────────────────────────────────────────────────────────────

def _use_in_memory(data: dict | None = None) -> None:
    """Replace file-backed storage with an in-memory dict.

    Call from conftest.py to isolate tests from data/.settings.json.
    Optionally seed with initial data.
    """
    global _storage, _last_mtime
    _storage = dict(data) if data else {}
    _last_mtime = 0.0


# Bootstrap on import
_load()
