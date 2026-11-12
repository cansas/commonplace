"""Regression tests for Readeck/BookOrbit sync trigger guards.

v1.5.0 bug: POST /api/settings/{readeck,bookorbit}-sync-now returned
{"ok": true, "result": {"posted": 0, "skipped": 0, "errors": 0}} even when
sync was disabled or unconfigured — a misleading "0 imported" report.
The routes now return {"ok": false, "error": "..."} when sync is not
enabled or missing required config.

Auth note: these are /api/* routes, so AuthMiddleware requires an
``Authorization: Token ...`` header (a session cookie is not enough). The
fixture below creates a real token row and points the middleware's
async_session at the test database.
"""

import pytest
import pytest_asyncio

from app.auth import generate_api_token
from app.models import ApiToken, User


class _SessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@pytest_asyncio.fixture
async def api_headers(db_session, monkeypatch):
    import app.auth

    user = User(username="testuser", password_hash="x")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    plaintext, token_hash, prefix = generate_api_token("test")
    db_session.add(ApiToken(
        user_id=user.id, name="test", token_hash=token_hash, token_prefix=prefix,
    ))
    await db_session.commit()

    monkeypatch.setattr(app.auth, "async_session", lambda: _SessionCtx(db_session))
    return {"Authorization": f"Token {plaintext}"}


@pytest.mark.asyncio
async def test_readeck_sync_now_unconfigured_returns_error(client, api_headers):
    """Unconfigured Readeck sync must report ok:false, not a fake 0/0/0."""
    response = await client.post("/api/settings/readeck-sync-now", headers=api_headers)
    data = response.json()
    assert data.get("ok") is False
    assert "error" in data


@pytest.mark.asyncio
async def test_bookorbit_sync_now_unconfigured_returns_error(client, api_headers):
    """Unconfigured BookOrbit sync must report ok:false, not a fake 0/0/0."""
    response = await client.post("/api/settings/bookorbit-sync-now", headers=api_headers)
    data = response.json()
    assert data.get("ok") is False
    assert "error" in data
