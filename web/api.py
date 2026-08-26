import hashlib
import hmac
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qsl

from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from bot.runtime import bot, dp
from config import settings
from db import Film, Member, Room, Session, close_db, init_db
from storage import presigned_get, presigned_put

log = logging.getLogger("nobar")
STATIC = Path(__file__).parent / "static"
WEBHOOK_PATH = "/telegram/webhook"


def webhook_secret() -> str:
    return hmac.new(
        settings.bot_token.encode(),
        settings.webapp_url.encode(),
        hashlib.sha256,
    ).hexdigest()[:32]


def webhook_url() -> str:
    return f"{settings.webapp_url}{WEBHOOK_PATH}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Keep one webhook for the lifetime of this service. Do not remove it on
    # shutdown: Telegram should continue pointing at NOBAR across restarts.
    await init_db()
    try:
        me = await bot.get_me()
        url = webhook_url()
        if not url.startswith("https://"):
            raise RuntimeError("WEBAPP_URL must be HTTPS for Telegram webhook")

        await bot.set_webhook(
            url=url,
            secret_token=webhook_secret(),
            drop_pending_updates=False,
            allowed_updates=[
                "message",
                "callback_query",
                "chat_member",
                "my_chat_member",
            ],
        )
        info = await bot.get_webhook_info()
        if info.url != url:
            raise RuntimeError(f"Telegram webhook mismatch: {info.url!r} != {url!r}")
        log.info(
            "NOBAR Telegram ready: bot=@%s webhook=%s pending=%s last_error=%r",
            me.username, url, info.pending_update_count, info.last_error_message,
        )
        yield
    except Exception:
        log.exception("NOBAR startup failed while configuring Telegram webhook")
        await close_db()
        raise
    finally:
        # IMPORTANT: do not call delete_webhook() here. A Railway restart must
        # not unregister the Telegram webhook. Only close local resources.
        try:
            await bot.session.close()
        finally:
            await close_db()


app = FastAPI(title="NOBAR Mini App", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


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


@app.get("/health")
async def health():
    info = await bot.get_webhook_info()
    return {
        "status": "ok",
        "service": "nobar",
        "telegram": {
            "webhook_url_configured": info.url == webhook_url(),
            "webhook_url": info.url,
            "pending_updates": info.pending_update_count,
            "last_error": info.last_error_message,
            "last_error_date": info.last_error_date,
        },
    }


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not supplied or not hmac.compare_digest(supplied, webhook_secret()):
        log.warning("Rejected Telegram webhook request: invalid secret")
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    try:
        payload = await request.json()
        update = Update.model_validate(payload)
        await dp.feed_update(bot, update)
        return {"ok": True}
    except Exception as exc:
        log.exception("Telegram update processing failed")
        raise HTTPException(status_code=500, detail="Webhook processing failed") from exc


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
