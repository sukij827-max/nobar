import asyncio,logging,threading,time,uvicorn
from config import settings
from db import init_db,close_db
from bot.runtime import bot
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
    logging.basicConfig(level=logging.INFO,format='%(asctime)s | %(levelname)s | %(message)s');await init_db();server=start_web();await bot.get_me()
    webhook=f'{settings.webapp_url.rstrip("/")}/telegram/webhook'
    await bot.set_webhook(webhook,drop_pending_updates=False,allowed_updates=['message','callback_query','chat_member','my_chat_member'])
    try:
        while True: await asyncio.sleep(3600)
    finally:
        await bot.delete_webhook(drop_pending_updates=False);server.should_exit=True;await bot.session.close();await close_db()
if __name__=='__main__':asyncio.run(main())
