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
    """Run Telegram polling independently from the HTTP health server."""
    retry = 0
    while True:
        db = None
        bot = None
        try:
            s = settings()
            print("[BOT] Configuration loaded", flush=True)

            db = DB(s.database_url)
            await db.connect()

            print("[BOT] Creating Telegram client...", flush=True)
            bot = Bot(
                s.bot_token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            print("[BOT] Telegram client created", flush=True)

            # Ensure an old webhook does not prevent long polling after redeploy.
            print("[BOT] Clearing any existing webhook...", flush=True)
            await bot.delete_webhook(drop_pending_updates=False)

            dp = Dispatcher()
            dp.include_router(router)
            dp["settings"] = s
            dp["db"] = db

            retry = 0
            print("[BOT] Starting Telegram polling...", flush=True)
            await dp.start_polling(bot)
            print("[BOT] Polling stopped; restarting...", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            retry += 1
            print(
                f"[BOT] Service attempt #{retry} failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            print("[BOT] Retrying in 5 seconds...", flush=True)
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
    # Railway supplies PORT. Keep /health independent from DB/Telegram startup.
    port = int(os.getenv("PORT", "8000"))
    print(f"[HTTP] Starting health server on 0.0.0.0:{port}", flush=True)
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
