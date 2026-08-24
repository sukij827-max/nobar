import asyncpg
from pathlib import Path

class DB:
    def __init__(self, url):
        self.url = url
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(self.url, min_size=1, max_size=10)
        await self._migrate()

    async def _migrate(self):
        """
        Idempotent PostgreSQL bootstrap/migration.
        Important: do not rely on CREATE TABLE IF NOT EXISTS to repair an
        older schema. Existing installations may have id/telegram_id instead
        of user_id and may have incompatible foreign keys.
        """
        async with self.pool.acquire() as c:
            async with c.transaction():
                # Base tables are intentionally created without FKs first.
                # This prevents legacy/incompatible FK definitions from
                # stopping application startup.
                await c.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        created_at TIMESTAMPTZ DEFAULT now(),
                        updated_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                await c.execute("""
                    CREATE TABLE IF NOT EXISTS groups (
                        chat_id BIGINT PRIMARY KEY,
                        title TEXT,
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                await c.execute("""
                    CREATE TABLE IF NOT EXISTS films (
                        id BIGSERIAL PRIMARY KEY,
                        owner_id BIGINT,
                        original_name TEXT,
                        size_bytes BIGINT DEFAULT 0,
                        telegram_file_id TEXT,
                        content_type TEXT DEFAULT 'video/mp4',
                        storage_key TEXT,
                        upload_id TEXT,
                        archive_path TEXT,
                        archive_sha TEXT,
                        status TEXT DEFAULT 'processing',
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                await c.execute("""
                    CREATE TABLE IF NOT EXISTS rooms (
                        id BIGSERIAL PRIMARY KEY,
                        code TEXT UNIQUE NOT NULL,
                        group_chat_id BIGINT,
                        host_user_id BIGINT,
                        film_id BIGINT,
                        title TEXT,
                        is_active BOOLEAN DEFAULT TRUE,
                        position_seconds DOUBLE PRECISION DEFAULT 0,
                        is_playing BOOLEAN DEFAULT FALSE,
                        updated_at TIMESTAMPTZ DEFAULT now(),
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                await c.execute("""
                    CREATE TABLE IF NOT EXISTS room_members (
                        room_id BIGINT,
                        user_id BIGINT,
                        joined_at TIMESTAMPTZ DEFAULT now(),
                        PRIMARY KEY(room_id, user_id)
                    )
                """)

                # Repair legacy users table if it existed with another key name.
                cols = await self._columns(c, "users")
                if "user_id" not in cols:
                    await c.execute("ALTER TABLE users ADD COLUMN user_id BIGINT")
                    cols = await self._columns(c, "users")
                if "id" in cols:
                    await c.execute("UPDATE users SET user_id=id WHERE user_id IS NULL")
                elif "telegram_id" in cols:
                    await c.execute("UPDATE users SET user_id=telegram_id WHERE user_id IS NULL")

                # Remove duplicate/null rows before making user_id unique.
                await c.execute("DELETE FROM users WHERE user_id IS NULL")
                await c.execute("""
                    DELETE FROM users a
                    USING users b
                    WHERE a.ctid < b.ctid AND a.user_id = b.user_id
                """)
                await c.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS users_user_id_uq
                    ON users(user_id)
                """)

                # Ensure columns required by the current application exist.
                await self._add_column(c, "users", "username", "TEXT")
                await self._add_column(c, "users", "first_name", "TEXT")
                await self._add_column(c, "users", "created_at", "TIMESTAMPTZ DEFAULT now()")
                await self._add_column(c, "users", "updated_at", "TIMESTAMPTZ DEFAULT now()")

                await self._add_column(c, "groups", "title", "TEXT")
                await self._add_column(c, "groups", "created_at", "TIMESTAMPTZ DEFAULT now()")

                film_cols = {
                    "owner_id": "BIGINT",
                    "original_name": "TEXT",
                    "size_bytes": "BIGINT DEFAULT 0",
                    "telegram_file_id": "TEXT",
                    "content_type": "TEXT DEFAULT 'video/mp4'",
                    "storage_key": "TEXT",
                    "upload_id": "TEXT",
                    "archive_path": "TEXT",
                    "archive_sha": "TEXT",
                    "status": "TEXT DEFAULT 'processing'",
                    "created_at": "TIMESTAMPTZ DEFAULT now()",
                }
                for name, typ in film_cols.items():
                    await self._add_column(c, "films", name, typ)

                room_cols = {
                    "code": "TEXT",
                    "group_chat_id": "BIGINT",
                    "host_user_id": "BIGINT",
                    "film_id": "BIGINT",
                    "title": "TEXT",
                    "is_active": "BOOLEAN DEFAULT TRUE",
                    "position_seconds": "DOUBLE PRECISION DEFAULT 0",
                    "is_playing": "BOOLEAN DEFAULT FALSE",
                    "updated_at": "TIMESTAMPTZ DEFAULT now()",
                    "created_at": "TIMESTAMPTZ DEFAULT now()",
                }
                for name, typ in room_cols.items():
                    await self._add_column(c, "rooms", name, typ)

                await self._add_column(c, "room_members", "room_id", "BIGINT")
                await self._add_column(c, "room_members", "user_id", "BIGINT")
                await self._add_column(c, "room_members", "joined_at", "TIMESTAMPTZ DEFAULT now()")

                # Legacy rows can have NULLs in newly-added fields. Do not make
                # them NOT NULL; current inserts always provide the values.
                await c.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS rooms_code_uq ON rooms(code)
                    WHERE code IS NOT NULL
                """)
                await c.execute("""
                    CREATE INDEX IF NOT EXISTS room_members_room_idx
                    ON room_members(room_id)
                """)
                await c.execute("""
                    CREATE INDEX IF NOT EXISTS room_members_user_idx
                    ON room_members(user_id)
                """)
                await c.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS room_members_room_user_uq
                    ON room_members(room_id, user_id)
                """)
                await c.execute("""
                    CREATE INDEX IF NOT EXISTS films_owner_idx
                    ON films(owner_id)
                """)

    async def _columns(self, c, table):
        rows = await c.fetch("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=$1
        """, table)
        return {r["column_name"] for r in rows}

    async def _add_column(self, c, table, name, definition):
        cols = await self._columns(c, table)
        if name not in cols:
            await c.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def user(self, u):
        await self.pool.execute("""
            INSERT INTO users(user_id,username,first_name)
            VALUES($1,$2,$3)
            ON CONFLICT(user_id)
            DO UPDATE SET username=$2,first_name=$3,updated_at=now()
        """, u.id, u.username, u.first_name)

    async def group(self, c):
        await self.pool.execute("""
            INSERT INTO groups(chat_id,title)
            VALUES($1,$2)
            ON CONFLICT(chat_id)
            DO UPDATE SET title=$2
        """, c.id, c.title or '')

    async def film(self, uid, name, size, fid=None, content_type='video/mp4'):
        return await self.pool.fetchval("""
            INSERT INTO films(owner_id,original_name,size_bytes,telegram_file_id,content_type)
            VALUES($1,$2,$3,$4,$5) RETURNING id
        """, uid, name, size, fid, content_type)

    async def room(self, code):
        return await self.pool.fetchrow(
            'SELECT * FROM rooms WHERE code=$1 AND is_active',
            code.upper()
        )

    async def make_room(self, code, gid, uid, title):
        return await self.pool.fetchrow("""
            INSERT INTO rooms(code,group_chat_id,host_user_id,title)
            VALUES($1,$2,$3,$4) RETURNING *
        """, code, gid, uid, title)

    async def join(self, rid, uid):
        await self.pool.execute("""
            INSERT INTO room_members(room_id,user_id)
            VALUES($1,$2)
            ON CONFLICT(room_id,user_id) DO NOTHING
        """, rid, uid)
