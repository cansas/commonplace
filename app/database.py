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

    # ── BookCover metadata columns ──────────────────────────────────────────
    async with engine.begin() as conn:
        from sqlalchemy import text as sqltext
        pragma2 = await conn.execute(sqltext("PRAGMA table_info('book_covers')"))
        bc_cols = {row[1] for row in pragma2.fetchall()}
        if "hardcover_id" not in bc_cols:
            await conn.execute(sqltext("ALTER TABLE book_covers ADD COLUMN hardcover_id INTEGER"))
            print("  Migration: added hardcover_id to book_covers")
        if "isbn" not in bc_cols:
            await conn.execute(sqltext("ALTER TABLE book_covers ADD COLUMN isbn VARCHAR(20)"))
            print("  Migration: added isbn to book_covers")

    # ── UserAchievements table ─────────────────────────────────────────────
    async with engine.begin() as conn:
        from sqlalchemy import text as sqltext
        pragma3 = await conn.execute(sqltext("SELECT name FROM sqlite_master WHERE type='table' AND name='user_achievements'"))
        if not pragma3.fetchone():
            await conn.execute(sqltext(
                "CREATE TABLE user_achievements ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),"
                "  achievement_key VARCHAR(64) NOT NULL,"
                "  message VARCHAR(255),"
                "  unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                "  UNIQUE(user_id, achievement_key)"
                ")"
            ))
            print("  Migration: created user_achievements table")

    # ── Tags color column ───────────────────────────────────────────────────
    async with engine.begin() as conn:
        from sqlalchemy import text as sqltext
        pragma4 = await conn.execute(sqltext("PRAGMA table_info('tags')"))
        tag_cols = {row[1] for row in pragma4.fetchall()}
        if "color" not in tag_cols:
            await conn.execute(sqltext("ALTER TABLE tags ADD COLUMN color VARCHAR(7)"))
            print("  Migration: added color to tags")

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
        # Sync triggers — AU fires only when FTS-relevant columns change
        # (not on favorite/share_token updates)
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
        # Replace old AU trigger that fired on EVERY column with one scoped to content columns
        await conn.execute(sqltext("DROP TRIGGER IF EXISTS highlights_au"))
        await conn.execute(sqltext(
            "CREATE TRIGGER highlights_au AFTER UPDATE OF text, note, book_title, book_author ON highlights BEGIN "
            "  INSERT INTO highlights_fts(highlights_fts, rowid, text, note, book_title, book_author) "
            "  VALUES ('delete', old.id, old.text, old.note, old.book_title, old.book_author); "
            "  INSERT INTO highlights_fts(rowid, text, note, book_title, book_author) "
            "  VALUES (new.id, new.text, new.note, new.book_title, new.book_author); "
            "END"
        ))

    # ── Database indexes ───────────────────────────────────────────────────
    # Add indexes on common filter columns used in WHERE/ORDER BY clauses
    async with engine.begin() as conn:
        from sqlalchemy import text as sqltext
        for idx_stmt in [
            "CREATE INDEX IF NOT EXISTS ix_highlights_highlighted_at ON highlights(highlighted_at)",
            "CREATE INDEX IF NOT EXISTS ix_highlights_book_title ON highlights(book_title)",
            "CREATE INDEX IF NOT EXISTS ix_highlights_source_type ON highlights(source_type)",
            "CREATE INDEX IF NOT EXISTS ix_highlights_favorite ON highlights(favorite)",
            "CREATE INDEX IF NOT EXISTS ix_review_log_highlight_id ON review_log(highlight_id)",
            "CREATE INDEX IF NOT EXISTS ix_review_log_reviewed_at ON review_log(reviewed_at)",
        ]:
            try:
                await conn.execute(sqltext(idx_stmt))
            except Exception:
                pass  # Index may already exist or engine doesn't support

    # ── Fingerprint column for import dedup ──────────────────────────
    async with engine.begin() as conn:
        from sqlalchemy import text as sqltext
        pragma = await conn.execute(sqltext("PRAGMA table_info('highlights')"))
        hl_cols = {row[1] for row in pragma.fetchall()}
        if "fingerprint" not in hl_cols:
            await conn.execute(sqltext(
                "ALTER TABLE highlights ADD COLUMN fingerprint VARCHAR(64)"
            ))
            print("  Migration: added fingerprint to highlights")

    # Backfill fingerprints for existing rows (one-time)
    async with async_session() as session:
        from app.services.import_service import highlight_fingerprint
        result = await session.execute(
            select(Highlight).where(Highlight.fingerprint.is_(None))
        )
        missing = result.scalars().all()
        if missing:
            print(f"  Backfilling fingerprints for {len(missing)} highlights...")
            for hl in missing:
                hl.fingerprint = highlight_fingerprint(hl.text, hl.book_title or "")
            await session.commit()

    # Create fingerprint index
    async with engine.begin() as conn:
        try:
            await conn.execute(sqltext(
                "CREATE INDEX IF NOT EXISTS ix_highlights_fingerprint "
                "ON highlights(fingerprint)"
            ))
        except Exception:
            pass

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
