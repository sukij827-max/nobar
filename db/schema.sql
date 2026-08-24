CREATE TABLE IF NOT EXISTS users(user_id BIGINT PRIMARY KEY,username TEXT,first_name TEXT,created_at TIMESTAMPTZ DEFAULT now(),updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS groups(chat_id BIGINT PRIMARY KEY,title TEXT,created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS films(id BIGSERIAL PRIMARY KEY,owner_id BIGINT REFERENCES users(user_id),original_name TEXT NOT NULL,size_bytes BIGINT DEFAULT 0,telegram_file_id TEXT,content_type TEXT DEFAULT 'video/mp4',storage_key TEXT,upload_id TEXT,archive_path TEXT,archive_sha TEXT,status TEXT DEFAULT 'processing',created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS rooms(id BIGSERIAL PRIMARY KEY,code TEXT UNIQUE NOT NULL,group_chat_id BIGINT NOT NULL,host_user_id BIGINT REFERENCES users(user_id),film_id BIGINT REFERENCES films(id),title TEXT NOT NULL,is_active BOOLEAN DEFAULT TRUE,position_seconds DOUBLE PRECISION DEFAULT 0,is_playing BOOLEAN DEFAULT FALSE,updated_at TIMESTAMPTZ DEFAULT now(),created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS room_members(room_id BIGINT REFERENCES rooms(id) ON DELETE CASCADE,user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,joined_at TIMESTAMPTZ DEFAULT now(),PRIMARY KEY(room_id,user_id));
ALTER TABLE films ADD COLUMN IF NOT EXISTS content_type TEXT DEFAULT 'video/mp4';
ALTER TABLE films ADD COLUMN IF NOT EXISTS storage_key TEXT;
ALTER TABLE films ADD COLUMN IF NOT EXISTS upload_id TEXT;
ALTER TABLE films ALTER COLUMN telegram_file_id DROP NOT NULL;
