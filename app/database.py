from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:////app/data/commonplace.db")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        from app.models import Base  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
    # Migrations for existing databases
    async with engine.begin() as conn:
        from sqlalchemy import text
        try:
            await conn.execute(text("ALTER TABLE highlights ADD COLUMN favorite INTEGER DEFAULT 0"))
        except Exception:
            pass  # Column already exists
        try:
            await conn.execute(text("ALTER TABLE highlights ADD COLUMN share_token VARCHAR(64)"))
        except Exception:
            pass  # Column already exists

    # Backfill share_token for highlights that don't have one
    async with async_session() as session:
        from app.models import Highlight
        from app.routes.share import get_share_token
        from sqlalchemy import select
        result = await session.execute(
            select(Highlight).where(Highlight.share_token.is_(None))
        )
        missing = result.scalars().all()
        for hl in missing:
            hl.share_token = get_share_token()
        if missing:
            await session.commit()
            print(f"  Backfilled share_token for {len(missing)} highlights")

    # Create dedup index (text + book_title + highlighted_at)
    async with engine.begin() as conn:
        from sqlalchemy import text as sqltext
        try:
            await conn.execute(sqltext(
                "CREATE INDEX IF NOT EXISTS ix_highlights_dedup "
                "ON highlights(text, book_title, highlighted_at)"
            ))
        except Exception:
            pass  # Already exists or not supported
