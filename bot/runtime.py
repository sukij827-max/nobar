from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from config import settings
from bot.handlers import router

# One Bot + one Dispatcher for the entire process.
# They are created once and used only from FastAPI's single asyncio loop.
bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
dp.include_router(router)
