import hashlib,hmac,json,time,secrets
from urllib.parse import parse_qsl
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from aiogram.types import Update
from pydantic import BaseModel,Field
from sqlalchemy import select,func
from config import settings
from db import Session,Room,Member,Film
from storage import presigned_put,presigned_get
from bot.runtime import bot,dp
app=FastAPI(title='NOBAR Mini App',docs_url=None,redoc_url=None); STATIC=Path(__file__).parent/'static'; app.mount('/static',StaticFiles(directory=STATIC),name='static')
def user(init):
    try:
        p=dict(parse_qsl(init,keep_blank_values=True)); h=p.pop('hash',None); auth=int(p.get('auth_date','0'))
        if not h or not auth or auth>time.time()+60 or time.time()-auth>86400:return None
        check='\n'.join(f'{k}={v}' for k,v in sorted(p.items())); secret=hmac.new(b'WebAppData',settings.bot_token.encode(),hashlib.sha256).digest(); exp=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(exp,h):return None
        return json.loads(p.get('user','{}'))
    except Exception:return None
class SyncIn(BaseModel): init_data:str=''; playing:bool=False; position:float=Field(ge=0)
class UploadIn(BaseModel): init_data:str=''; title:str=Field(min_length=1,max_length=255); size:int=Field(gt=0,le=5*1024**3); mime:str='video/mp4'
@app.get('/health')
async def health():return {'status':'ok','service':'nobar','version':'1.0'}
@app.post('/telegram/webhook')
async def telegram_webhook(request:Request):
    secret=request.headers.get('X-Telegram-Bot-Api-Secret-Token')
    expected=hmac.new(settings.bot_token.encode(),settings.webapp_url.encode(),hashlib.sha256).hexdigest()[:32]
    if not secret or not hmac.compare_digest(secret,expected):raise HTTPException(403,'Invalid webhook secret')
    try:update=Update.model_validate(await request.json());await dp.feed_update(bot,update);return {'ok':True}
    except Exception:raise HTTPException(400,'Invalid Telegram update')
@app.get('/')
async def home():return FileResponse(STATIC/'index.html',headers={'Cache-Control':'no-store'})
@app.get('/miniapp')
async def miniapp():return FileResponse(STATIC/'index.html',headers={'Cache-Control':'no-store'})
async def room_for(code):
    async with Session() as s:r=await s.scalar(select(Room).where(Room.code==code.upper(),Room.is_active.is_(True)))
    if not r:raise HTTPException(404,'Room tidak ditemukan')
    return r
@app.get('/api/rooms/{code}')
async def room_api(code:str,init_data:str=''):
    u=user(init_data);r=await room_for(code)
    async with Session() as s:
        n=await s.scalar(select(func.count()).select_from(Member).where(Member.room_id==r.id)); f=await s.scalar(select(Film).where(Film.room_id==r.id,Film.status=='ready').order_by(Film.created_at.desc()))
    return {'room':{'code':r.code,'title':r.title,'group_id':r.group_chat_id,'host_id':r.host_user_id,'is_host':bool(u and int(u['id'])==r.host_user_id),'playing':r.is_playing,'position':r.position,'updated_at':r.updated_at.isoformat()},'members':n,'film':({'title':f.title,'size':f.size_bytes,'mime':f.mime_type,'url':presigned_get(f.object_key)} if f else None)}
@app.get('/api/dashboard/{group_id}')
async def dashboard(group_id:int,init_data:str=''):
    u=user(init_data)
    if not u:raise HTTPException(401,'Telegram auth required')
    async with Session() as s:
        rows=(await s.scalars(select(Room).where(Room.group_chat_id==group_id,Room.is_active.is_(True)).order_by(Room.created_at.desc()).limit(30))).all();out=[]
        for r in rows:
            n=await s.scalar(select(func.count()).select_from(Member).where(Member.room_id==r.id));out.append({'code':r.code,'title':r.title,'host_id':r.host_user_id,'members':n,'playing':r.is_playing,'position':r.position})
    return {'group_id':group_id,'rooms':out}
@app.post('/api/sync/{code}')
async def sync(code:str,p:SyncIn):
    u=user(p.init_data);r=await room_for(code)
    if not u or int(u['id'])!=r.host_user_id:raise HTTPException(403,'Host only')
    async with Session() as s:x=await s.get(Room,r.id);x.is_playing=p.playing;x.position=p.position;await s.commit()
    return {'ok':True}
@app.post('/api/upload/{code}')
async def upload(code:str,p:UploadIn):
    u=user(p.init_data);r=await room_for(code)
    if not u or int(u['id'])!=r.host_user_id:raise HTTPException(403,'Host only')
    key=f'films/{r.group_chat_id}/{r.code}/{secrets.token_hex(12)}-{p.title.replace("/","_")}'
    async with Session() as s:s.add(Film(room_id=r.id,owner_user_id=r.host_user_id,title=p.title,object_key=key,size_bytes=p.size,mime_type=p.mime));await s.commit()
    return {'upload_url':presigned_put(key,p.mime),'object_key':key}
