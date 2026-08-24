import hashlib
import hmac
import json
import os
import time
import urllib.parse
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

from bot.storage import B2Storage, MAX_FILM_BYTES, PART_SIZE, MAX_PARTS

load_dotenv()
app = FastAPI(title='Nobar Mini App')


def storage():
    return B2Storage(
        os.environ['B2_ENDPOINT'],
        os.environ['B2_BUCKET'],
        os.environ['B2_KEY_ID'],
        os.environ['B2_APPLICATION_KEY'],
        os.getenv('B2_REGION', 'us-east-005'),
    )


async def db():
    return await asyncpg.connect(os.environ['DATABASE_URL'])


def verify_init_data(init_data: str):
    if not init_data:
        raise HTTPException(401, 'Telegram session diperlukan')
    try:
        q = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        received = q.pop('hash', None)
        auth_date = int(q.get('auth_date', '0'))
        now = int(time.time())
        if not received or not auth_date or auth_date > now + 60 or now - auth_date > 86400:
            raise ValueError
        data_check = '\n'.join(f'{k}={q[k]}' for k in sorted(q))
        secret = hmac.new(b'WebAppData', os.environ['BOT_TOKEN'].encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received):
            raise ValueError
        user = json.loads(q.get('user', '{}'))
        return int(user['id'])
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, 'Telegram session tidak valid/kedaluwarsa')


async def room_for(code, uid, c):
    normalized = (code or '').strip().upper()
    if not normalized or len(normalized) > 32:
        raise HTTPException(400, 'Kode room tidak valid')
    r = await c.fetchrow(
        'SELECT r.*, f.original_name, f.content_type, f.storage_key, f.status '
        'FROM rooms r LEFT JOIN films f ON f.id=r.film_id '
        'WHERE r.code=$1 AND r.is_active', normalized,
    )
    if not r:
        raise HTTPException(404, 'Room tidak ditemukan')
    member = await c.fetchval(
        'SELECT 1 FROM room_members WHERE room_id=$1 AND user_id=$2', r['id'], uid
    )
    if not member:
        raise HTTPException(403, 'Kamu belum join room')
    return r


@app.get('/health')
async def health():
    return {'ok': True}


@app.get('/')
async def home():
    return FileResponse(Path(__file__).parent / 'static/index.html')


@app.get('/api/room/{code}')
async def room(code, x_telegram_init_data: str = Header(default='')):
    uid = verify_init_data(x_telegram_init_data)
    c = await db()
    try:
        r = await room_for(code, uid, c)
        n = await c.fetchval('SELECT count(*) FROM room_members WHERE room_id=$1', r['id'])
        position = max(0.0, float(r['position_seconds'] or 0))
        if r['is_playing']:
            position += max(0, time.time() - r['updated_at'].timestamp())
        return {
            'code': r['code'], 'title': r['title'], 'members': n,
            'is_playing': bool(r['is_playing']), 'position_seconds': position,
            'is_host': uid == r['host_user_id'],
            'film_ready': r['status'] == 'ready', 'film_name': r['original_name'],
        }
    finally:
        await c.close()


@app.post('/api/room/{code}/state')
async def state(code, body: dict, x_telegram_init_data: str = Header(default='')):
    uid = verify_init_data(x_telegram_init_data)
    c = await db()
    try:
        r = await room_for(code, uid, c)
        if uid != r['host_user_id']:
            raise HTTPException(403, 'Hanya host yang boleh mengontrol playback')
        try:
            pos = max(0.0, float(body.get('position', 0)))
        except (TypeError, ValueError):
            raise HTTPException(400, 'Posisi playback tidak valid')
        playing = bool(body.get('playing', False))
        await c.execute(
            'UPDATE rooms SET position_seconds=$2,is_playing=$3,updated_at=now() WHERE id=$1',
            r['id'], pos, playing,
        )
        return {'ok': True}
    finally:
        await c.close()


@app.get('/api/film/{code}')
async def film(code, x_telegram_init_data: str = Header(default='')):
    uid = verify_init_data(x_telegram_init_data)
    c = await db()
    try:
        r = await room_for(code, uid, c)
        if not r['film_id'] or r['status'] != 'ready' or not r['storage_key']:
            raise HTTPException(409, 'Film belum siap')
        return {
            'name': r['original_name'],
            'content_type': r['content_type'] or 'video/mp4',
            'stream': storage().presign_get(r['storage_key']),
        }
    finally:
        await c.close()


