import hashlib
import hmac
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from bot.runtime import bot, start_polling, stop_polling
from config import settings
from db import Film, Member, Room, Session, Upload, close_db, init_db
from storage import abort_multipart, complete_multipart, create_multipart, head, presigned_get, presigned_part

log = logging.getLogger("nobar.web")
STATIC = Path(__file__).parent / "static"
PART_SIZE = 64 * 1024 * 1024
MAX_PARTS = 10000


def telegram_user(init_data: str):
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = data.pop("hash", None)
        auth_date = int(data.get("auth_date", "0"))
        now = int(time.time())
        if not received_hash or not auth_date or auth_date > now + 60 or now - auth_date > 86400:
            return None
        check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received_hash):
            return None
        user = json.loads(data.get("user", "{}"))
        return user if user.get("id") else None
    except Exception:
        return None


async def require_user(init_data: str) -> dict:
    user = telegram_user(init_data)
    if not user:
        raise HTTPException(401, "Telegram Mini App authentication required")
    return user


async def room_for(session, code: str) -> Room:
    room = await session.scalar(select(Room).where(Room.code == code.upper(), Room.is_active.is_(True)))
    if not room:
        raise HTTPException(404, "Room tidak ditemukan")
    return room


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await start_polling()
    log.info("NOBAR startup complete")
    try:
        yield
    finally:
        await stop_polling()
        await close_db()


app = FastAPI(title="NOBAR", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def home():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/miniapp")
async def miniapp():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/health")
async def health():
    try:
        me = await bot.get_me()
        return {"status": "ok", "telegram": {"connected": True, "bot_id": me.id, "bot_username": me.username}, "storage": "backblaze-b2"}
    except Exception as exc:
        return {"status": "degraded", "telegram": {"connected": False, "error": str(exc)}, "storage": "backblaze-b2"}


@app.get("/api/dashboard/{group_id}")
async def dashboard(group_id: int, init_data: str = ""):
    user = await require_user(init_data)
    uid = int(user["id"])
    async with Session() as session:
        allowed = await session.scalar(select(Member.id).join(Room, Room.id == Member.room_id).where(Room.group_chat_id == group_id, Member.user_id == uid, Room.is_active.is_(True)).limit(1))
        if allowed is None:
            raise HTTPException(403, "Akses dashboard GC ditolak")
        rooms = (await session.scalars(select(Room).where(Room.group_chat_id == group_id, Room.is_active.is_(True)).order_by(Room.created_at.desc()).limit(30))).all()
        result = []
        for room in rooms:
            members = await session.scalar(select(func.count()).select_from(Member).where(Member.room_id == room.id))
            film = await session.scalar(select(Film).where(Film.room_id == room.id, Film.status == "ready").order_by(Film.created_at.desc()))
            result.append({"code": room.code, "title": room.title, "host_id": room.host_user_id, "members": members, "playing": room.is_playing, "position": room.position, "has_film": bool(film)})
    return {"group_id": group_id, "rooms": result}


@app.get("/api/rooms/{code}")
async def room_api(code: str, init_data: str = ""):
    user = await require_user(init_data)
    uid = int(user["id"])
    async with Session() as session:
        room = await room_for(session, code)
        member = await session.scalar(select(Member.id).where(Member.room_id == room.id, Member.user_id == uid))
        if member is None:
            raise HTTPException(403, "Join room terlebih dahulu via /join KODE")
        members = await session.scalar(select(func.count()).select_from(Member).where(Member.room_id == room.id))
        film = await session.scalar(select(Film).where(Film.room_id == room.id, Film.status == "ready").order_by(Film.created_at.desc()))
    return {"room": {"code": room.code, "title": room.title, "group_id": room.group_chat_id, "host_id": room.host_user_id, "is_host": uid == room.host_user_id, "playing": room.is_playing, "position": room.position, "updated_at": room.updated_at.isoformat()}, "members": members, "film": ({"title": film.title, "size": film.size_bytes, "mime": film.mime_type, "url": presigned_get(film.object_key)} if film else None)}


class SyncIn(BaseModel):
    init_data: str = ""
    playing: bool
    position: float = Field(ge=0)


@app.post("/api/sync/{code}")
async def sync(code: str, payload: SyncIn):
    user = await require_user(payload.init_data)
    uid = int(user["id"])
    async with Session() as session:
        room = await room_for(session, code)
        if room.host_user_id != uid:
            raise HTTPException(403, "Host only")
        room.is_playing = payload.playing
        room.position = payload.position
        from datetime import datetime, timezone
        room.updated_at = datetime.now(timezone.utc)
        await session.commit()
    return {"ok": True}


class StartUploadIn(BaseModel):
    init_data: str = ""
    title: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0, le=settings.max_film_bytes)
    mime: str = Field(default="video/mp4", max_length=120)


