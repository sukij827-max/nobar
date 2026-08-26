import html
import secrets
import string
from datetime import datetime, timezone

from aiogram import Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from sqlalchemy import func, or_, select

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
        now = datetime.now(timezone.utc)

        # The production database contains legacy rows where the Telegram ID
        # is stored in telegram_id while user_id was an old numeric PK. Never
        # INSERT a second row just because the immutable Telegram ID is not
        # equal to that legacy PK.
        result = await session.execute(
            select(User)
            .where(or_(User.user_id == user.id, User.telegram_id == user.id))
            .limit(1)
        )
        row = result.scalar_one_or_none()

        if row is None:
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
        "/room KODE — detail room\n"
        "/play KODE — buka player\n"
        "/upload KODE — upload film\n"
        "/feedback — kirim feedback"
    )


@router.message(Command("nobar"))
async def create_room(message: Message, bot: Bot):
    if not await require_channel(message, bot):
        return
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer("❌ /nobar hanya bisa dipakai di grup.")
        return
    await ensure_user(message.from_user)
    title = message.text.partition(" ")[2].strip() or "NOBAR"
    async with Session() as session:
        code = make_code()
        while (await session.scalar(select(Room.id).where(Room.code == code))) is not None:
            code = make_code()
        room = Room(code=code, title=title, group_id=message.chat.id, host_id=message.from_user.id)
        session.add(room)
        session.add(Member(room=room, user_id=message.from_user.id))
        await session.commit()
    await message.answer(
        f"🍿 <b>{html.escape(title)}</b>\n\nRoom: <code>{code}</code>\nHost: @{html.escape(message.from_user.username or str(message.from_user.id))}",
        reply_markup=room_button(room, upload=True),
    )


@router.message(Command("join"))
async def join_room(message: Message, bot: Bot):
    if not await require_channel(message, bot):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Gunakan: /join KODE")
        return
    code = parts[1].strip().upper()
    await ensure_user(message.from_user)
    async with Session() as session:
        room = await session.scalar(select(Room).where(Room.code == code, Room.is_active.is_(True)))
        if not room:
            await message.answer("❌ Room tidak ditemukan atau sudah ditutup.")
            return
        exists = await session.scalar(select(Member.id).where(Member.room_id == room.id, Member.user_id == message.from_user.id))
        if not exists:
            session.add(Member(room_id=room.id, user_id=message.from_user.id))
            await session.commit()
    await message.answer(f"✅ Kamu masuk room <code>{code}</code>.", reply_markup=room_button(room))


@router.message(Command("rooms"))
async def list_rooms(message: Message, bot: Bot):
    if not await require_channel(message, bot):
        return
    async with Session() as session:
        rooms = (await session.scalars(select(Room).where(Room.is_active.is_(True)).order_by(Room.created_at.desc()).limit(20))).all()
    if not rooms:
        await message.answer("Belum ada room aktif.")
        return
    lines = ["🎬 <b>Room aktif</b>"]
    for room in rooms:
        lines.append(f"• <code>{room.code}</code> — {html.escape(room.title)}")
    await message.answer("\n".join(lines))


@router.message(Command("room"))
async def room_info(message: Message, bot: Bot):
    if not await require_channel(message, bot):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Gunakan: /room KODE")
        return
    async with Session() as session:
        room = await session.scalar(select(Room).where(Room.code == parts[1].strip().upper()))
        if not room:
            await message.answer("❌ Room tidak ditemukan.")
            return
        count = await session.scalar(select(func.count(Member.id)).where(Member.room_id == room.id))
    await message.answer(
        f"🎬 <b>{html.escape(room.title)}</b>\n\n"
        f"Kode: <code>{room.code}</code>\n"
        f"Member: {count}\n"
        f"Status: {'🟢 aktif' if room.is_active else '🔴 ditutup'}",
        reply_markup=room_button(room),
    )


@router.message(Command("play"))
async def play_room(message: Message, bot: Bot):
    if not await require_channel(message, bot):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Gunakan: /play KODE")
        return
    async with Session() as session:
        room = await session.scalar(select(Room).where(Room.code == parts[1].strip().upper(), Room.is_active.is_(True)))
    if not room:
        await message.answer("❌ Room tidak ditemukan.")
        return
    await message.answer("▶️ Buka player NOBAR:", reply_markup=room_button(room))


@router.message(Command("upload"))
async def upload_room(message: Message, bot: Bot):
    if not await require_channel(message, bot):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Gunakan: /upload KODE")
        return
    await ensure_user(message.from_user)
    async with Session() as session:
        room = await session.scalar(select(Room).where(Room.code == parts[1].strip().upper(), Room.is_active.is_(True)))
    if not room:
        await message.answer("❌ Room tidak ditemukan.")
        return
    if room.host_id != message.from_user.id:
        await message.answer("❌ Hanya host yang dapat mengupload film.")
        return
    await message.answer("📤 Buka NOBAR untuk upload film langsung ke B2.", reply_markup=room_button(room, upload=True))


@router.message(Command("feedback"))
async def feedback(message: Message, bot: Bot):
    if not await require_channel(message, bot):
        return
    text = message.text.partition(" ")[2].strip()
    if not text:
        await message.answer("Gunakan: /feedback isi masukan")
        return
    await ensure_user(message.from_user)
    async with Session() as session:
        session.add(Feedback(user_id=message.from_user.id, username=message.from_user.username, message=text))
        await session.commit()
    await message.answer("✅ Feedback sudah diterima. Terima kasih!")