@app.post('/api/upload/init/{code}')
async def upload_init(code, body: dict, x_telegram_init_data: str = Header(default='')):
    uid = verify_init_data(x_telegram_init_data)
    c = await db()
    try:
        r = await room_for(code, uid, c)
        if uid != r['host_user_id']:
            raise HTTPException(403, 'Hanya host yang boleh upload film')
        try:
            size = int(body.get('size', 0))
        except (TypeError, ValueError):
            raise HTTPException(400, 'Ukuran file tidak valid')
        name = str(body.get('name', 'film.mp4')).strip() or 'film.mp4'
        content_type = str(body.get('content_type') or 'video/mp4').strip().lower()
        if size <= 0 or size > MAX_FILM_BYTES:
            raise HTTPException(413, 'Ukuran film maksimal 5 GiB')
        if not (content_type.startswith('video/') or name.lower().endswith(('.mp4', '.mkv', '.webm', '.mov', '.m4v'))):
            raise HTTPException(415, 'File harus berupa video')
        parts = (size + PART_SIZE - 1) // PART_SIZE
        if parts > MAX_PARTS:
            raise HTTPException(413, 'Jumlah part terlalu banyak')

        old = await c.fetchrow(
            'SELECT storage_key,upload_id FROM films WHERE room_id=$1 AND status=\'uploading\' ORDER BY id DESC LIMIT 1',
            r['id'],
        )
        if old and old['storage_key'] and old['upload_id']:
            storage().abort(old['storage_key'], old['upload_id'])
        if old:
            await c.execute(
                'UPDATE films SET status=\'failed\',upload_id=NULL WHERE room_id=$1 AND status=\'uploading\'',
                r['id'],
            )

        film_id = await c.fetchval(
            'INSERT INTO films(owner_id,room_id,original_name,size_bytes,content_type,status) '
            'VALUES($1,$2,$3,$4,$5,\'uploading\') RETURNING id',
            uid, r['id'], name[:200], size, content_type,
        )
        key = storage().key(film_id, name)
        upload_id = storage().create(key, content_type)
        try:
            await c.execute('UPDATE films SET storage_key=$2,upload_id=$3 WHERE id=$1', film_id, key, upload_id)
            urls = [
                {'part_number': i, 'url': storage().presign_part(key, upload_id, i)}
                for i in range(1, parts + 1)
            ]
        except Exception:
            storage().abort(key, upload_id)
            await c.execute('UPDATE films SET status=\'failed\',upload_id=NULL WHERE id=$1', film_id)
            raise
        return {'film_id': film_id, 'key': key, 'upload_id': upload_id, 'part_size': PART_SIZE, 'parts': urls}
    finally:
        await c.close()


@app.post('/api/upload/complete/{code}')
async def upload_complete(code, body: dict, x_telegram_init_data: str = Header(default='')):
    uid = verify_init_data(x_telegram_init_data)
    c = await db()
    try:
        r = await room_for(code, uid, c)
        if uid != r['host_user_id']:
            raise HTTPException(403, 'Hanya host yang boleh upload film')
        try:
            film_id = int(body.get('film_id', 0))
        except (TypeError, ValueError):
            raise HTTPException(400, 'Film ID tidak valid')
        parts = body.get('parts') or []
        f = await c.fetchrow(
            'SELECT * FROM films WHERE id=$1 AND owner_id=$2 AND room_id=$3 AND status=\'uploading\'',
            film_id, uid, r['id'],
        )
        if not f or not f['storage_key'] or not f['upload_id']:
            raise HTTPException(404, 'Upload tidak ditemukan')
        expected = (int(f['size_bytes']) + PART_SIZE - 1) // PART_SIZE
        if not isinstance(parts, list) or len(parts) != expected:
            raise HTTPException(400, 'Part upload belum lengkap')
        try:
            normalized = []
            for p in parts:
                number = int(p.get('PartNumber', 0))
                etag = str(p.get('ETag', '')).strip()
                if not 1 <= number <= expected or not etag:
                    raise ValueError
                normalized.append({'PartNumber': number, 'ETag': etag})
            numbers = sorted(p['PartNumber'] for p in normalized)
        except (AttributeError, TypeError, ValueError):
            raise HTTPException(400, 'Data part tidak valid')
        if numbers != list(range(1, expected + 1)):
            raise HTTPException(400, 'Nomor part tidak lengkap atau duplikat')

        try:
            storage().complete(f['storage_key'], f['upload_id'], normalized)
            meta = storage().head(f['storage_key'])
        except Exception as exc:
            raise HTTPException(502, f'Gagal menyelesaikan upload: {type(exc).__name__}')
        if int(meta.get('ContentLength', -1)) != int(f['size_bytes']):
            storage().abort(f['storage_key'], f['upload_id'])
            raise HTTPException(400, 'Ukuran object tidak cocok')

        await c.execute('UPDATE films SET status=\'ready\',upload_id=NULL WHERE id=$1', film_id)
        await c.execute(
            'UPDATE rooms SET film_id=$2,position_seconds=0,is_playing=false,updated_at=now() WHERE id=$1',
            r['id'], film_id,
        )
        return {'ok': True, 'film_id': film_id, 'name': f['original_name']}
    finally:
        await c.close()


@app.post('/api/upload/abort/{code}')
async def upload_abort(code, body: dict, x_telegram_init_data: str = Header(default='')):
    uid = verify_init_data(x_telegram_init_data)
    c = await db()
    try:
        r = await room_for(code, uid, c)
        if uid != r['host_user_id']:
            raise HTTPException(403, 'Hanya host yang boleh membatalkan upload')
        try:
            film_id = int(body.get('film_id', 0))
        except (TypeError, ValueError):
            raise HTTPException(400, 'Film ID tidak valid')
        f = await c.fetchrow(
            'SELECT * FROM films WHERE id=$1 AND owner_id=$2 AND room_id=$3 AND status=\'uploading\'',
            film_id, uid, r['id'],
        )
        if f:
            if f['storage_key'] and f['upload_id']:
                storage().abort(f['storage_key'], f['upload_id'])
            await c.execute('UPDATE films SET status=\'failed\',upload_id=NULL WHERE id=$1', film_id)
        return {'ok': True}
    finally:
        await c.close()
