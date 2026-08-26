import hashlib
import html
import os
import secrets
import string
import tempfile
from datetime import datetime, timezone

from aiogram import Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from sqlalchemy import func, or_, select

from config import settings
from db import Feedback, Film, Group, GroupMember, Member, Room, Session, User
from storage import upload_file, delete_object

router = Router()


def make_code():
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))


def main_menu(admin=False):
    rows = [
        [InlineKeyboardButton(text="🎬 Buat Room", callback_data="menu:create"), InlineKeyboardButton(text="🔗 Join Room", callback_data="menu:join")],
        [InlineKeyboardButton(text="🔎 Cek NOBAR", callback_data="menu:rooms"), InlineKeyboardButton(text="📋 Info Room", callback_data="menu:info")],
        [InlineKeyboardButton(text="📤 Tambah Film", callback_data="menu:upload"), InlineKeyboardButton(text="👤 Room Saya", callback_data="menu:myrooms")],
        [InlineKeyboardButton(text="❓ Bantuan", callback_data="menu:help"), InlineKeyboardButton(text="💬 Feedback", callback_data="menu:feedback")],
    ]
    if admin:
        rows.append([InlineKeyboardButton(text="🔐 Panel Admin", callback_data="admin:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def room_menu(room):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Buka NOBAR", web_app=WebAppInfo(url=f"{settings.webapp_url}/miniapp?room={room.code}"))],
        [InlineKeyboardButton(text="📤 Upload Film", callback_data=f"roomupload:{room.id}"), InlineKeyboardButton(text="🔗 Share ke Grup", callback_data=f"share:{room.id}")],
        [InlineKeyboardButton(text="🎞️ Info Film", callback_data=f"roomfilm:{room.id}"), InlineKeyboardButton(text="👥 Member", callback_data=f"roommembers:{room.id}")],
        [InlineKeyboardButton(text="🚪 Keluar Room", callback_data=f"leave:{room.id}")],
    ])


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistik", callback_data="admin:stats"), InlineKeyboardButton(text="👥 Pengguna", callback_data="admin:users")],
        [InlineKeyboardButton(text="🎞️ Database Film", callback_data="admin:films"), InlineKeyboardButton(text="🏠 Room Aktif", callback_data="admin:rooms")],
        [InlineKeyboardButton(text="📝 Broadcast Teks", callback_data="admin:btext"), InlineKeyboardButton(text="🖼️ Broadcast Foto", callback_data="admin:bphoto")],
        [InlineKeyboardButton(text="📝 Feedback", callback_data="admin:feedback")],
        [InlineKeyboardButton(text="⬅️ Menu", callback_data="menu:back")],
    ])


async def channel_access(bot, user_id):
    try:
        m = await bot.get_chat_member(settings.required_channel, user_id)
        return m.status in {"member", "administrator", "creator"}
    except Exception:
        return False


async def ensure_user(user):
    async with Session() as session:
        now = datetime.now(timezone.utc)
        result = await session.execute(select(User).where(or_(User.user_id == user.id, User.telegram_id == user.id)).limit(1))
        row = result.scalar_one_or_none()
        if row is None:
            session.add(User(user_id=user.id, telegram_id=user.id, username=user.username, first_name=user.first_name, updated_at=now, last_seen=now))
        else:
            row.telegram_id = user.id
            row.username = user.username
            row.first_name = user.first_name
            row.updated_at = now
            row.last_seen = now
        await session.commit()


async def require_channel(message, bot):
    if await channel_access(bot, message.from_user.id):
        return True
    await message.answer(f"⚠️ Join {html.escape(settings.required_channel)} dulu sebelum menggunakan NOBAR.")
    return False


async def track_group(message, bot):
    if message.chat.type not in {"group", "supergroup"} or not message.from_user:
        return
    try:
        me = await bot.get_me()
        bm = await bot.get_chat_member(message.chat.id, me.id)
        async with Session() as session:
            group = await session.get(Group, message.chat.id)
            if group is None:
                group = Group(chat_id=message.chat.id, title=message.chat.title or str(message.chat.id), chat_type=message.chat.type, bot_is_admin=bm.status in {"administrator", "creator"})
                session.add(group)
            else:
                group.title = message.chat.title or str(message.chat.id)
                group.bot_is_admin = bm.status in {"administrator", "creator"}
                group.updated_at = datetime.now(timezone.utc)
            gm = await session.scalar(select(GroupMember.id).where(GroupMember.chat_id == message.chat.id, GroupMember.user_id == message.from_user.id))
            if gm is None:
                session.add(GroupMember(chat_id=message.chat.id, user_id=message.from_user.id))
            await session.commit()
    except Exception:
        pass


