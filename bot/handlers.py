import secrets,string,asyncio
from aiogram import Router,Bot
from aiogram.filters import Command,CommandStart
from aiogram.types import Message,InlineKeyboardMarkup,InlineKeyboardButton,WebAppInfo
router=Router()
def code(): return ''.join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(6))
def kb(url): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🎬 Buka Nobar',web_app=WebAppInfo(url=url))]])
async def access(m,bot,s):
    try: x=await bot.get_chat_member(s.required_channel,m.from_user.id); ok=x.status in {'member','administrator','creator'}
    except: ok=False
    if not ok: await m.answer(f'⚠️ Join channel {s.required_channel} dulu.'); return False
    return True
@router.message(CommandStart())
async def start(m:Message,bot:Bot,settings,db):
    await db.user(m.from_user)
    if await access(m,bot,settings): await m.answer('🎬 <b>Nobar</b>\nGunakan /nobar di grup untuk membuat room. Setelah room dibuat, host upload film sampai 5 GiB langsung dari Mini App.',parse_mode='HTML')
@router.message(Command('help'))
async def help(m): await m.answer('/nobar — buat room grup\n/join KODE — join\n/room KODE — info\n/play KODE — buka Mini App\n/rooms — room aktif\n/upload — buka uploader host\n/broadcast — owner, reply teks/foto')
@router.message(Command('nobar'))
async def nobar(m,bot,settings,db):
    if m.chat.type not in {'group','supergroup'}: return await m.answer('Gunakan /nobar di grup.')
    if not await access(m,bot,settings): return
    await db.user(m.from_user);await db.group(m.chat)
    title=m.text.partition(' ')[2].strip() or f'Nobar {m.from_user.first_name}';r=await db.make_room(code(),m.chat.id,m.from_user.id,title);await db.join(r['id'],m.from_user.id)
    await m.answer(f'🍿 <b>Room dibuat</b>\n{title}\nKode: <code>{r["code"]}</code>\nHost bisa upload film maksimal 5 GiB dari Mini App.',parse_mode='HTML',reply_markup=kb(f'{settings.webapp_url}/?room={r["code"]}'))
@router.message(Command('join'))
async def join(m,bot,settings,db):
    if not await access(m,bot,settings): return
    a=m.text.split(maxsplit=1);r=await db.room(a[1] if len(a)>1 else '')
    if not r:return await m.answer('❌ Room tidak ditemukan.')
    await db.join(r['id'],m.from_user.id);await m.answer(f'✅ Masuk {r["title"]}',reply_markup=kb(f'{settings.webapp_url}/?room={r["code"]}'))
@router.message(Command('room'))
async def room(m,db):
    a=m.text.split(maxsplit=1);r=await db.room(a[1] if len(a)>1 else '')
    if not r:return await m.answer('❌ Room tidak ditemukan.')
    await m.answer(f'🎬 {r["title"]}\nKode: {r["code"]}\nStatus: {"▶️ Playing" if r["is_playing"] else "⏸️ Paused"}\nPosisi: {int(r["position_seconds"])} detik')
@router.message(Command('play'))
async def play(m,bot,settings,db):
    if not await access(m,bot,settings): return
    a=m.text.split(maxsplit=1);r=await db.room(a[1] if len(a)>1 else '')
    if not r:return await m.answer('❌ Room tidak ditemukan.')
    await db.join(r['id'],m.from_user.id);await m.answer('🎥 Buka Mini App:',reply_markup=kb(f'{settings.webapp_url}/?room={r["code"]}'))
@router.message(Command('upload'))
async def upload(m,bot,settings,db):
    if not await access(m,bot,settings): return
    a=m.text.split(maxsplit=1);r=await db.room(a[1] if len(a)>1 else '')
    if not r:return await m.answer('❌ Room tidak ditemukan.')
    if r['host_user_id']!=m.from_user.id:return await m.answer('❌ Hanya host room yang boleh upload film.')
    await db.join(r['id'],m.from_user.id);await m.answer('⬆️ Buka uploader:',reply_markup=kb(f'{settings.webapp_url}/?room={r["code"]}&upload=1'))
@router.message(Command('rooms'))
async def rooms(m,db):
    rows=await db.pool.fetch('SELECT code,title FROM rooms WHERE group_chat_id=$1 AND is_active',m.chat.id)
    await m.answer('\n'.join(f'🎬 {x["code"]} — {x["title"]}' for x in rows) or 'Tidak ada nobar aktif.')
@router.message(Command('addfilm'))
async def addfilm(m,bot,settings,db):
    if not await access(m,bot,settings): return
    t=m.reply_to_message
    if not t or not (t.video or t.document): return await m.answer('Untuk film besar, gunakan /upload. Telegram Bot API saat ini hanya mengizinkan bot mengunduh file sampai 20 MB.')
    media=t.video or t.document; size=getattr(media,'file_size',0) or 0
    if size>20*1024*1024: return await m.answer('❌ Film ini terlalu besar untuk /addfilm. Gunakan /upload agar file sampai 5 GiB dikirim langsung ke object storage.')
    await m.answer('ℹ️ /addfilm versi Telegram hanya untuk file kecil. Gunakan /upload untuk film sampai 5 GiB.')
@router.message(Command('broadcast'))
async def broadcast(m,bot,settings,db):
    if m.from_user.id!=settings.owner_id:return await m.answer('❌ Khusus owner.')
    t=m.reply_to_message
    if not t:return await m.answer('Reply pesan teks atau foto lalu /broadcast.')
    rows=await db.pool.fetch('SELECT user_id FROM users');ok=0
    for x in rows:
        try:
            if t.photo: await bot.send_photo(x['user_id'],t.photo[-1].file_id,caption=t.caption or '')
            elif t.text: await bot.send_message(x['user_id'],t.text)
            else: await bot.copy_message(x['user_id'],m.chat.id,t.message_id)
            ok+=1;await asyncio.sleep(.04)
        except: pass
    await m.answer(f'📣 Broadcast selesai: {ok}/{len(rows)}')
