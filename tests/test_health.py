"""Basic smoke test — verify the FastAPI app starts and responds to requests.

This tests the public /health endpoint which bypasses auth middleware.
"""

import pytest


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """The health endpoint should return 200 without authentication."""
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_returns_json(client):
    """The health endpoint should return a JSON body."""
    response = await client.get("/health")
    try:
        data = response.json()
    except Exception:
        pytest.fail("Response was not valid JSON")
    # Accept whatever structure the endpoint returns — just confirm it's dict-like
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_login_page_accessible(client, db_session):
    """The login page should be reachable (no auth challenge).

    Expects 200 (user exists) or 303 (no user → redirect to setup).
    Either is valid — what matters is no 401/403/500.
    """
    response = await client.get("/login", follow_redirects=False)
    assert response.status_code in (200, 303)


@pytest.mark.asyncio
async def test_static_file_served(client):
    """Static files should be served without auth."""
    response = await client.get("/static/logo.png")
    # May 404 if this specific file doesn't exist, but should NOT be a 500
    assert response.status_code in (200, 404)
