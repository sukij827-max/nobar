import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from bot.fixes import router as fixes_router
from bot.direct_room import router as direct_room_router
from bot.handlers import router

log = logging.getLogger("nobar.telegram")

bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
# Fix/router layer must be first so direct-room creation works in private and
# group chats, group messages never receive private-only web_app buttons, and
# deep-link joins/admin user pages are handled before legacy handlers.
dp.include_router(fixes_router)
dp.include_router(direct_room_router)
dp.include_router(router)

_polling_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


async def _poll_forever() -> None:
    """Run the single Telegram consumer and never fail silently."""
    assert _stop_event is not None
    while not _stop_event.is_set():
        try:
            await dp.start_polling(
                bot,
                allowed_updates=[
                    "message",
                    "callback_query",
                    "chat_member",
                    "my_chat_member",
                ],
                handle_signals=False,
            )
            if not _stop_event.is_set():
                log.error("Telegram polling stopped unexpectedly; restarting")
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Telegram polling crashed; retrying in 3 seconds")
            if not _stop_event.is_set():
                await asyncio.sleep(3)


async def start_polling() -> None:
    global _polling_task, _stop_event
    if _polling_task and not _polling_task.done():
        return

    await bot.delete_webhook(drop_pending_updates=False)
    me = await bot.get_me()
    log.info("Telegram bot verified: @%s (%s)", me.username, me.id)

    _stop_event = asyncio.Event()
    _polling_task = asyncio.create_task(_poll_forever(), name="nobar-telegram-polling")
    await asyncio.sleep(0)
    log.info("Telegram polling task started")


async def stop_polling() -> None:
    global _polling_task, _stop_event
    if _stop_event:
        _stop_event.set()
    task = _polling_task
    _polling_task = None
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _stop_event = None
    await bot.session.close()
