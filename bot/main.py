import asyncio
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from .config import settings
from .db import DB
from .handlers import router
from web.app import app


async def main():
    # Build/validate environment configuration without touching the network yet.
    s = settings()

    # Start HTTP first so Railway can reach /health even while PostgreSQL is
    # starting up or temporarily unavailable. Railway provides PORT.
    server_config = uvicorn.Config(
        app,
        host='0.0.0.0',
        port=s.port,
        log_level='warning',
        access_log=False,
    )
    server = uvicorn.Server(server_config)
    server_task = asyncio.create_task(server.serve())

    # Give Uvicorn a scheduling turn to bind the socket before doing DB work.
    await asyncio.sleep(0)

    db = DB(s.database_url)
    try:
        while True:
            try:
                await db.connect()
                break
            except Exception as exc:
                print(f'Database connection failed: {type(exc).__name__}; retrying in 5s')
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
        server.should_exit = True
        await server_task


if __name__ == '__main__':
    asyncio.run(main())