@app.post("/api/upload/start/{code}")
async def upload_start(code: str, payload: StartUploadIn):
    user = await require_user(payload.init_data)
    uid = int(user["id"])
    if not payload.mime.startswith("video/"):
        raise HTTPException(400, "File harus berupa video")
    safe_title = payload.title.replace("/", "_").replace("\\", "_")
    async with Session() as session:
        room = await room_for(session, code)
        if room.host_user_id != uid:
            raise HTTPException(403, "Host only")
        existing = (await session.scalars(select(Upload).where(Upload.room_id == room.id, Upload.user_id == uid, Upload.status == "started"))).all()
        for old in existing:
            try:
                abort_multipart(old.object_key, old.upload_id)
            except Exception:
                pass
            old.status = "aborted"
        key = f"films/{room.group_chat_id}/{room.code}/{secrets.token_hex(16)}-{safe_title}"
        upload_id = create_multipart(key, payload.mime)
        upload = Upload(room_id=room.id, user_id=uid, upload_id=upload_id, object_key=key, title=payload.title, size_bytes=payload.size, mime_type=payload.mime)
        session.add(upload)
        await session.commit()
    part_count = (payload.size + PART_SIZE - 1) // PART_SIZE
    if part_count > MAX_PARTS:
        raise HTTPException(400, "Terlalu banyak part")
    parts = [{"part_number": n, "url": presigned_part(key, upload_id, n)} for n in range(1, part_count + 1)]
    return {"upload_id": upload_id, "object_key": key, "part_size": PART_SIZE, "parts": parts}


class PartItem(BaseModel):
    part_number: int = Field(ge=1, le=MAX_PARTS)
    etag: str = Field(min_length=1, max_length=255)


class CompleteUploadIn(BaseModel):
    init_data: str = ""
    upload_id: str
    parts: list[PartItem]


@app.post("/api/upload/complete/{code}")
async def upload_complete(code: str, payload: CompleteUploadIn):
    user = await require_user(payload.init_data)
    uid = int(user["id"])
    async with Session() as session:
        room = await room_for(session, code)
        if room.host_user_id != uid:
            raise HTTPException(403, "Host only")
        upload = await session.scalar(select(Upload).where(Upload.upload_id == payload.upload_id, Upload.room_id == room.id, Upload.user_id == uid, Upload.status == "started"))
        if not upload:
            raise HTTPException(404, "Upload tidak ditemukan atau sudah selesai")
        expected_parts = (upload.size_bytes + PART_SIZE - 1) // PART_SIZE
        if len(payload.parts) != expected_parts or sorted(p.part_number for p in payload.parts) != list(range(1, expected_parts + 1)):
            raise HTTPException(400, "Daftar part tidak lengkap")
        try:
            complete_multipart(upload.object_key, upload.upload_id, [{"ETag": p.etag, "PartNumber": p.part_number} for p in payload.parts])
            meta = head(upload.object_key)
            actual = int(meta.get("ContentLength", -1))
            if actual != upload.size_bytes:
                raise RuntimeError(f"Ukuran B2 {actual} != ukuran upload {upload.size_bytes}")
        except Exception as exc:
            upload.status = "failed"
            await session.commit()
            raise HTTPException(502, f"Gagal menyelesaikan upload: {exc}")
        film = Film(room_id=room.id, owner_user_id=uid, title=upload.title, object_key=upload.object_key, size_bytes=actual, mime_type=upload.mime_type, status="ready")
        session.add(film)
        upload.status = "completed"
        await session.commit()
    return {"ok": True, "title": upload.title}


class AbortUploadIn(BaseModel):
    init_data: str = ""
    upload_id: str


@app.post("/api/upload/abort/{code}")
async def upload_abort(code: str, payload: AbortUploadIn):
    user = await require_user(payload.init_data)
    uid = int(user["id"])
    async with Session() as session:
        room = await room_for(session, code)
        upload = await session.scalar(select(Upload).where(Upload.upload_id == payload.upload_id, Upload.room_id == room.id, Upload.user_id == uid, Upload.status == "started"))
        if not upload:
            return {"ok": True}
        try:
            abort_multipart(upload.object_key, upload.upload_id)
        finally:
            upload.status = "aborted"
            await session.commit()
    return {"ok": True}
