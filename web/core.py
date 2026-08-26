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
from db import Film, Member, Room, Session, close_db, init_db
from storage import presigned_get, presigned_put

log = logging.getLogger("nobar")
STATIC = Path(__file__).parent / "static"


def telegram_user(init_data: str):
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = data.pop("hash", None)
        auth_date = int(data.get("auth_date", "0"))
        now = int(time.time())
        if not received_hash or not auth_date or auth_date > now + 60 or now - auth_date > 86400:
            return None
        check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received_hash):
            return None
        return json.loads(data.get("user", "{}"))
    except Exception:
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Clean startup order: database first, then exactly one Telegram consumer.
    await init_db()
    try:
        await start_polling()
        log.info("NOBAR startup complete: Telegram polling is active")
        yield
    except Exception:
        log.exception("NOBAR startup failed")
        raise
    finally:
        await stop_polling()
        await close_db()


app = FastAPI(title="NOBAR Mini App", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/health")
async def health():
    try:
        me = await bot.get_me()
        telegram_ok = True
        telegram_error = None
    except Exception as exc:
        me = None
        telegram_ok = False
        telegram_error = str(exc)
    return {
        "status": "ok" if telegram_ok else "degraded",
        "service": "nobar",
        "telegram": {
            "mode": "polling",
            "connected": telegram_ok,
            "bot_id": me.id if me else None,
            "bot_username": me.username if me else None,
            "error": telegram_error,
        },
    }


@app.get("/")
async def home():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/miniapp")
async def miniapp():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


async def room_for(code: str):
    async with Session() as session:
        room = await session.scalar(select(Room).where(Room.code == code.upper(), Room.is_active.is_(True)))
    if not room:
        raise HTTPException(404, "Room tidak ditemukan")
    return room


@app.get("/api/dashboard/{group_id}")
async def dashboard(group_id: int, init_data: str = ""):
    user = telegram_user(init_data)
    if not user:
        raise HTTPException(401, "Telegram auth required")
    uid = int(user["id"])
    async with Session() as session:
        allowed = await session.scalar(
            select(Member.id)
            .join(Room, Room.id == Member.room_id)
            .where(Room.group_chat_id == group_id, Member.user_id == uid, Room.is_active.is_(True))
            .limit(1)
        )
        if allowed is None:
            raise HTTPException(403, "Akses dashboard GC ditolak")
        rooms = (await session.scalars(select(Room).where(Room.group_chat_id == group_id, Room.is_active.is_(True)).order_by(Room.created_at.desc()).limit(30))).all()
        result = []
        for room in rooms:
            members = await session.scalar(select(func.count()).select_from(Member).where(Member.room_id == room.id))
            result.append({"code": room.code, "title": room.title, "host_id": room.host_user_id, "members": members, "playing": room.is_playing, "position": room.position})
    return {"group_id": group_id, "rooms": result}


@app.get("/api/rooms/{code}")
async def room_api(code: str, init_data: str = ""):
    user = telegram_user(init_data)
    if not user:
        raise HTTPException(401, "Telegram auth required")
    room = await room_for(code)
    uid = int(user["id"])
    async with Session() as session:
        member = await session.scalar(select(Member).where(Member.room_id == room.id, Member.user_id == uid))
        if not member:
            raise HTTPException(403, "Join room terlebih dahulu")
        members = await session.scalar(select(func.count()).select_from(Member).where(Member.room_id == room.id))
        film = await session.scalar(select(Film).where(Film.room_id == room.id, Film.status == "ready").order_by(Film.created_at.desc()))
    return {"room": {"code": room.code, "title": room.title, "group_id": room.group_chat_id, "host_id": room.host_user_id, "is_host": uid == room.host_user_id, "playing": room.is_playing, "position": room.position, "updated_at": room.updated_at.isoformat()}, "members": members, "film": ({"title": film.title, "size": film.size_bytes, "mime": film.mime_type, "url": presigned_get(film.object_key)} if film else None)}


class SyncIn(BaseModel):
    init_data: str = ""
    playing: bool = False
    position: float = Field(ge=0)


@app.post("/api/sync/{code}")
async def sync(code: str, payload: SyncIn):
    user = telegram_user(payload.init_data)
    room = await room_for(code)
    if not user or int(user["id"]) != room.host_user_id:
        raise HTTPException(403, "Host only")
    async with Session() as session:
        current = await session.get(Room, room.id)
        if not current:
            raise HTTPException(404, "Room tidak ditemukan")
        current.is_playing = payload.playing
        current.position = payload.position
        await session.commit()
    return {"ok": True}


class UploadIn(BaseModel):
    init_data: str = ""
    title: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0, le=5 * 1024**3)
    mime: str = "video/mp4"


@app.post("/api/upload/{code}")
async def upload(code: str, payload: UploadIn):
    user = telegram_user(payload.init_data)
    room = await room_for(code)
    if not user or int(user["id"]) != room.host_user_id:
        raise HTTPException(403, "Host only")
    key = f"films/{room.group_chat_id}/{room.code}/{secrets.token_hex(12)}-{payload.title.replace('/', '_')}"
    async with Session() as session:
        session.add(Film(room_id=room.id, owner_user_id=room.host_user_id, title=payload.title, object_key=key, size_bytes=payload.size, mime_type=payload.mime))
        await session.commit()
    return {"upload_url": presigned_put(key, payload.mime), "object_key": key}
