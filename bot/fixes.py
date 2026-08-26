import html
import re
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from sqlalchemy import func, select

from config import settings
from db import Film, Member, Room, Session, User
from bot import handlers as legacy
from bot import direct_room

router = Router()


def safe_room_menu(room):
    """Private chats may launch the Mini App directly. Group invites use a
    Telegram startapp deep link so the group button opens the Mini App instead
    of sending the viewer through /start."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Buka NOBAR", web_app=WebAppInfo(url=f"{settings.webapp_url}/miniapp?room={room.code}"))],
        [InlineKeyboardButton(text="🎞️ Pilih Film", callback_data=f"roomfilm:{room.id}"), InlineKeyboardButton(text="🔗 Share ke Grup", callback_data=f"share:{room.id}")],
        [InlineKeyboardButton(text="👥 Member", callback_data=f"roommembers:{room.id}"), InlineKeyboardButton(text="🚪 Keluar Room", callback_data=f"leave:{room.id}")],
    ])


def safe_direct_room_menu(room):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Buka NOBAR", web_app=WebAppInfo(url=f"{settings.webapp_url}/miniapp?room={room.code}"))],
        [InlineKeyboardButton(text="🎞️ Pilih Film", callback_data=f"roomfilm:{room.id}"), InlineKeyboardButton(text="🔗 Share ke Grup", callback_data=f"directshare:{room.id}")],
    ])


def patched_main_menu(admin=False):
    rows = [
        [InlineKeyboardButton(text="🎬 Buat Room", callback_data="menu:create"), InlineKeyboardButton(text="🔗 Join Room", callback_data="menu:join")],
        [InlineKeyboardButton(text="🔎 Cek NOBAR", callback_data="menu:rooms"), InlineKeyboardButton(text="📋 Info Room", callback_data="menu:info")],
        [InlineKeyboardButton(text="📤 Tambah Film", callback_data="menu:upload"), InlineKeyboardButton(text="🎞️ Film Tersimpan", callback_data="menu:films")],
        [InlineKeyboardButton(text="👤 Room Saya", callback_data="menu:myrooms"), InlineKeyboardButton(text="❓ Bantuan", callback_data="menu:help")],
        [InlineKeyboardButton(text="💬 Feedback", callback_data="menu:feedback")],
    ]
    if admin:
        rows.append([InlineKeyboardButton(text="🔐 Panel Admin", callback_data="admin:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


legacy.room_menu = safe_room_menu
legacy.main_menu = patched_main_menu
direct_room.room_keyboard = safe_direct_room_menu


_original_track_group = legacy.track_group


async def tracked_group(message, bot):
    if message.from_user:
        try:
            await legacy.ensure_user(message.from_user)
        except Exception:
            pass
    return await _original_track_group(message, bot)


legacy.track_group = tracked_group


_original_create_direct_room = direct_room.create_direct_room


async def tracked_create_direct_room(user_id: int, title: str = "NOBAR"):
    try:
        async with Session() as session:
            user = await session.get(User, user_id)
            if user is None:
                session.add(User(user_id=user_id, telegram_id=user_id, username=None, first_name="", updated_at=datetime.now(timezone.utc), last_seen=datetime.now(timezone.utc)))
                await session.commit()
    except Exception:
        pass
    return await _original_create_direct_room(user_id, title)


direct_room.create_direct_room = tracked_create_direct_room


@router.message(Command("nobar"))
async def create_room_direct(message: Message, bot):
    """NOBAR/Buat Room always creates a direct room, including when clicked/used from a group."""
    if not await legacy.require_channel(message, bot):
        return
    await legacy.ensure_user(message.from_user)
    title = message.text.partition(" ")[2].strip() or "NOBAR"
    room = await tracked_create_direct_room(message.from_user.id, title)
    await message.answer(
        f"🎬 <b>Room NOBAR dibuat!</b>\n\n🔑 Kode: <code>{room.code}</code>\n👑 Host: @{html.escape(message.from_user.username or str(message.from_user.id))}\n\nRoom ini tidak terikat ke grup. Pilih film tersimpan lalu bagikan ke grup.",
        reply_markup=safe_direct_room_menu(room),
    )


@router.callback_query(lambda c: c.data == "menu:create")
async def create_from_menu_direct(callback: CallbackQuery, bot):
    if not await legacy.channel_access(bot, callback.from_user.id):
        await callback.answer("Join channel owner dulu.", show_alert=True)
        return
    await callback.answer("Room dibuat")
    await legacy.ensure_user(callback.from_user)
    room = await tracked_create_direct_room(callback.from_user.id)
    await callback.message.answer(
        f"🎬 <b>Room NOBAR dibuat!</b>\n\n🔑 Kode: <code>{room.code}</code>\n👑 Host: @{html.escape(callback.from_user.username or str(callback.from_user.id))}\n\nRoom siap digunakan. Pilih film tersimpan lalu share ke grup.",
        reply_markup=safe_direct_room_menu(room),
    )


@router.callback_query(lambda c: c.data == "menu:films")
async def film_library(callback: CallbackQuery, bot):
    if not await legacy.channel_access(bot, callback.from_user.id):
        await callback.answer("Join channel owner dulu.", show_alert=True)
        return
    await callback.answer()
    async with Session() as session:
        films = (await session.scalars(select(Film).where(Film.status == "ready", Film.owner_user_id == callback.from_user.id).order_by(Film.created_at.desc()).limit(50))).all()
    if not films:
        await callback.message.answer("🎞️ <b>Film Tersimpan</b>\n\nBelum ada film tersimpan. Kirim video/film langsung ke bot untuk menyimpannya.")
        return
    lines = ["🎞️ <b>FILM TERSIMPAN</b>", "", "Pilih film untuk melihat detail atau memasukkannya ke room:"]
    buttons = []
    for film in films:
        lines.append(f"• {html.escape(film.title)}")
        buttons.append([InlineKeyboardButton(text=f"🎬 {film.title[:45]}", callback_data=f"filmview:{film.id}")])
    await callback.message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(lambda c: c.data and c.data.startswith("filmview:"))
async def film_view(callback: CallbackQuery, bot):
    await callback.answer()
    fid = int(callback.data.split(":", 1)[1])
    async with Session() as session:
        film = await session.get(Film, fid)
    if not film or film.status != "ready" or film.owner_user_id != callback.from_user.id:
        await callback.message.answer("❌ Film tidak ditemukan.")
        return
    size = film.size_bytes / (1024 ** 3) if film.size_bytes >= 1024 ** 3 else film.size_bytes / (1024 ** 2)
    unit = "GB" if film.size_bytes >= 1024 ** 3 else "MB"
    await callback.message.answer(
        f"🎞️ <b>{html.escape(film.title)}</b>\n\n📦 Ukuran: {size:.2f} {unit}\n🔐 SHA-256: <code>{html.escape(film.sha256 or '-')}</code>\n☁️ Backblaze B2\n\nFilm ini sudah tersimpan dan tidak perlu di-upload lagi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 Pilih untuk Room", callback_data=f"filmpick:{film.id}")]]),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("roomfilm:"))
async def room_film_picker(callback: CallbackQuery, bot):
    await callback.answer()
    rid = int(callback.data.split(":", 1)[1])
    async with Session() as session:
        room = await session.get(Room, rid)
        films = (await session.scalars(select(Film).where(Film.status == "ready", Film.owner_user_id == callback.from_user.id).order_by(Film.created_at.desc()).limit(50))).all()
    if not room or not room.is_active:
        await callback.message.answer("❌ Room tidak aktif.")
        return
    if room.host_user_id != callback.from_user.id:
        await callback.message.answer("❌ Hanya host yang dapat memilih film.")
        return
    if not films:
        await callback.message.answer("🎞️ Belum ada film tersimpan. Kirim film langsung ke bot terlebih dahulu.")
        return
    buttons = [[InlineKeyboardButton(text=f"🎬 {film.title[:45]}", callback_data=f"filmpickroom:{rid}:{film.id}")] for film in films]
    await callback.message.answer("🎞️ <b>PILIH FILM UNTUK ROOM</b>\n\nFilm diambil dari koleksi tersimpan. Tidak ada upload ulang.", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(lambda c: c.data and c.data.startswith("filmpickroom:"))
async def pick_film_for_room(callback: CallbackQuery, bot):
    await callback.answer("Film dipilih")
    _, rid, fid = callback.data.split(":")
    rid, fid = int(rid), int(fid)
    async with Session() as session:
        room = await session.get(Room, rid)
        film = await session.get(Film, fid)
        if not room or not room.is_active:
            await callback.message.answer("❌ Room tidak aktif.")
            return
        if room.host_user_id != callback.from_user.id:
            await callback.message.answer("❌ Hanya host yang dapat memilih film.")
            return
        if not film or film.status != "ready" or film.owner_user_id != callback.from_user.id:
            await callback.message.answer("❌ Film tidak tersedia.")
            return
        room.film_id = film.id
        room.position = 0
        room.is_playing = False
        room.updated_at = datetime.now(timezone.utc)
        await session.commit()
    await callback.message.answer(f"✅ <b>Film dipasang ke room</b>\n\n🎞️ {html.escape(film.title)}\n\nTidak ada upload ulang. Semua peserta akan memakai film yang sama dari penyimpanan.", reply_markup=safe_direct_room_menu(room) if room.group_chat_id is None else safe_room_menu(room))


@router.callback_query(lambda c: c.data and c.data.startswith("filmpick:"))
async def pick_film_prompt(callback: CallbackQuery, bot):
    await callback.answer()
    fid = int(callback.data.split(":", 1)[1])
    async with Session() as session:
        film = await session.get(Film, fid)
        rooms = (await session.scalars(select(Room).where(Room.host_user_id == callback.from_user.id, Room.is_active.is_(True)).order_by(Room.created_at.desc()).limit(20))).all()
    if not film or film.owner_user_id != callback.from_user.id:
        await callback.message.answer("❌ Film tidak ditemukan.")
        return
    if not rooms:
        await callback.message.answer("🎬 Belum ada room aktif. Buat room dulu.")
        return
    buttons = [[InlineKeyboardButton(text=f"🍿 {r.title[:42]} · {r.code}", callback_data=f"filmpickroom:{r.id}:{film.id}")] for r in rooms]
    await callback.message.answer("Pilih room tujuan untuk film ini:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(lambda c: c.data and c.data.startswith("openroom:"))
async def open_room(callback: CallbackQuery, bot):
    room_id = int(callback.data.split(":", 1)[1])
    async with Session() as session:
        room = await session.scalar(select(Room).where(Room.id == room_id, Room.is_active.is_(True)))
        if not room:
            await callback.answer("Room sudah tidak aktif.", show_alert=True)
            return
        exists = await session.scalar(select(Member.id).where(Member.room_id == room.id, Member.user_id == callback.from_user.id))
        if not exists:
            session.add(Member(room_id=room.id, user_id=callback.from_user.id))
            await session.commit()

    if callback.message.chat.type == "private":
        await callback.answer("Membuka NOBAR...")
        await callback.message.answer(
            f"🎬 <b>{html.escape(room.title)}</b>\n\n🔑 Room: <code>{room.code}</code>\n\nSiap nonton bareng.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎬 Mulai Nonton", web_app=WebAppInfo(url=f"{settings.webapp_url}/miniapp?room={room.code}"))],
                [InlineKeyboardButton(text="🎞️ Pilih Film", callback_data=f"roomfilm:{room.id}"), InlineKeyboardButton(text="🔗 Share ke Grup", callback_data=f"directshare:{room.id}")],
            ]),
        )
        return

    me = await bot.get_me()
    if not me.username:
        await callback.answer("Bot belum memiliki username publik.", show_alert=True)
        return
    direct_link = f"https://t.me/{me.username}?startapp=room_{room.code}"
    await callback.answer(url=direct_link)


@router.message(lambda m: bool(m.text) and re.match(r"^/start(?:@[^\s]+)?\s+room_[A-Za-z0-9_-]+$", m.text.strip(), re.I))
async def join_from_deep_link(message: Message, bot):
    if not await legacy.require_channel(message, bot):
        return
    payload = message.text.strip().split(maxsplit=1)[1]
    code = payload[5:].upper()
    await legacy.ensure_user(message.from_user)
    async with Session() as session:
        room = await session.scalar(select(Room).where(Room.code == code, Room.is_active.is_(True)))
        if not room:
            await message.answer("❌ Room tidak ditemukan atau sudah ditutup.")
            return
        exists = await session.scalar(select(Member.id).where(Member.room_id == room.id, Member.user_id == message.from_user.id))
        if not exists:
            session.add(Member(room_id=room.id, user_id=message.from_user.id))
            await session.commit()
    await message.answer(
        f"✅ <b>Berhasil masuk NOBAR</b>\n\n🎞️ {html.escape(room.title)}\n🔑 Room: <code>{room.code}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎬 Mulai Nonton", web_app=WebAppInfo(url=f"{settings.webapp_url}/miniapp?room={room.code}"))],
            [InlineKeyboardButton(text="🎞️ Pilih Film", callback_data=f"roomfilm:{room.id}")],
        ]),
    )


@router.callback_query(lambda c: c.data and re.fullmatch(r"admin:users(?::\d+)?", c.data))
async def admin_users_full(callback: CallbackQuery, bot):
    if callback.from_user.id != settings.owner_id:
        await callback.answer("Akses ditolak", show_alert=True)
        return
    await callback.answer()
    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) == 3 else 1
    page = max(1, page)
    per_page = 25
    async with Session() as session:
        total = await session.scalar(select(func.count(User.user_id))) or 0
        users = (await session.scalars(select(User).order_by(User.last_seen.desc()).offset((page - 1) * per_page).limit(per_page))).all()
    pages = max(1, (total + per_page - 1) // per_page)
    if page > pages:
        page = pages
    lines = [f"👥 <b>Daftar Pengguna</b> — {total} total\n<b>Halaman {page}/{pages}</b>\n"]
    for i, u in enumerate(users, start=(page - 1) * per_page + 1):
        uname = f"@{html.escape(u.username)}" if u.username else "(tanpa username)"
        name = html.escape(u.first_name or "-")
        flags = (" 💎" if u.is_premium else "") + (" 🚫" if u.is_banned else "")
        lines.append(f"{i}. {name} — {uname}\n   ID: <code>{u.user_id}</code>{flags}")
    rows = []
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️ Sebelumnya", callback_data=f"admin:users:{page-1}"))
    if page < pages:
        nav.append(InlineKeyboardButton(text="Berikutnya ➡️", callback_data=f"admin:users:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ Panel Admin", callback_data="admin:open")])
    await callback.message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
