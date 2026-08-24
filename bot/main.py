import asyncio
import os
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from .config import settings
from .db import DB
from .handlers import router
from web.app import app


async def run_bot_services():
    """Keep application services retrying without taking down /health."""
    while True:
        db = None
        bot = None
        try:
            s = settings()
            db = DB(s.database_url)
            await db.connect()

            bot = Bot(
                s.bot_token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            dp = Dispatcher()
            dp.include_router(router)
            dp["settings"] = s
            dp["db"] = db
            print("Application services ready")
            await dp.start_polling(bot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Application startup/service failed: {type(exc).__name__}: {exc}")
            await asyncio.sleep(5)
        finally:
            if bot is not None:
                try:
                    await bot.session.close()
                except Exception:
                    pass
            if db is not None:
                try:
                    await db.close()
                except Exception:
                    pass


async def main():
    # Railway supplies PORT. Keep the HTTP server independent from DB/Bot
    # startup so /health remains reachable even when a dependency is broken.
    port = int(os.getenv("PORT", "8000"))
    server_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(server_config)
    services_task = asyncio.create_task(run_bot_services())

    try:
        await server.serve()
    finally:
        services_task.cancel()
        try:
            await services_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
