from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config import settings


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class Group(Base):
    __tablename__ = "nobar_groups"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    chat_type: Mapped[str] = mapped_column(String(30), default="supergroup")
    bot_is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class GroupMember(Base):
    __tablename__ = "nobar_group_members"
    __table_args__ = (UniqueConstraint("chat_id", "user_id", name="uq_nobar_group_member"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    group_chat_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    host_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    title: Mapped[str] = mapped_column(String(200))
    film_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_playing: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Member(Base):
    __tablename__ = "room_members"
    __table_args__ = (UniqueConstraint("room_id", "user_id", name="uq_room_member"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Film(Base):
    __tablename__ = "films"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(Integer, index=True, default=0)
    owner_user_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(String(700), unique=True)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mime_type: Mapped[str] = mapped_column(String(120), default="video/mp4")
    status: Mapped[str] = mapped_column(String(20), default="ready")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Upload(Base):
    __tablename__ = "uploads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    upload_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    object_key: Mapped[str] = mapped_column(String(700), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mime_type: Mapped[str] = mapped_column(String(120), default="video/mp4")
    status: Mapped[str] = mapped_column(String(30), default="started")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(30), default="feedback")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


engine = create_async_engine(settings.database_url, pool_pre_ping=True, pool_recycle=300)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        statements = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_id BIGINT",
            "UPDATE users SET telegram_id = user_id WHERE telegram_id IS NULL",
            "ALTER TABLE users ALTER COLUMN telegram_id SET NOT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE",
            "UPDATE users SET is_premium = FALSE WHERE is_premium IS NULL",
            "ALTER TABLE users ALTER COLUMN is_premium SET DEFAULT FALSE",
            "ALTER TABLE users ALTER COLUMN is_premium SET NOT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE",
            "UPDATE users SET is_banned = FALSE WHERE is_banned IS NULL",
            "ALTER TABLE users ALTER COLUMN is_banned SET DEFAULT FALSE",
            "ALTER TABLE users ALTER COLUMN is_banned SET NOT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
            "UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL",
            "ALTER TABLE users ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE users ALTER COLUMN updated_at SET NOT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
            "UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE last_seen IS NULL",
            "ALTER TABLE users ALTER COLUMN last_seen SET DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE users ALTER COLUMN last_seen SET NOT NULL",
            "ALTER TABLE rooms ADD COLUMN IF NOT EXISTS group_chat_id BIGINT",
            "ALTER TABLE rooms ALTER COLUMN group_chat_id DROP NOT NULL",
            "ALTER TABLE rooms ADD COLUMN IF NOT EXISTS film_id INTEGER",
            "ALTER TABLE films ADD COLUMN IF NOT EXISTS sha256 VARCHAR(64)",
            "ALTER TABLE feedback ADD COLUMN IF NOT EXISTS kind VARCHAR(30) DEFAULT 'feedback'",
        ]
        for statement in statements:
            await conn.execute(text(statement))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_films_sha256 ON films (sha256)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rooms_film_id ON rooms (film_id)"))


async def close_db() -> None:
    await engine.dispose()
