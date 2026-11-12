"""BookOrbit sync auth: API keys alongside the legacy username/password.

BookOrbit gained API keys (``bok_`` prefixed, sent as ``X-Api-Key``). The sync
must prefer a key when one is configured and keep the password flow working
untouched for installations that never set one.
"""

import pytest
import pytest_asyncio

from app.services import bookorbit_sync as bos


# ── Fake httpx transport ────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = "{}" if body is None else "x"

    def json(self):
        return self._body


class _FakeClient:
    """Records every request the sync makes; replies from a lookup table."""

    def __init__(self, routes, calls):
        self._routes = routes
        self._calls = calls

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, method, url, json=None, headers=None):
        self._calls.append({"method": method, "url": url, "json": json, "headers": headers or {}})
        for fragment, response in self._routes.items():
            if fragment in url:
                return response
        return _FakeResponse(404, {"message": "not found"})


@pytest.fixture
def fake_http(monkeypatch):
    """Patch the sync module's httpx client. Returns ``(routes, calls)``."""
    routes = {}
    calls = []
    monkeypatch.setattr(bos.httpx, "AsyncClient", _FakeClient(routes, calls))
    return routes, calls


class _SessionCtx:
    """Context-manager wrapper so a test session looks like async_session()."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


# ── Pure helpers ────────────────────────────────────────────────────────────


def test_auth_headers_uses_x_api_key():
    assert bos.auth_headers("bok_abc") == {"X-Api-Key": "bok_abc"}


def test_auth_headers_strips_pasted_whitespace():
    assert bos.auth_headers("  bok_abc\n") == {"X-Api-Key": "bok_abc"}


def test_auth_headers_empty_when_no_key():
    assert bos.auth_headers("") == {}
    assert bos.auth_headers(None) == {}


@pytest.mark.parametrize(
    "config,expected",
    [
        ({"url": "http://bo", "api_key": "bok_x"}, True),
        ({"url": "http://bo", "username": "u", "password": "p"}, True),
        ({"url": "http://bo", "api_key": "bok_x", "username": "u", "password": "p"}, True),
        ({"url": "http://bo", "username": "u"}, False),
        ({"url": "", "api_key": "bok_x"}, False),
        ({"url": "http://bo"}, False),
        ({}, False),
    ],
)
def test_has_credentials(config, expected):
    assert bos.has_credentials(config) is expected


# ── test_connection ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connection_with_api_key_hits_auth_me(fake_http):
    routes, calls = fake_http
    routes["/api/v1/auth/me"] = _FakeResponse(
        200, {"username": "brandon", "authenticationMethod": "api_key"}
    )

    result = await bos.test_connection("http://bo/", api_key="bok_key")

    assert result["ok"] is True
    assert result["method"] == "api_key"
    assert result["username"] == "brandon"
    assert calls[0]["url"] == "http://bo/api/v1/auth/me"
    assert calls[0]["headers"] == {"X-Api-Key": "bok_key"}
    # A key never needs a login round-trip.
    assert not any("/auth/login" in c["url"] for c in calls)


@pytest.mark.asyncio
async def test_connection_rejected_api_key_surfaces_server_message(fake_http):
    routes, _ = fake_http
    routes["/api/v1/auth/me"] = _FakeResponse(401, {"message": "Invalid API key"})

    result = await bos.test_connection("http://bo", api_key="bok_bad")

    assert result["ok"] is False
    assert result["method"] == "api_key"
    assert "Invalid API key" in result["error"]


@pytest.mark.asyncio
async def test_connection_reports_disabled_api_keys(fake_http):
    routes, _ = fake_http
    routes["/api/v1/auth/me"] = _FakeResponse(
        401, {"message": "API keys disabled", "errorCode": "API_KEYS_DISABLED"}
    )

    result = await bos.test_connection("http://bo", api_key="bok_key")

    assert result["ok"] is False
    assert "disabled" in result["error"].lower()


@pytest.mark.asyncio
async def test_connection_key_wins_over_password(fake_http):
    routes, calls = fake_http
    routes["/api/v1/auth/me"] = _FakeResponse(200, {"username": "brandon"})
    routes["/api/v1/auth/login"] = _FakeResponse(200, {})

    result = await bos.test_connection(
        "http://bo", username="u", password="p", api_key="bok_key"
    )

    assert result["method"] == "api_key"
    assert not any("/auth/login" in c["url"] for c in calls)


@pytest.mark.asyncio
async def test_connection_falls_back_to_password_login(fake_http):
    routes, calls = fake_http
    routes["/api/v1/auth/login"] = _FakeResponse(200, {"token": "jwt"})

    result = await bos.test_connection("http://bo", username="u", password="p")

    assert result["ok"] is True
    assert result["method"] == "password"
    assert calls[0]["method"] == "POST"
    assert calls[0]["json"] == {"username": "u", "password": "p"}
    assert calls[0]["headers"] == {}


@pytest.mark.asyncio
async def test_connection_needs_some_credential(fake_http):
    routes, calls = fake_http

    result = await bos.test_connection("http://bo", username="u")

    assert result["ok"] is False
    assert "API key" in result["error"]
    assert calls == []


@pytest.mark.asyncio
async def test_connection_requires_url(fake_http):
    result = await bos.test_connection("", api_key="bok_key")
    assert result["ok"] is False
    assert "URL" in result["error"]


# ── sync_from_bookorbit ─────────────────────────────────────────────────────


@pytest.fixture
def configured(monkeypatch):
    """Store a config without touching real settings/DB."""
    state = {
        "url": "http://bo",
        "api_key": "bok_key",
        "username": "",
        "password": "",
        "enabled": True,
        "last_synced_id": 0,
        "last_synced_at": "",
        "disabled_reason": "",
    }
    written = {}
    monkeypatch.setattr(bos, "get_sync_config", lambda: dict(state))
    monkeypatch.setattr(bos, "_set", lambda k, v: written.__setitem__(k, v))
    return state, written


@pytest.fixture
def sync_db(db_session, monkeypatch):
    """Point the sync's own ``async_session`` at the test database."""
    import app.database

    monkeypatch.setattr(app.database, "async_session", lambda: _SessionCtx(db_session))
    return db_session