@router.message(CommandStart())
async def start(message: Message, bot: Bot):
    await ensure_user(message.from_user)
    if not await require_channel(message, bot): return
    await track_group(message, bot)
    await message.answer("🎬 <b>NOBAR</b>\n\nWatch party Telegram untuk GC. Pilih fitur:", reply_markup=main_menu(message.from_user.id == settings.owner_id))


@router.message(Command("menu"))
async def menu(message: Message, bot: Bot):
    if not await require_channel(message, bot): return
    await message.answer("🎬 <b>NOBAR</b>\n\nPilih fitur:", reply_markup=main_menu(message.from_user.id == settings.owner_id))


@router.message(Command("help"))
async def help_command(message: Message, bot: Bot):
    if not await require_channel(message, bot): return
    await message.answer("🎬 <b>NOBAR — Commands</b>\n\n/start /menu /nobar /join KODE /rooms /room KODE /play KODE /upload /invite /feedback")


@router.message(Command("nobar"))
async def create_room(message: Message, bot: Bot):
    if not await require_channel(message, bot): return
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer("❌ /nobar hanya bisa dipakai di grup."); return
    await ensure_user(message.from_user); await track_group(message, bot)
    title = message.text.partition(" ")[2].strip() or "NOBAR"
    async with Session() as session:
        code = make_code()
        while await session.scalar(select(Room.id).where(Room.code == code)): code = make_code()
        room = Room(code=code, title=title, group_chat_id=message.chat.id, host_user_id=message.from_user.id)
        session.add(room); await session.flush(); session.add(Member(room_id=room.id, user_id=message.from_user.id)); await session.commit()
    await message.answer(f"🍿 <b>{html.escape(title)}</b>\n\n🔑 Room: <code>{code}</code>\n👑 Host: @{html.escape(message.from_user.username or str(message.from_user.id))}", reply_markup=room_menu(room))


async def get_room(code):
    async with Session() as session:
        return await session.scalar(select(Room).where(Room.code == code.upper(), Room.is_active.is_(True)))


@router.message(Command("join"))
async def join_room(message: Message, bot: Bot):
    if not await require_channel(message, bot): return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2: await message.answer("Gunakan: /join KODE"); return
    await ensure_user(message.from_user)
    async with Session() as session:
        room = await session.scalar(select(Room).where(Room.code == parts[1].upper(), Room.is_active.is_(True)))
        if not room: await message.answer("❌ Room tidak ditemukan atau sudah ditutup."); return
        exists = await session.scalar(select(Member.id).where(Member.room_id == room.id, Member.user_id == message.from_user.id))
        if not exists: session.add(Member(room_id=room.id, user_id=message.from_user.id)); await session.commit()
    await message.answer(f"✅ Kamu masuk room <code>{room.code}</code>.", reply_markup=room_menu(room))


@router.message(Command("rooms"))
async def list_rooms(message: Message, bot: Bot):
    if not await require_channel(message, bot): return
    async with Session() as session:
        rooms = (await session.scalars(select(Room).where(Room.is_active.is_(True)).order_by(Room.created_at.desc()).limit(20))).all()
    if not rooms: await message.answer("🔎 Tidak ada NOBAR aktif."); return
    await message.answer("🔎 <b>NOBAR aktif</b>\n\n" + "\n".join(f"• <code>{r.code}</code> — {html.escape(r.title)}" for r in rooms))


@router.message(Command("room"))
async def room_info(message: Message, bot: Bot):
    if not await require_channel(message, bot): return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2: await message.answer("Gunakan: /room KODE"); return
    room = await get_room(parts[1])
    if not room: await message.answer("❌ Room tidak ditemukan."); return
    async with Session() as session:
        count = await session.scalar(select(func.count(Member.id)).where(Member.room_id == room.id))
        film = await session.scalar(select(Film).where(Film.room_id == room.id, Film.status == "ready").order_by(Film.created_at.desc()))
    await message.answer(f"🎬 <b>{html.escape(room.title)}</b>\n\n🔑 <code>{room.code}</code>\n👥 Member: {count}\n🎞️ Film: {html.escape(film.title) if film else 'Belum dipilih'}\n🟢 {'Aktif' if room.is_active else 'Selesai'}", reply_markup=room_menu(room))


