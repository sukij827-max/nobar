from pathlib import Path
import asyncpg

class DB:
    def __init__(self,url): self.url=url; self.pool=None
    async def connect(self):
        pool = await asyncpg.create_pool(self.url, min_size=1, max_size=10)
        try:
            await pool.execute((Path(__file__).parents[1] / 'db/schema.sql').read_text())
        except Exception:
            await pool.close()
            raise
        self.pool = pool
    async def close(self):
        if self.pool: await self.pool.close()
    async def user(self,u):
        await self.pool.execute('INSERT INTO users(user_id,username,first_name) VALUES($1,$2,$3) ON CONFLICT(user_id) DO UPDATE SET username=$2,first_name=$3,updated_at=now()',u.id,u.username,u.first_name)
    async def group(self,c):
        await self.pool.execute('INSERT INTO groups(chat_id,title) VALUES($1,$2) ON CONFLICT(chat_id) DO UPDATE SET title=$2',c.id,c.title or '')
    async def film(self,uid,name,size,fid=None,content_type='video/mp4'):
        return await self.pool.fetchval('INSERT INTO films(owner_id,original_name,size_bytes,telegram_file_id,content_type) VALUES($1,$2,$3,$4,$5) RETURNING id',uid,name,size,fid,content_type)
    async def room(self,code):
        return await self.pool.fetchrow('SELECT * FROM rooms WHERE code=$1 AND is_active',code.upper())
    async def make_room(self,code,gid,uid,title):
        return await self.pool.fetchrow('INSERT INTO rooms(code,group_chat_id,host_user_id,title) VALUES($1,$2,$3,$4) RETURNING *',code,gid,uid,title)
    async def join(self,rid,uid):
        await self.pool.execute('INSERT INTO room_members VALUES($1,$2) ON CONFLICT DO NOTHING',rid,uid)
