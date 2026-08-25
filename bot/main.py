import asyncio,logging,threading,time,uvicorn
from aiogram import Bot,Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from config import settings
from db import init_db,close_db
from bot.handlers import router
from web.app import app
class Server(uvicorn.Server):
    def install_signal_handlers(self):pass
def start_web():
    s=Server(uvicorn.Config(app,host='0.0.0.0',port=settings.port,log_level='info'));t=threading.Thread(target=s.run,daemon=True);t.start()
    for _ in range(100):
        if s.started:return s
        if not t.is_alive():raise RuntimeError('Web server stopped before startup completed.')
        time.sleep(.05)
    raise RuntimeError('Web server startup timeout.')
async def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s | %(levelname)s | %(message)s');await init_db();server=start_web();bot=Bot(settings.bot_token,default=DefaultBotProperties(parse_mode=ParseMode.HTML));dp=Dispatcher();dp.include_router(router)
    try: await bot.delete_webhook(drop_pending_updates=False); await bot.get_me(); await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
    finally: server.should_exit=True; await bot.session.close(); await close_db()
if __name__=='__main__':asyncio.run(main())