@router.message(Command("play"))
async def play_room(message: Message, bot: Bot):
    if not await require_channel(message, bot): return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2: await message.answer("Gunakan: /play KODE"); return
    room = await get_room(parts[1])
    if not room: await message.answer("❌ Room tidak ditemukan."); return
    await message.answer("▶️ Buka Mini App NOBAR:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 Mulai Nonton", web_app=WebAppInfo(url=f"{settings.webapp_url}/miniapp?room={room.code}"))]]))


@router.message(Command("upload"))
async def upload_help(message: Message, bot: Bot):
    if not await require_channel(message, bot): return
    await message.answer("📤 Kirim film/video langsung ke chat bot ini. Untuk mengaitkan ke room, buka room lalu tekan 📤 Upload Film.")


@router.message(lambda m: m.video is not None or m.document is not None)
async def receive_film(message: Message, bot: Bot):
    if not await require_channel(message, bot): return
    media = message.video or message.document
    mime = (media.mime_type or "video/mp4")
    if not mime.startswith("video/") and not (message.document and (media.file_name or "").lower().endswith((".mp4", ".mkv", ".webm", ".mov", ".avi"))):
        return
    size = media.file_size or 0
    if size > settings.max_film_bytes:
        await message.answer(f"❌ Film terlalu besar. Batas konfigurasi NOBAR: {settings.max_film_bytes // (1024**3)} GB."); return
    await ensure_user(message.from_user)
    status = await message.answer("⏳ Film diterima. Menghitung SHA-256 dan menyiapkan B2...")
    path = None
    try:
        suffix = os.path.splitext(getattr(media, "file_name", None) or "film.mp4")[1] or ".mp4"
        fd, path = tempfile.mkstemp(prefix="nobar-", suffix=suffix); os.close(fd)
        await bot.download(media, destination=path)
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(8 * 1024 * 1024)
                if not chunk: break
                digest.update(chunk)
        sha = digest.hexdigest()
        title = getattr(media, "file_name", None) or f"Film {sha[:8]}"
        async with Session() as session:
            existing = await session.scalar(select(Film).where(Film.sha256 == sha, Film.status == "ready").order_by(Film.created_at.desc()))
            if existing:
                await status.edit_text(f"♻️ <b>Film sudah tersimpan</b>\n\n🎞️ {html.escape(existing.title)}\n🔐 SHA-256: <code>{sha}</code>\n\nTidak perlu upload ulang.")
                return
            key = f"films/{sha}/{secrets.token_hex(8)}-{title.replace('/', '_')[:150]}"
            await status.edit_text("☁️ SHA-256 cocok unik. Mengupload film ke Backblaze B2...")
            upload_file(path, key, mime, sha)
            film = Film(room_id=0, owner_user_id=message.from_user.id, title=title, object_key=key, sha256=sha, size_bytes=size or os.path.getsize(path), mime_type=mime, status="ready")
            session.add(film); await session.commit()
        await status.edit_text(f"✅ <b>Film tersimpan</b>\n\n🎞️ {html.escape(title)}\n📦 {size // (1024**2) if size else os.path.getsize(path)//(1024**2)} MB\n🔐 SHA-256: <code>{sha}</code>\n☁️ Backblaze B2\n\nFilm siap dipilih untuk NOBAR.")
    except Exception as exc:
        await status.edit_text(f"❌ Upload film gagal: <code>{html.escape(str(exc)[:500])}</code>")
    finally:
        if path:
            try: os.remove(path)
            except OSError: pass


