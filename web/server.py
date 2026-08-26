import hashlib
import logging
from contextlib import asynccontextmanager

from fastapi import Request
from fastapi.responses import JSONResponse
from aiogram.types import BotCommand, BotCommandScopeDefault

from bot.runtime import bot, dp
from config import settings
from db import close_db, init_db
from web.core import app

log = logging.getLogger("nobar.webhook")
WEBHOOK_PATH = "/telegram/webhook"


def webhook_secret() -> str:
    return hashlib.sha256(settings.bot_token.encode("utf-8")).hexdigest()


def webhook_url() -> str:
    return f"{settings.webapp_url}{WEBHOOK_PATH}"


async def set_commands():
    await bot.set_my_commands([
        BotCommand(command="start", description="Mulai NOBAR"),
        BotCommand(command="menu", description="Buka menu utama"),
        BotCommand(command="nobar", description="Buat room langsung"),
        BotCommand(command="join", description="Join room dengan kode"),
        BotCommand(command="rooms", description="Lihat NOBAR aktif"),
        BotCommand(command="room", description="Info room"),
        BotCommand(command="play", description="Buka player NOBAR"),
        BotCommand(command="upload", description="Kirim film ke bot"),
        BotCommand(command="invite", description="Share room ke grup"),
        BotCommand(command="feedback", description="Kirim feedback"),
    ], scope=BotCommandScopeDefault())


@asynccontextmanager
async def webhook_lifespan(app_instance):
    await init_db()
    try:
        url = webhook_url()
        if not settings.webapp_url.startswith("https://"):
            raise RuntimeError("WEBAPP_URL must be HTTPS for Telegram webhook")
        await bot.set_webhook(
            url=url,
            secret_token=webhook_secret(),
            allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"],
            drop_pending_updates=False,
        )
        await set_commands()
        info = await bot.get_webhook_info()
        if info.url != url:
            raise RuntimeError(f"Telegram webhook mismatch: {info.url!r} != {url!r}")
        log.info("NOBAR Telegram webhook ready: bot=@%s url=%s pending=%s last_error=%r", (await bot.get_me()).username, url, info.pending_update_count, info.last_error_message)
        yield
    except Exception:
        log.exception("NOBAR startup failed while configuring Telegram webhook")
        await close_db()
        raise
    finally:
        await bot.session.close()
        await close_db()


app.router.lifespan_context = webhook_lifespan


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    expected = webhook_secret()
    received = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not received or received != expected:
        return JSONResponse({"ok": False, "error": "Unauthorized webhook"}, status_code=401)
    try:
        update = await request.json()
        await dp.feed_raw_update(bot, update)
        return {"ok": True}
    except Exception:
        log.exception("Telegram webhook update processing failed")
        return JSONResponse({"ok": False}, status_code=500)
