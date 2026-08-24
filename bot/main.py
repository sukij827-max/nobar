import asyncio,threading,uvicorn
from aiogram import Bot,Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from .config import settings
from .db import DB
from .handlers import router
from web.app import app
async def main():
    s=settings();db=DB(s.database_url);await db.connect()
    threading.Thread(target=lambda:uvicorn.run(app,host='0.0.0.0',port=s.port,log_level='warning'),daemon=True).start()
    bot=Bot(s.bot_token,default=DefaultBotProperties(parse_mode=ParseMode.HTML));dp=Dispatcher();dp.include_router(router);dp['settings']=s;dp['db']=db
    try: await dp.start_polling(bot)
    finally: await db.close();await bot.session.close()
if __name__=='__main__':asyncio.run(main())