@router.callback_query(lambda c: c.data and c.data.startswith("menu:"))
async def menu_callbacks(c: CallbackQuery, bot: Bot):
    await c.answer()
    action = c.data.split(":", 1)[1]
    if action == "back": await c.message.edit_text("🎬 <b>NOBAR</b>\n\nPilih fitur:", reply_markup=main_menu(c.from_user.id == settings.owner_id)); return
    texts = {
        "create": "🎬 Buat Room\n\nGunakan /nobar di grup untuk membuat room.",
        "join": "🔗 Join Room\n\nGunakan /join KODE atau tombol GABUNG NOBAR.",
        "rooms": "🔎 Gunakan /rooms untuk melihat NOBAR aktif.",
        "info": "📋 Gunakan /room KODE untuk detail room.",
        "upload": "📤 Kirim film/video langsung ke bot. SHA-256 akan dicek sebelum upload ke B2.",
        "myrooms": "👤 Gunakan /rooms lalu buka room yang kamu ikuti.",
        "help": "❓ /nobar /join KODE /rooms /room KODE /play KODE /upload /invite /feedback",
        "feedback": "💬 Gunakan /feedback isi masukan",
    }
    await c.message.answer(texts.get(action, "Pilih menu."))


@router.callback_query(lambda c: c.data and c.data.startswith("roomupload:"))
async def room_upload_prompt(c: CallbackQuery, bot: Bot):
    await c.answer()
    rid = int(c.data.split(":", 1)[1])
    async with Session() as session: room = await session.get(Room, rid)
    if not room or not room.is_active: await c.message.answer("❌ Room tidak aktif."); return
    if room.host_user_id != c.from_user.id: await c.message.answer("❌ Hanya host yang menentukan film room."); return
    await c.message.answer(f"📤 Kirim film/video ke bot sekarang. Setelah tersimpan, gunakan /room {room.code} untuk memilihnya.")


@router.callback_query(lambda c: c.data and c.data.startswith("share:"))
async def share_room(c: CallbackQuery, bot: Bot):
    await c.answer()
    rid = int(c.data.split(":", 1)[1])
    async with Session() as session:
        room = await session.get(Room, rid)
        rows = (await session.execute(select(Group.chat_id, Group.title).join(GroupMember, GroupMember.chat_id == Group.chat_id).where(GroupMember.user_id == c.from_user.id, Group.bot_is_admin.is_(True)).distinct())).all()
    if not room or not room.is_active: await c.message.answer("❌ Room tidak aktif."); return
    valid = []
    me = await bot.get_me()
    for gid, title in rows:
        try:
            bm = await bot.get_chat_member(gid, me.id); um = await bot.get_chat_member(gid, c.from_user.id)
            if bm.status in {"administrator", "creator"} and um.status in {"member", "administrator", "creator"}: valid.append((gid, title))
        except Exception: pass
    if not valid: await c.message.answer("⚠️ Tidak ada grup yang bisa dipilih."); return
    buttons = [[InlineKeyboardButton(text=f"👥 {title[:45]}", callback_data=f"shareto:{rid}:{gid}")] for gid, title in valid]
    buttons.append([InlineKeyboardButton(text="❌ Batal", callback_data="sharecancel")])
    await c.message.answer("🔗 <b>SHARE NOBAR</b>\n\nPilih grup tujuan:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(lambda c: c.data and c.data.startswith("shareto:"))
async def share_to_group(c: CallbackQuery, bot: Bot):
    await c.answer()
    _, rid, gid = c.data.split(":")
    async with Session() as session: room = await session.get(Room, int(rid))
    if not room or not room.is_active: await c.message.answer("❌ Room tidak aktif."); return
    try:
        me = await bot.get_me(); bm = await bot.get_chat_member(int(gid), me.id); um = await bot.get_chat_member(int(gid), c.from_user.id)
        if bm.status not in {"administrator", "creator"} or um.status not in {"member", "administrator", "creator"}: raise RuntimeError("access")
        url = f"https://t.me/{me.username}?start=room_{room.code}"
        await bot.send_message(int(gid), f"🎬 <b>NOBAR</b>\n\n🎞️ {html.escape(room.title)}\n🔑 Room: <code>{room.code}</code>\n\nYuk ikut nonton bareng!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 GABUNG NOBAR", url=url)]]))
        await c.message.answer("✅ Undangan sudah dikirim ke grup.")
    except Exception: await c.message.answer("❌ Bot tidak dapat mengirim ke grup tersebut.")


@router.callback_query(lambda c: c.data == "sharecancel")
async def share_cancel(c: CallbackQuery):
    await c.answer("Dibatalkan"); await c.message.delete()


