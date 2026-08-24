import asyncio
import logging
import threading
import time

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import settings
from .db import DB
from .handlers import router
from web.app import app

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
)
log = logging.getLogger('nobar')


class RailwayUvicornServer(uvicorn.Server):
    """Run Uvicorn in a worker thread without installing signal handlers."""

    def install_signal_handlers(self):
        pass


def start_web_server(port: int):
    config = uvicorn.Config(
        app,
        host='0.0.0.0',
        port=port,
        log_level='info',
        access_log=True,
    )
    server = RailwayUvicornServer(config)
    thread = threading.Thread(target=server.run, name='uvicorn', daemon=True)
    thread.start()

    # Do not start Telegram polling until the HTTP server has had a chance to
    # bind its Railway port. A bind/startup failure becomes a real startup
    # exception instead of silently leaving the service half-alive.
    for _ in range(100):
        if server.started:
            log.info('Web server ready on port %s', port)
            return server, thread
        if not thread.is_alive():
            raise RuntimeError('Uvicorn berhenti sebelum server siap.')
        time.sleep(0.05)

    if not server.started:
        raise RuntimeError('Uvicorn belum siap setelah 5 detik.')
    return server, thread


async def main():
    s = settings()
    log.info('Starting Nobar service...')

    db = DB(s.database_url)
    await db.connect()
    log.info('PostgreSQL connected and schema migration completed.')

    server = None
    bot = Bot(
        s.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)
    dp['settings'] = s
    dp['db'] = db

    try:
        server, _ = start_web_server(s.port)

        await bot.delete_webhook(drop_pending_updates=False)
        me = await bot.get_me()
        log.info('Telegram bot authenticated: @%s (id=%s)', me.username, me.id)
        log.info('Starting Telegram polling...')

        await dp.start_polling(
            bot,
            handle_signals=False,
            close_bot_session=False,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception('Nobar service stopped because of an error.')
        raise
    finally:
        if server is not None:
            server.should_exit = True
        await db.close()
        try:
            await bot.session.close()
        except Exception:
            pass


if __name__ == '__main__':
    asyncio.run(main())
