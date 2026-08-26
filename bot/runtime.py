import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from bot.handlers import router

log = logging.getLogger("nobar.telegram")

bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
dp.include_router(router)

_polling_task: asyncio.Task | None = None


async def start_polling() -> None:
    """Start the only Telegram consumer used by NOBAR.

    NOBAR deliberately uses long polling instead of a Telegram webhook. This
    removes the webhook-registration race and guarantees that Railway restarts
    cannot silently unregister the bot endpoint. Only one Railway replica must
    run this process.
    """
    global _polling_task
    if _polling_task and not _polling_task.done():
        return

    await bot.delete_webhook(drop_pending_updates=False)
    me = await bot.get_me()
    log.info("Telegram consumer ready: @%s (%s)", me.username, me.id)
    _polling_task = asyncio.create_task(
        dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"],
            handle_signals=False,
        )
    )


async def stop_polling() -> None:
    global _polling_task
    task = _polling_task
    _polling_task = None
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await bot.session.close()
