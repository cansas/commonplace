"""Commonplace test infrastructure.

Sets env vars before importing the app so the production startup handler
(init_db) can share an in-memory engine with test fixtures.
"""

import os
import pytest
import pytest_asyncio

# Set these before importing app modules — avoids filesystem access
# for session secret and sets test-friendly defaults.
os.environ.setdefault("SESSION_SECRET", "test-secret-not-for-production")
os.environ.setdefault("SESSION_HTTPS_ONLY", "false")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")

from app.services.settings_service import _use_in_memory

# Replace file-backed settings with an in-memory dict so tests don't
# read or write data/.settings.json and each test starts clean.
_use_in_memory({"review_count": 10, "theme": "modern"})

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import Base, get_db
from app.main import app

from httpx import ASGITransport, AsyncClient

# ── Shared in-memory engine ──────────────────────────────────────────────
# A single engine shared by the startup handler and all test fixtures
# so an in-memory SQLite DB isn't duplicated per connection.

test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


async def override_get_db():
    """Replace the app's get_db dependency with our test session."""
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture
async def db_session():
    """Create all tables, yield a session, drop tables.

    Include this fixture in any test that needs database access.
    Parser tests (pure functions) don't need it.
    """
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestSessionLocal() as session:
        yield session
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    """An httpx AsyncClient pointed at the FastAPI app.

    Uses ASGITransport to avoid starting a real server (no port needed).
    Does NOT trigger lifespan startup/shutdown — tables are managed
    by ``db_session`` when a test needs them.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
