import html,secrets,string
from aiogram import Router,Bot
from aiogram.filters import Command,CommandStart
from aiogram.types import Message,InlineKeyboardMarkup,InlineKeyboardButton,WebAppInfo
from db import Session,User,Room,Member
from sqlalchemy import select,func
from config import settings
router=Router()
def code(): return ''.join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(6))
def web(room,upload=False): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🎬 Buka Nobar',web_app=WebAppInfo(url=f'{settings.webapp_url}/miniapp?room={room.code}&upload={1 if upload else 0}'))]])
def dashboard(group_id): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🏠 Dashboard GC',web_app=WebAppInfo(url=f'{settings.webapp_url}/miniapp?group_id={group_id}'))]])
async def access(m:Message,bot:Bot):
    try:
        x=await bot.get_chat_member(settings.required_channel,m.from_user.id); return x.status in {'member','administrator','creator'}
    except Exception:return False
async def ensure_user(u):
    async with Session() as s:
        x=await s.get(User,u.id)
        if not x:s.add(User(user_id=u.id,username=u.username,first_name=u.first_name))
        else:x.username=u.username;x.first_name=u.first_name
        await s.commit()
@router.message(CommandStart())
async def start(m:Message,bot:Bot):
    await ensure_user(m.from_user)
    if not await access(m,bot):return await m.answer(f'⚠️ Join {html.escape(settings.required_channel)} dulu.')
    await m.answer('🎬 <b>NOBAR</b>\nGunakan /nobar di GC untuk membuat room.',reply_markup=dashboard(m.chat.id) if m.chat.type in {'group','supergroup'} else None)
@router.message(Command('help'))
async def help_(m):await m.answer('/nobar — buat room\n/join KODE — masuk room\n/room KODE — status\n/play KODE — buka Mini App\n/upload KODE — upload film\n/rooms — room aktif di GC')
@router.message(Command('nobar'))
async def nobar(m:Message,bot:Bot):
    if m.chat.type not in {'group','supergroup'}:return await m.answer('Gunakan /nobar di GC.')
    if not await access(m,bot):return await m.answer(f'⚠️ Join {html.escape(settings.required_channel)} dulu.')
    await ensure_user(m.from_user);title=(m.text.partition(' ')[2].strip() or f'Nobar {m.from_user.first_name}')[:200]
    async with Session() as s:
        for _ in range(8):
            c=code()
            if not await s.scalar(select(Room).where(Room.code==c)):break
        r=Room(code=c,group_chat_id=m.chat.id,host_user_id=m.from_user.id,title=title);s.add(r);await s.flush();s.add(Member(room_id=r.id,user_id=m.from_user.id));await s.commit();await s.refresh(r)
    await m.answer(f'🍿 <b>Room dibuat</b>\n{html.escape(title)}\nKode: <code>{r.code}</code>',reply_markup=web(r))
@router.message(Command('join'))
async def join(m:Message,bot:Bot):
    if not await access(m,bot):return
    parts=m.text.split(maxsplit=1)
    if len(parts)<2:return await m.answer('Gunakan /join KODE')
    await ensure_user(m.from_user)
    async with Session() as s:
        r=await s.scalar(select(Room).where(Room.code==parts[1].upper(),Room.is_active.is_(True)))
        if not r:return await m.answer('❌ Room tidak ditemukan.')
        if r.group_chat_id!=m.chat.id:return await m.answer('❌ Room ini milik GC lain.')
        if not await s.scalar(select(Member).where(Member.room_id==r.id,Member.user_id==m.from_user.id)):s.add(Member(room_id=r.id,user_id=m.from_user.id));await s.commit()
    await m.answer(f'✅ Masuk <b>{html.escape(r.title)}</b>',reply_markup=web(r))
@router.message(Command('rooms'))
async def rooms(m:Message,bot:Bot):
    if m.chat.type not in {'group','supergroup'}:return await m.answer('Gunakan /rooms di GC.')
    if not await access(m,bot):return
    async with Session() as s:rows=(await s.scalars(select(Room).where(Room.group_chat_id==m.chat.id,Room.is_active.is_(True)).order_by(Room.created_at.desc()).limit(20))).all()
    if not rows:return await m.answer('Tidak ada room aktif di GC ini.')
    await m.answer('\n'.join(f'🎬 <code>{r.code}</code> — {html.escape(r.title)}' for r in rows),reply_markup=dashboard(m.chat.id))
async def open_room(m,bot,cmd,upload=False):
    if not await access(m,bot):return
    p=m.text.split(maxsplit=1)
    if len(p)<2:return await m.answer(f'Gunakan /{cmd} KODE')
    async with Session() as s:r=await s.scalar(select(Room).where(Room.code==p[1].upper(),Room.is_active.is_(True)))
    if not r:return await m.answer('❌ Room tidak ditemukan.')
    if r.group_chat_id!=m.chat.id:return await m.answer('❌ Room ini bukan milik GC ini.')
    if upload and r.host_user_id!=m.from_user.id:return await m.answer('❌ Hanya host yang boleh upload.')
    await m.answer('🎬 Buka Mini App:',reply_markup=web(r,upload))
@router.message(Command('play'))
async def play(m,bot):await open_room(m,bot,'play')
@router.message(Command('upload'))
async def upload(m,bot):await open_room(m,bot,'upload',True)
@router.message(Command('room'))
async def room(m,bot):
    if not await access(m,bot):return
    p=m.text.split(maxsplit=1)
    if len(p)<2:return await m.answer('Gunakan /room KODE')
    async with Session() as s:r=await s.scalar(select(Room).where(Room.code==p[1].upper()));n=await s.scalar(select(func.count()).select_from(Member).where(Member.room_id==r.id)) if r else 0
    if not r:return await m.answer('❌ Room tidak ditemukan.')
    if r.group_chat_id!=m.chat.id:return await m.answer('❌ Room ini bukan milik GC ini.')
    await m.answer(f'🎬 {html.escape(r.title)}\n👥 {n} peserta\n{"▶️ Playing" if r.is_playing else "⏸️ Paused"}\nPosisi: {int(r.position)} detik')
