import asyncio
import logging
import threading
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from .config import settings
from .db import DB
from .handlers import router
from web.app import app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("nobar")

async def main():
    s = settings()
    db = DB(s.database_url)

    # Fail loudly once if the database cannot be initialized. This prevents
    # Railway from showing a healthy HTTP server while polling is dead.
    try:
        await db.connect()
        log.info("Database connected and schema migration completed.")
    except Exception:
        log.exception("DATABASE STARTUP FAILED")
        raise

    threading.Thread(
        target=lambda: uvicorn.run(
            app, host="0.0.0.0", port=s.port, log_level="info"
        ),
        daemon=True
    ).start()

    bot = Bot(
        s.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    dp.include_router(router)
    dp["settings"] = s
    dp["db"] = db

    try:
        log.info("Starting Telegram polling...")
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    except Exception:
        log.exception("TELEGRAM POLLING FAILED")
        raise
    finally:
        await db.close()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
