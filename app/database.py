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
    # Migrations for existing databases — use PRAGMA to check column existence
    async with engine.begin() as conn:
        from sqlalchemy import text as sqltext
        # Check which columns actually exist in highlights
        pragma = await conn.execute(sqltext("PRAGMA table_info('highlights')"))
        existing = {row[1] for row in pragma.fetchall()}  # row[1] = column name

        pending = []
        if "favorite" not in existing:
            pending.append("ALTER TABLE highlights ADD COLUMN favorite INTEGER DEFAULT 0")
        if "share_token" not in existing:
            pending.append("ALTER TABLE highlights ADD COLUMN share_token VARCHAR(64)")

        for stmt in pending:
            print(f"  Running migration: {stmt}")
            await conn.execute(sqltext(stmt))

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

    # ── FTS5 Full-Text Search ─────────────────────────────────────────────
    async with engine.begin() as conn:
        from sqlalchemy import text as sqltext
        # Drop old external-content FTS table if upgrading
        await conn.execute(sqltext("DROP TABLE IF EXISTS highlights_fts"))
        # Create FTS5 virtual table (standalone — stores its own content)
        await conn.execute(sqltext(
            "CREATE VIRTUAL TABLE IF NOT EXISTS highlights_fts USING fts5("
            "  text, note, book_title, book_author,"
            "  tokenize='porter unicode61'"
            ")"
        ))
        # Sync triggers
        await conn.execute(sqltext(
            "CREATE TRIGGER IF NOT EXISTS highlights_ai AFTER INSERT ON highlights BEGIN "
            "  INSERT INTO highlights_fts(rowid, text, note, book_title, book_author) "
            "  VALUES (new.id, new.text, new.note, new.book_title, new.book_author); "
            "END"
        ))
        await conn.execute(sqltext(
            "CREATE TRIGGER IF NOT EXISTS highlights_ad AFTER DELETE ON highlights BEGIN "
            "  INSERT INTO highlights_fts(highlights_fts, rowid, text, note, book_title, book_author) "
            "  VALUES ('delete', old.id, old.text, old.note, old.book_title, old.book_author); "
            "END"
        ))
        await conn.execute(sqltext(
            "CREATE TRIGGER IF NOT EXISTS highlights_au AFTER UPDATE ON highlights BEGIN "
            "  INSERT INTO highlights_fts(highlights_fts, rowid, text, note, book_title, book_author) "
            "  VALUES ('delete', old.id, old.text, old.note, old.book_title, old.book_author); "
            "  INSERT INTO highlights_fts(rowid, text, note, book_title, book_author) "
            "  VALUES (new.id, new.text, new.note, new.book_title, new.book_author); "
            "END"
        ))

    # Backfill FTS index for existing highlights
    async with async_session() as session:
        from app.models import Highlight
        from sqlalchemy import select, func
        hl_count = await session.execute(select(func.count(Highlight.id)))
        total = hl_count.scalar() or 0

        # Check if FTS index needs backfilling
        try:
            fts_ok = await session.execute(
                sqltext("SELECT COUNT(*) FROM highlights_fts")
            )
            needs_backfill = (fts_ok.scalar() or 0) == 0
        except Exception:
            needs_backfill = True

        if needs_backfill and total > 0:
            print(f"  Backfilling FTS index for {total} highlights...")
            await session.execute(sqltext(
                "INSERT INTO highlights_fts(rowid, text, note, book_title, book_author) "
                "SELECT id, text, note, book_title, book_author FROM highlights"
            ))
            await session.commit()
            print("  FTS backfill complete")