@pytest.mark.asyncio
async def test_sync_sends_api_key_on_every_annotation_page(fake_http, configured, sync_db):
    routes, calls = fake_http
    state, written = configured
    routes["/api/v1/auth/me"] = _FakeResponse(200, {"username": "brandon"})
    routes["/api/v1/annotations"] = _FakeResponse(200, {"items": [], "total": 0})

    result = await bos.sync_from_bookorbit()

    assert result["posted"] == 0
    ann_calls = [c for c in calls if "/api/v1/annotations" in c["url"]]
    assert ann_calls, "annotations were never requested"
    assert all(c["headers"] == {"X-Api-Key": "bok_key"} for c in ann_calls)
    # No login POST at all when authenticated by key.
    assert not any("/auth/login" in c["url"] for c in calls)
    assert written.get(bos._BOOKORBIT_DISABLED_REASON) == ""


@pytest.mark.asyncio
async def test_sync_records_rejected_key_as_disabled_reason(fake_http, configured, sync_db):
    routes, calls = fake_http
    state, written = configured
    routes["/api/v1/auth/me"] = _FakeResponse(401, {"message": "Invalid API key"})

    result = await bos.sync_from_bookorbit()

    assert result["posted"] == 0
    assert written[bos._BOOKORBIT_DISABLED_REASON].startswith("auth_failed:")
    assert not any("/api/v1/annotations" in c["url"] for c in calls)


@pytest.mark.asyncio
async def test_sync_legacy_password_flow_still_works(fake_http, configured, sync_db):
    routes, calls = fake_http
    state, written = configured
    state["api_key"] = ""
    state["username"] = "u"
    state["password"] = "p"
    routes["/api/v1/auth/login"] = _FakeResponse(200, {})
    routes["/api/v1/annotations"] = _FakeResponse(200, {"items": [], "total": 0})

    result = await bos.sync_from_bookorbit()

    assert result["posted"] == 0
    login = [c for c in calls if "/auth/login" in c["url"]]
    assert len(login) == 1 and login[0]["method"] == "POST"
    ann_calls = [c for c in calls if "/api/v1/annotations" in c["url"]]
    assert all(c["headers"] == {} for c in ann_calls)


@pytest.mark.asyncio
async def test_sync_without_credentials_makes_no_requests(fake_http, configured, sync_db):
    routes, calls = fake_http
    state, _ = configured
    state["api_key"] = ""

    result = await bos.sync_from_bookorbit()

    assert result["posted"] == 0
    assert calls == []


# ── Settings routes ─────────────────────────────────────────────────────────
#
# The JSON settings routes sit behind AuthMiddleware, which verifies an
# ``Authorization: Token ...`` header against its own async_session. That
# session is swapped for the test session so the routes can be exercised over
# HTTP instead of by calling the handlers directly.


@pytest_asyncio.fixture
async def api_headers(db_session, monkeypatch):
    import app.auth
    from app.auth import generate_api_token
    from app.models import ApiToken, User

    user = User(username="bouser", password_hash="x")
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
async def test_save_settings_persists_api_key(client, api_headers):
    resp = await client.post(
        "/api/settings/bookorbit-sync",
        json={
            "bookorbit_url": "http://bo",
            "bookorbit_api_key": "bok_saved",
            "bookorbit_sync_enabled": True,
        },
        headers=api_headers,
    )
    assert resp.json()["ok"] is True

    config = bos.get_sync_config()
    assert config["api_key"] == "bok_saved"
    assert config["url"] == "http://bo"
    assert config["enabled"] is True


@pytest.mark.asyncio
async def test_sync_now_accepts_api_key_only_config(client, api_headers, monkeypatch):
    """A key-only config used to fail the 'URL and username' guard."""
    await client.post(
        "/api/settings/bookorbit-sync",
        json={
            "bookorbit_url": "http://bo",
            "bookorbit_api_key": "bok_saved",
            "bookorbit_sync_enabled": True,
        },
        headers=api_headers,
    )

    called = {}

    async def _stub():
        called["yes"] = True
        return {"posted": 1, "skipped": 0, "errors": 0, "last_id": 5}

    monkeypatch.setattr(bos, "sync_from_bookorbit", _stub)

    resp = await client.post("/api/settings/bookorbit-sync-now", headers=api_headers)
    data = resp.json()

    assert data["ok"] is True, data
    assert called.get("yes") is True
    assert data["result"]["posted"] == 1


@pytest.mark.asyncio
async def test_sync_now_reports_missing_credentials(client, api_headers):
    await client.post(
        "/api/settings/bookorbit-sync",
        json={
            "bookorbit_url": "http://bo",
            "bookorbit_api_key": "",
            "bookorbit_username": "",
            "bookorbit_password": "",
            "bookorbit_sync_enabled": True,
        },
        headers=api_headers,
    )

    resp = await client.post("/api/settings/bookorbit-sync-now", headers=api_headers)
    data = resp.json()

    assert data["ok"] is False
    assert "API key" in data["error"]
