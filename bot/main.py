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


async def main():
    # Railway assigns PORT automatically. Start HTTP first so /health is
    # reachable even if configuration or PostgreSQL is temporarily unavailable.
    port = int(os.getenv('PORT', '8000'))
    server_config = uvicorn.Config(
        app,
        host='0.0.0.0',
        port=port,
        log_level='info',
        access_log=False,
    )
    server = uvicorn.Server(server_config)
    server_task = asyncio.create_task(server.serve())

    try:
        # Wait until Uvicorn has actually bound the socket before continuing.
        for _ in range(200):
            if server.started:
                break
            if server_task.done():
                exc = server_task.exception()
                if exc:
                    raise exc
                raise RuntimeError('Uvicorn stopped before binding the HTTP port')
            await asyncio.sleep(0.05)
        if not server.started:
            raise RuntimeError('Uvicorn did not bind the HTTP port within 10 seconds')

        # Only after /health is available do we validate application settings.
        s = settings()
        db = DB(s.database_url)
        try:
            while True:
                try:
                    await db.connect()
                    break
                except Exception as exc:
                    print(f'Database connection failed: {type(exc).__name__}; retrying in 5s', flush=True)
                    await asyncio.sleep(5)

            bot = Bot(
                s.bot_token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            dp = Dispatcher()
            dp.include_router(router)
            dp['settings'] = s
            dp['db'] = db

            try:
                await dp.start_polling(bot)
            finally:
                await bot.session.close()
        finally:
            await db.close()
    finally:
        server.should_exit = True
        await server_task


if __name__ == '__main__':
    asyncio.run(main())