@router.message(Command("invite"))
async def invite(message: Message, bot: Bot):
    if not await require_channel(message, bot): return
    await message.answer("🔗 Buka room dan tekan <b>Share ke Grup</b>.")


@router.message(Command("feedback"))
async def feedback(message: Message, bot: Bot):
    if not await require_channel(message, bot): return
    text = message.text.partition(" ")[2].strip()
    if not text: await message.answer("Gunakan: /feedback isi masukan"); return
    await ensure_user(message.from_user)
    async with Session() as session:
        session.add(Feedback(user_id=message.from_user.id, username=message.from_user.username, kind="feedback", message=text)); await session.commit()
    await message.answer("✅ Feedback diterima.")


@router.message(Command("admin"))
async def admin_command(message: Message, bot: Bot):
    if message.from_user.id != settings.owner_id: await message.answer("❌ Tidak memiliki akses."); return
    await message.answer("🔐 <b>PANEL ADMIN</b>", reply_markup=admin_menu())


@router.callback_query(lambda c: c.data and c.data.startswith("admin:"))
async def admin_callbacks(c: CallbackQuery, bot: Bot):
    if c.from_user.id != settings.owner_id: await c.answer("Akses ditolak", show_alert=True); return
    await c.answer()
    action = c.data.split(":", 1)[1]
    if action == "open": await c.message.answer("🔐 <b>PANEL ADMIN</b>", reply_markup=admin_menu()); return
    async with Session() as session:
        if action == "stats":
            users = await session.scalar(select(func.count(User.user_id))); groups = await session.scalar(select(func.count(Group.chat_id))); rooms = await session.scalar(select(func.count(Room.id)).where(Room.is_active.is_(True))); films = await session.scalar(select(func.count(Film.id)).where(Film.status == "ready"))
            await c.message.answer(f"📊 <b>Statistik</b>\n👥 Users: {users}\n🏘️ Groups: {groups}\n🏠 Active rooms: {rooms}\n🎞️ Films: {films}")
        elif action == "users":
            users = await session.scalar(select(func.count(User.user_id))); await c.message.answer(f"👥 Total pengguna: <b>{users}</b>")
        elif action == "rooms":
            rooms = await session.scalar(select(func.count(Room.id)).where(Room.is_active.is_(True))); await c.message.answer(f"🏠 Room aktif: <b>{rooms}</b>")
        elif action == "films":
            films = await session.scalar(select(func.count(Film.id)).where(Film.status == "ready")); await c.message.answer(f"🎞️ Film siap: <b>{films}</b>")
        elif action == "feedback":
            items = (await session.scalars(select(Feedback).order_by(Feedback.created_at.desc()).limit(10))).all()
            await c.message.answer("📝 <b>Feedback terbaru</b>\n\n" + ("\n".join(f"• {html.escape(x.message[:160])}" for x in items) if items else "Belum ada feedback."))
        elif action == "btext":
            _pending_admin[c.from_user.id] = "text"; await c.message.answer("📝 Kirim pesan broadcast berikutnya. /cancel untuk batal.")
        elif action == "bphoto":
            _pending_admin[c.from_user.id] = "photo"; await c.message.answer("🖼️ Kirim foto + caption broadcast berikutnya. /cancel untuk batal.")


_pending_admin = {}


@router.message(Command("cancel"))
async def cancel(message: Message, bot: Bot):
    if message.from_user.id == settings.owner_id: _pending_admin.pop(message.from_user.id, None); await message.answer("❌ Dibatalkan.")


@router.message(lambda m: m.from_user and m.from_user.id == settings.owner_id and m.from_user.id in _pending_admin and not (m.text or "").startswith("/"))
async def admin_broadcast_input(message: Message, bot: Bot):
    mode = _pending_admin.pop(message.from_user.id, None)
    if not mode: return
    async with Session() as session: ids = list((await session.scalars(select(User.user_id).where(User.is_banned.is_(False)))).all())
    sent = 0
    for uid in ids:
        try:
            if mode == "photo" and message.photo:
                await bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption or "")
            elif mode == "text" and message.text:
                await bot.send_message(uid, message.text)
            else: continue
            sent += 1
        except Exception: pass
    await message.answer(f"📣 Broadcast selesai. Terkirim: {sent}/{len(ids)}")


@router.message()
async def group_tracker_fallback(message: Message, bot: Bot):
    await track_group(message, bot)
