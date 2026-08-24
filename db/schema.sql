-- Nobar FINAL3: PostgreSQL schema with safe legacy migration.
-- The migration is deliberately idempotent and never references users(user_id)
-- until user_id has been created and made UNIQUE.

CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT,
    username TEXT,
    first_name TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- Older builds used telegram_id. Copy it before enforcing the new key.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='users' AND column_name='telegram_id'
    ) THEN
        EXECUTE 'UPDATE users SET user_id = telegram_id WHERE user_id IS NULL AND telegram_id IS NOT NULL';
    END IF;
END $$;

-- Drop the previous FK set first. This also removes broken legacy references.
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN
        SELECT conrelid::regclass AS table_name, conname
        FROM pg_constraint
        WHERE contype='f'
          AND (
              confrelid = 'users'::regclass
              OR conrelid IN (
                  'users'::regclass,
                  'films'::regclass,
                  'rooms'::regclass,
                  'room_members'::regclass
              )
          )
    LOOP
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I', r.table_name, r.conname);
    END LOOP;
END $$;

-- Legacy rows without a Telegram id cannot be used by the bot. Remove only
-- those unusable rows, then collapse duplicate ids so the new key is valid.
DELETE FROM users WHERE user_id IS NULL;
DELETE FROM users a
USING users b
WHERE a.user_id = b.user_id
  AND a.ctid > b.ctid;

-- A real UNIQUE CONSTRAINT is used as the FK target. Do not rely on a bare
-- unique index here; that was the source of the previous FK migration failure.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_user_id_key;
DROP INDEX IF EXISTS users_user_id_unique_idx;
ALTER TABLE users ADD CONSTRAINT users_user_id_key UNIQUE (user_id);
ALTER TABLE users ALTER COLUMN user_id SET NOT NULL;

CREATE TABLE IF NOT EXISTS groups (
    chat_id BIGINT PRIMARY KEY,
    title TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE groups ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE groups ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();

CREATE TABLE IF NOT EXISTS films (
    id BIGSERIAL PRIMARY KEY,
    owner_id BIGINT,
    original_name TEXT NOT NULL,
    size_bytes BIGINT DEFAULT 0,
    telegram_file_id TEXT,
    content_type TEXT DEFAULT 'video/mp4',
    storage_key TEXT,
    upload_id TEXT,
    archive_path TEXT,
    archive_sha TEXT,
    status TEXT DEFAULT 'processing',
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE films ADD COLUMN IF NOT EXISTS owner_id BIGINT;
ALTER TABLE films ADD COLUMN IF NOT EXISTS original_name TEXT;
ALTER TABLE films ADD COLUMN IF NOT EXISTS size_bytes BIGINT DEFAULT 0;
ALTER TABLE films ADD COLUMN IF NOT EXISTS telegram_file_id TEXT;
ALTER TABLE films ADD COLUMN IF NOT EXISTS content_type TEXT DEFAULT 'video/mp4';
ALTER TABLE films ADD COLUMN IF NOT EXISTS storage_key TEXT;
ALTER TABLE films ADD COLUMN IF NOT EXISTS upload_id TEXT;
ALTER TABLE films ADD COLUMN IF NOT EXISTS archive_path TEXT;
ALTER TABLE films ADD COLUMN IF NOT EXISTS archive_sha TEXT;
ALTER TABLE films ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'processing';
ALTER TABLE films ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();
ALTER TABLE films ALTER COLUMN telegram_file_id DROP NOT NULL;

CREATE TABLE IF NOT EXISTS rooms (
    id BIGSERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    group_chat_id BIGINT NOT NULL,
    host_user_id BIGINT,
    film_id BIGINT,
    title TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    position_seconds DOUBLE PRECISION DEFAULT 0,
    is_playing BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMPTZ DEFAULT now(),
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS code TEXT;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS group_chat_id BIGINT;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS host_user_id BIGINT;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS film_id BIGINT;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS position_seconds DOUBLE PRECISION DEFAULT 0;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS is_playing BOOLEAN DEFAULT FALSE;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();

-- Repair duplicate legacy room codes before creating the unique constraint.
DO $$
BEGIN
    DELETE FROM rooms a
    USING rooms b
    WHERE a.code IS NOT NULL
      AND a.code = b.code
      AND a.ctid > b.ctid;
EXCEPTION WHEN undefined_column THEN
    NULL;
END $$;
DROP INDEX IF EXISTS rooms_code_unique_idx;
ALTER TABLE rooms DROP CONSTRAINT IF EXISTS rooms_code_key;
CREATE UNIQUE INDEX IF NOT EXISTS rooms_code_unique_idx ON rooms(code);

CREATE TABLE IF NOT EXISTS room_members (
    room_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    joined_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE room_members ADD COLUMN IF NOT EXISTS room_id BIGINT;
ALTER TABLE room_members ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE room_members ADD COLUMN IF NOT EXISTS joined_at TIMESTAMPTZ DEFAULT now();

-- Remove duplicate legacy membership rows before installing the unique index.
DELETE FROM room_members a
USING room_members b
WHERE a.room_id = b.room_id
  AND a.user_id = b.user_id
  AND a.ctid > b.ctid;
DROP INDEX IF EXISTS room_members_room_user_unique_idx;
CREATE UNIQUE INDEX IF NOT EXISTS room_members_room_user_unique_idx ON room_members(room_id,user_id);

-- The application writes the related records in the correct order. We intentionally
-- do not recreate legacy foreign keys here: old deployments had incompatible
-- FK definitions, and PostgreSQL would abort the whole service startup before
-- the bot could repair them. Indexes below provide the lookup performance.

CREATE INDEX IF NOT EXISTS films_owner_idx ON films(owner_id);
CREATE INDEX IF NOT EXISTS rooms_group_active_idx ON rooms(group_chat_id,is_active);
CREATE INDEX IF NOT EXISTS room_members_user_idx ON room_members(user_id);
