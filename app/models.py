from sqlalchemy import Column, Integer, String, Text, DateTime, Float, ForeignKey, Table, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime

# Many-to-many: highlight <-> tag
highlight_tags = Table(
    "highlight_tags",
    Base.metadata,
    Column("highlight_id", Integer, ForeignKey("highlights.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)


class Highlight(Base):
    __tablename__ = "highlights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text, nullable=False)
    note = Column(Text, nullable=True)
    page = Column(Integer, nullable=True)
    chapter = Column(String(255), nullable=True)
    source_type = Column(String(64), nullable=False, default="manual")  # koreader, readwise, manual, kindle
    source_id = Column(String(255), nullable=True)
    book_title = Column(String(511), nullable=False, default="Untitled")
    book_author = Column(String(511), nullable=True)
    book_url = Column(String(2047), nullable=True)
    category = Column(String(64), nullable=True, default="books")
    color = Column(String(32), nullable=True)
    highlighted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    favorite = Column(Integer, default=0)  # 0=no, 1=favorite
    share_token = Column(String(64), unique=True, nullable=True)
    fingerprint = Column(String(64), nullable=True, index=True)  # SHA256 dedup hash

    tags = relationship("Tag", secondary=highlight_tags, lazy="selectin")
    reviews = relationship("ReviewLog", back_populates="highlight", lazy="selectin")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), unique=True, nullable=False)
    color = Column(String(7), nullable=True)  # hex color like #3b82f6


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    source_type = Column(String(64), nullable=False)
    last_import_at = Column(DateTime, nullable=True)
    last_hash = Column(String(128), nullable=True)
    highlights_imported = Column(Integer, default=0)


class ReviewLog(Base):
    __tablename__ = "review_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    highlight_id = Column(Integer, ForeignKey("highlights.id"), nullable=False)
    reviewed_at = Column(DateTime, default=datetime.utcnow)
    rating = Column(Integer, nullable=True)  # 0=forgot, 1=hard, 2=good, 3=easy
    ease_factor = Column(Float, default=2.5)
    interval = Column(Integer, default=0)  # days
    repetitions = Column(Integer, default=0)
    next_review_at = Column(DateTime, nullable=True)

    highlight = relationship("Highlight", back_populates="reviews")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(128), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    tokens = relationship("ApiToken", back_populates="user", cascade="all, delete-orphan")


class UserAchievement(Base):
    __tablename__ = "user_achievements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=1)
    achievement_key = Column(String(64), nullable=False)
    message = Column(String(255), nullable=True)
    unlocked_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "achievement_key", name="uq_user_achievement"),
    )


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(128), nullable=False)  # e.g. "koreader", "obsidian-plugin"
    token_hash = Column(String(255), nullable=False)  # SHA256 of the token secret
    token_prefix = Column(String(16), nullable=False)  # first chars for display
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="tokens")


class BookCover(Base):
    __tablename__ = "book_covers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_title = Column(String(511), nullable=False)
    book_author = Column(String(511), nullable=False, default="")
    cover_source = Column(String(16), nullable=False, default="none")
    cover_url = Column(String(1024), nullable=True)
    hardcover_id = Column(Integer, nullable=True)
    isbn = Column(String(20), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("book_title", "book_author", name="uq_book_cover"),
    )
