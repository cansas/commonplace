"""Regression tests for Readeck/BookOrbit sync trigger guards.

v1.5.0 bug: POST /api/settings/{readeck,bookorbit}-sync-now returned
{"ok": true, "result": {"posted": 0, "skipped": 0, "errors": 0}} even when
sync was disabled or unconfigured — a misleading "0 imported" report.
The routes now return {"ok": false, "error": "..."} when sync is not
enabled or missing required config.

Auth note: these tests use session auth (POST /login) rather than API
tokens, because AuthMiddleware verifies tokens against its own
async_session, which is not covered by the test dependency override.
"""

import pytest

from app.auth import hash_password
from app.models import User


async def _login(client, db_session) -> None:
    """Create a user and establish a session cookie on the client."""
    db_session.add(User(username="testuser", password_hash=hash_password("testpass")))
    await db_session.commit()
    resp = await client.post(
        "/login",
        data={"username": "testuser", "password": "testpass"},
        follow_redirects=False,
    )
    assert resp.status_code == 303


@pytest.mark.asyncio
async def test_readeck_sync_now_unconfigured_returns_error(client, db_session):
    """Unconfigured Readeck sync must report ok:false, not a fake 0/0/0."""
    await _login(client, db_session)
    response = await client.post("/api/settings/readeck-sync-now")
    data = response.json()
    assert data.get("ok") is False
    assert "error" in data


@pytest.mark.asyncio
async def test_bookorbit_sync_now_unconfigured_returns_error(client, db_session):
    """Unconfigured BookOrbit sync must report ok:false, not a fake 0/0/0."""
    await _login(client, db_session)
    response = await client.post("/api/settings/bookorbit-sync-now")
    data = response.json()
    assert data.get("ok") is False
    assert "error" in data
