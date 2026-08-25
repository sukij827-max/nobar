from aiogram import Bot,Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from config import settings
from bot.handlers import router
bot=Bot(settings.bot_token,default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp=Dispatcher()
dp.include_router(router)
