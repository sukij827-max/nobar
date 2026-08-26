import html
import secrets
import string
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from db import GroupMember, Member, Room, Session

router = Router()


def make_code() -> str:
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))


def room_keyboard(room: Room) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Share ke Grup", callback_data=f"directshare:{room.id}")],
        [InlineKeyboardButton(text="📤 Tambah Film", callback_data=f"roomupload:{room.id}")],
    ])


async def create_direct_room(user_id: int, title: str = "NOBAR") -> Room:
    async with Session() as session:
        code = make_code()
        while await session.scalar(select(Room.id).where(Room.code == code)) is not None:
            code = make_code()
        room = Room(
            code=code,
            title=title or "NOBAR",
            group_chat_id=None,
            host_user_id=user_id,
            is_active=True,
            is_playing=False,
            position=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(room)
        await session.flush()
        session.add(Member(room_id=room.id, user_id=user_id))
        await session.commit()
        return room


@router.message(Command("nobar"), F.chat.type == "private")
async def nobar_command(message: Message, bot: Bot):
    room = await create_direct_room(message.from_user.id, message.text.partition(" ")[2].strip() or "NOBAR")
    await message.answer(
        f"🎬 <b>Room NOBAR dibuat!</b>\n\n🔑 Kode: <code>{room.code}</code>\n👑 Host: @{html.escape(message.from_user.username or str(message.from_user.id))}\n\nSekarang tambahkan film, lalu share room ke grup.",
        reply_markup=room_keyboard(room),
    )


@router.callback_query(lambda c: c.data == "menu:create")
async def create_from_menu(callback: CallbackQuery, bot: Bot):
    await callback.answer("Membuat room...")
    room = await create_direct_room(callback.from_user.id)
    await callback.message.answer(
        f"🎬 <b>Room NOBAR dibuat!</b>\n\n🔑 Kode: <code>{room.code}</code>\n👑 Host: @{html.escape(callback.from_user.username or str(callback.from_user.id))}\n\nRoom siap digunakan. Tambahkan film lalu share ke grup.",
        reply_markup=room_keyboard(room),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("directshare:"))
async def direct_share(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    room_id = int(callback.data.split(":", 1)[1])
    async with Session() as session:
        room = await session.scalar(select(Room).where(Room.id == room_id, Room.is_active.is_(True)))
        if not room:
            await callback.message.answer("❌ Room sudah tidak aktif.")
            return
        is_member = await session.scalar(select(Member.id).where(Member.room_id == room.id, Member.user_id == callback.from_user.id))
        if not is_member:
            await callback.message.answer("❌ Kamu bukan member room ini.")
            return
        group_ids = [row[0] for row in (await session.execute(
            select(GroupMember.chat_id).where(GroupMember.user_id == callback.from_user.id).distinct()
        )).all()]

    valid = []
    me = await bot.get_me()
    for chat_id in group_ids:
        try:
            bot_member = await bot.get_chat_member(chat_id, me.id)
            if bot_member.status not in {"administrator", "creator"}:
                continue
            user_member = await bot.get_chat_member(chat_id, callback.from_user.id)
            if user_member.status not in {"member", "administrator", "creator"}:
                continue
            chat = await bot.get_chat(chat_id)
            valid.append((chat_id, chat.title or str(chat_id)))
        except Exception:
            continue

    if not valid:
        await callback.message.answer("⚠️ Tidak ada grup yang bisa dipilih. Pastikan kamu masih member grup dan bot NOBAR ada serta punya akses di grup tersebut.")
        return

    rows = [[InlineKeyboardButton(text=f"👥 {title[:45]}", callback_data=f"directshareto:{room.id}:{chat_id}")] for chat_id, title in valid]
    rows.append([InlineKeyboardButton(text="❌ Batal", callback_data="directsharecancel")])
    await callback.message.answer("🔗 <b>SHARE NOBAR</b>\n\nPilih grup tujuan:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(lambda c: c.data and c.data.startswith("directshareto:"))
async def direct_share_to_group(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    _, room_raw, chat_raw = callback.data.split(":", 2)
    room_id = int(room_raw)
    chat_id = int(chat_raw)
    async with Session() as session:
        room = await session.scalar(select(Room).where(Room.id == room_id, Room.is_active.is_(True)))
        is_member = await session.scalar(select(Member.id).where(Member.room_id == room_id, Member.user_id == callback.from_user.id))
    if not room or not is_member:
        await callback.message.answer("❌ Room tidak ditemukan atau kamu bukan member room.")
        return
    try:
        me = await bot.get_me()
        bot_member = await bot.get_chat_member(chat_id, me.id)
        user_member = await bot.get_chat_member(chat_id, callback.from_user.id)
        if bot_member.status not in {"administrator", "creator"} or user_member.status not in {"member", "administrator", "creator"}:
            raise RuntimeError("invalid access")
        invite_url = f"https://t.me/{me.username}?start=room_{room.code}"
        await bot.send_message(
            chat_id,
            f"🎬 <b>NOBAR</b>\n\n🎞️ {html.escape(room.title)}\n🔑 Room: <code>{room.code}</code>\n👑 Host: @{html.escape(callback.from_user.username or str(callback.from_user.id))}\n\nYuk ikut nonton bareng!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 GABUNG NOBAR", url=invite_url)]]),
        )
        await callback.message.answer("✅ Undangan NOBAR sudah dikirim ke grup.")
    except Exception:
        await callback.message.answer("❌ Bot tidak dapat mengirim ke grup tersebut. Pastikan bot masih ada dan memiliki akses yang diperlukan.")


@router.callback_query(lambda c: c.data == "directsharecancel")
async def direct_share_cancel(callback: CallbackQuery):
    await callback.answer("Dibatalkan")
    try:
        await callback.message.delete()
    except Exception:
        pass
