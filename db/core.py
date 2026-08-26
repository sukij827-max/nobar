from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String, UniqueConstraint, text
from config import settings


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    group_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    host_user_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_playing: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Member(Base):
    __tablename__ = "room_members"
    __table_args__ = (UniqueConstraint("room_id", "user_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Film(Base):
    __tablename__ = "films"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(Integer, index=True)
    owner_user_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(String(500), unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mime_type: Mapped[str] = mapped_column(String(120), default="video/mp4")
    status: Mapped[str] = mapped_column(String(20), default="ready")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


engine = create_async_engine(settings.database_url, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def _ensure_users_schema(conn):
    """Safely reconcile the production users table with the current ORM model.

    This is intentionally additive: it never drops or recreates the table, so
    existing production rows are preserved.
    """
    exists = await conn.scalar(
        text("SELECT to_regclass('public.users') IS NOT NULL")
    )
    if not exists:
        return

    columns = {
        row[0]
        for row in (
            await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='users'"
                )
            )
        ).all()
    }

    # Some earlier versions used `id`; keep those records and migrate the
    # identifier into the immutable Telegram user_id field.
    if "user_id" not in columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN user_id BIGINT"))
        if "id" in columns:
            await conn.execute(text("UPDATE users SET user_id = id WHERE user_id IS NULL"))

    if "username" not in columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR(255)"))
    if "first_name" not in columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN first_name VARCHAR(255)"))
    if "created_at" not in columns:
        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN created_at TIMESTAMPTZ "
                "DEFAULT CURRENT_TIMESTAMP"
            )
        )
        await conn.execute(
            text("UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
        )

    # The ORM requires user_id to identify a User. A unique index is enough for
    # PostgreSQL to enforce the invariant without destroying an existing PK.
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_user_id "
            "ON users(user_id) WHERE user_id IS NOT NULL"
        )
    )


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_users_schema(conn)


async def close_db():
    await engine.dispose()
