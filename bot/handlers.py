import html
import secrets
import string
from datetime import datetime, timezone

from aiogram import Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from sqlalchemy import func, select

from config import settings
from db import Feedback, Member, Room, Session, User

router = Router()


def make_code() -> str:
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))


def room_button(room: Room, upload: bool = False) -> InlineKeyboardMarkup:
    url = f"{settings.webapp_url}/miniapp?room={room.code}&upload={1 if upload else 0}"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 Buka NOBAR", web_app=WebAppInfo(url=url))]])


def dashboard_button(group_id: int) -> InlineKeyboardMarkup:
    url = f"{settings.webapp_url}/miniapp?group_id={group_id}"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Dashboard GC", web_app=WebAppInfo(url=url))]])


async def channel_access(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(settings.required_channel, user_id)
        return member.status in {"member", "administrator", "creator"}
    except Exception:
        return False


async def ensure_user(user) -> None:
    async with Session() as session:
        row = await session.get(User, user.id)
        now = datetime.now(timezone.utc)
        if not row:
            session.add(
                User(
                    user_id=user.id,
                    telegram_id=user.id,
                    username=user.username,
                    first_name=user.first_name,
                    updated_at=now,
                    last_seen=now,
                )
            )
        else:
            # user_id is the immutable application identity. telegram_id is
            # retained only as a backwards-compatible DB alias.
            row.telegram_id = user.id
            row.username = user.username
            row.first_name = user.first_name
            row.updated_at = now
            row.last_seen = now
        await session.commit()


async def require_channel(message: Message, bot: Bot) -> bool:
    if await channel_access(bot, message.from_user.id):
        return True
    await message.answer(f"⚠️ Kamu harus join {html.escape(settings.required_channel)} dulu sebelum memakai NOBAR.")
    return False


@router.message(CommandStart())
async def start(message: Message, bot: Bot):
    await ensure_user(message.from_user)
    if not await require_channel(message, bot):
        return
    text = (
        "🎬 <b>NOBAR</b>\n\n"
        "Watch party Telegram untuk GC. Film disimpan permanen di Backblaze B2, "
        "bukan di Railway.\n\n"
        "• /nobar — buat room\n"
        "• /join KODE — masuk room\n"
        "• /rooms — room aktif\n"
        "• /room KODE — status\n"
        "• /play KODE — buka player\n"
        "• /upload KODE — upload film (host)\n"
        "• /feedback — kirim masukan"
    )
    await message.answer(text, reply_markup=dashboard_button(message.chat.id) if message.chat.type in {"group", "supergroup"} else None)


@router.message(Command("help"))
async def help_command(message: Message, bot: Bot):
    if not await require_channel(message, bot):
        return
    await message.answer(
        "🎬 <b>NOBAR — Commands</b>\n\n"
        "/nobar [judul] — buat room di GC\n"
        "/join KODE — gabung room\n"
        "/rooms — lihat semua room aktif\n"
        "/room KODE — status\n"
        "/play KODE — buka player\n"
        "/upload KODE — uploader host\n"
        "/feedback teks — kirim feedback\n"
        "/broadcast — owner: reply pesan untuk broadcast"
    )


@router.message(Command("nobar"))
async def create_room(message: Message, bot: Bot):
    if message.chat.type not in {"group", "supergroup"}:
        return await message.answer("Gunakan /nobar di group Telegram.")
    if not await require_channel(message, bot):
        return
    await ensure_user(message.from_user)
    title = (message.text.partition(" ")[2].strip() or f"Nobar {message.from_user.first_name}")[:200]
    async with Session() as session:
        for _ in range(10):
            code = make_code()
            exists = await session.scalar(select(Room.id).where(Room.code == code))
            if not exists:
                break
        else:
            return await message.answer("❌ Gagal membuat kode room. Coba lagi.")
        room = Room(code=code, group_chat_id=message.chat.id, host_user_id=message.from_user.id, title=title)
        session.add(room)
        await session.flush()
        session.add(Member(room_id=room.id, user_id=message.from_user.id))
        await session.commit()
        await session.refresh(room)
    await message.answer(
        f"🍿 <b>Room NOBAR dibuat</b>\n\n🎬 {html.escape(title)}\n🔑 Kode: <code>{room.code}</code>\n\nHost bisa upload film dari tombol di bawah.",
        reply_markup=room_button(room, upload=True),
    )


@router.message(Command("join"))
async def join_room(message: Message, bot: Bot):
    if not await require_channel(message, bot):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        return await message.answer("Gunakan /join KODE")
    await ensure_user(message.from_user)
    async with Session() as session:
        room = await session.scalar(select(Room).where(Room.code == parts[1].strip().upper(), Room.is_active.is_(True)))
        if not room:
            return await message.answer("❌ Room tidak ditemukan atau sudah ditutup.")
        if message.chat.id != room.group_chat_id:
            return await message.answer("❌ Room ini berasal dari GC lain.")
        member = await session.scalar(select(Member.id).where(Member.room_id == room.id, Member.user_id == message.from_user.id))
        if not member:
            session.add(Member(room_id=room.id, user_id=message.from_user.id))
            await session.commit()
    await message.answer(f"✅ Kamu masuk ke <b>{html.escape(room.title)}</b>.", reply_markup=room_button(room))


@router.message(Command("rooms"))
async def list_rooms(message: Message, bot: Bot):
    if message.chat.type not in {"group", "supergroup"}:
        return await message.answer("Gunakan /rooms di group Telegram.")
    if not await require_channel(message, bot):
        return
    async with Session() as session:
        rooms = (await session.scalars(select(Room).where(Room.group_chat_id == message.chat.id, Room.is_active.is_(True)).order_by(Room.created_at.desc()).limit(20))).all()
    if not rooms:
        return await message.answer("📭 Belum ada room aktif di GC ini.")
    lines = ["🎬 <b>Room aktif</b>"]
    for room in rooms:
        lines.append(f"• <code>{room.code}</code> — {html.escape(room.title)}")
    await message.answer("\n".join(lines), reply_markup=dashboard_button(message.chat.id))


async def open_room(message: Message, bot: Bot, command: str, upload: bool = False):
    if not await require_channel(message, bot):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        return await message.answer(f"Gunakan /{command} KODE")
    async with Session() as session:
        room = await session.scalar(select(Room).where(Room.code == parts[1].strip().upper(), Room.is_active.is_(True)))
    if not room:
        return await message.answer("❌ Room tidak ditemukan.")
    if message.chat.id != room.group_chat_id:
        return await message.answer("❌ Room ini bukan milik GC ini.")
    if upload and message.from_user.id != room.host_user_id:
        return await message.answer("❌ Hanya host room yang boleh upload film.")
    await message.answer("🎬 Buka Mini App NOBAR:", reply_markup=room_button(room, upload))


@router.message(Command("play"))
async def play_room(message: Message, bot: Bot):
    await open_room(message, bot, "play")


@router.message(Command("upload"))
async def upload_room(message: Message, bot: Bot):
    await open_room(message, bot, "upload", True)


@router.message(Command("room"))
async def room_status(message: Message, bot: Bot):
    if not await require_channel(message, bot):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        return await message.answer("Gunakan /room KODE")
    async with Session() as session:
        room = await session.scalar(select(Room).where(Room.code == parts[1].strip().upper()))
        if not room:
            return await message.answer("❌ Room tidak ditemukan.")
        if room.group_chat_id != message.chat.id:
            return await message.answer("❌ Room ini bukan milik GC ini.")
        count = await session.scalar(select(func.count()).select_from(Member).where(Member.room_id == room.id))
    state = "▶️ Playing" if room.is_playing else "⏸️ Paused"
    await message.answer(f"🎬 <b>{html.escape(room.title)}</b>\n🔑 <code>{room.code}</code>\n👥 {count} peserta\n{state}\n⏱️ {int(room.position)} detik")


@router.message(Command("feedback"))
async def feedback(message: Message, bot: Bot):
    if not await require_channel(message, bot):
        return
    text = message.text.partition(" ")[2].strip()
    if not text:
        return await message.answer("Gunakan /feedback lalu tulis masukan/bug kamu.")
    async with Session() as session:
        session.add(Feedback(user_id=message.from_user.id, username=message.from_user.username, kind="feedback", message=text[:4000]))
        await session.commit()
    await message.answer("✅ Feedback tersimpan. Makasih sudah bantu ngembangin NOBAR!")
    try:
        uname = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
        await bot.send_message(settings.owner_id, f"📝 <b>Feedback NOBAR</b>\n👤 {html.escape(uname)}\n🆔 <code>{message.from_user.id}</code>\n\n{html.escape(text[:3500])}")
    except Exception:
        pass


@router.message(Command("broadcast"))
async def broadcast(message: Message, bot: Bot):
    if message.from_user.id != settings.owner_id:
        return await message.answer("❌ Owner only.")
    if not message.reply_to_message:
        return await message.answer("Reply pesan yang mau dibroadcast lalu kirim /broadcast")
    async with Session() as session:
        ids = [x[0] for x in (await session.execute(select(User.user_id))).all()]
    sent = 0
    failed = 0
    for uid in ids:
        try:
            await bot.copy_message(uid, message.chat.id, message.reply_to_message.message_id)
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"📢 Broadcast selesai.\n✅ Terkirim: {sent}\n⚠️ Gagal: {failed}")
