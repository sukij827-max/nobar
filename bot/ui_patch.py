import asyncio
import html
import re
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from config import settings
from db import GroupMember, Member, Room, Session

router = Router()

HELP = '''📖 <b>CARA MENGGUNAKAN NOBAR</b>

<b>🎬 /nobar</b>
Membuat room NOBAR baru. Setelah room dibuat, pilih film dari Film Tersimpan lalu bagikan ke grup.

<b>🔗 /join KODE</b>
Masuk ke room menggunakan kode. Contoh: <code>/join ABC123</code>.

<b>📋 /room KODE</b>
Melihat informasi room tertentu, seperti host, film, dan status room.

<b>▶️ /play KODE</b>
Membuka room untuk mulai menonton.

<b>📤 /upload</b>
Panduan untuk mengirim film langsung ke bot. Film yang selesai di-upload otomatis masuk ke Film Tersimpan.

<b>🔎 /rooms</b>
Melihat room NOBAR yang sedang aktif.

<b>🔗 /invite</b>
Mendapatkan cara membagikan room ke grup. Tombol GABUNG NOBAR di grup akan membuka Mini App langsung.

<b>💬 /feedback</b>
Mengirim saran, kritik, atau laporan bug kepada owner.

<b>🎞️ Film Tersimpan</b>
Film yang sudah pernah di-upload tidak perlu di-upload lagi. Pilih film tersebut untuk dipasang ke room baru.

<b>🍿 Saat di grup</b>
Bot hanya menampilkan undangan NOBAR yang diperlukan. Menu/command pengelolaan tidak diproses di grup agar chat tidak spam.

<b>🎬 GABUNG NOBAR</b>
Tekan tombol ini di grup → Telegram langsung membuka Mini App → otomatis masuk room → film siap ditonton.

<b>🧹 Tampilan bersih</b>
Pesan menu/pilihan sementara akan dihapus setelah selesai digunakan jika bot mempunyai izin menghapus pesan.'''


def delete_later(message, delay=0.3):
    async def _run():
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except Exception:
            pass
    return asyncio.create_task(_run())


@router.message(lambda m: m.chat.type != "private" and bool(m.text) and m.text.startswith("/"))
async def group_commands_private_only(message: Message):
    # Commands are intentionally private-only. Delete the command so groups
    # stay clean; no bot response is sent to the group.
    delete_later(message)


@router.callback_query(lambda c: c.message and c.message.chat.type != "private" and bool(c.data) and (c.data.startswith("menu:") or c.data.startswith("admin:")))
async def block_group_menus(callback: CallbackQuery):
    await callback.answer("Menu NOBAR hanya tersedia di chat pribadi.", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass


@router.callback_query(lambda c: c.message and c.message.chat.type != "private" and bool(c.data) and c.data.startswith(("roomfilm:", "roommembers:", "leave:", "roomupload:")))
async def block_group_room_controls(callback: CallbackQuery):
    await callback.answer("Pengaturan room dilakukan melalui bot pribadi.", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass


@router.callback_query(lambda c: c.message and c.message.chat.type == "private" and c.data == "menu:help")
async def private_help(callback: CallbackQuery):
    await callback.answer()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Kembali ke Menu", callback_data="menu:back")]])
    try:
        await callback.message.edit_text(HELP, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(HELP, reply_markup=keyboard)


@router.message(Command("help"))
async def private_help_command(message: Message):
    if message.chat.type != "private":
        return
    await message.answer(HELP, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Kembali ke Menu", callback_data="menu:back")]]))


@router.callback_query(lambda c: c.message and c.message.chat.type == "private" and c.data == "menu:back")
async def private_back(callback: CallbackQuery):
    await callback.answer()
    # Let the existing menu builder remain the source of truth; this only
    # restores it in-place when available.
    try:
        is_admin = callback.from_user.id == settings.owner_id
        from bot.fixes import patched_main_menu
        await callback.message.edit_text("🎬 <b>NOBAR</b>\n\nPilih fitur yang kamu butuhkan:", reply_markup=patched_main_menu(is_admin))
    except Exception:
        pass


async def _room_invite(bot, room_id: int, user_id: int, chat_id: int):
    async with Session() as session:
        room = await session.scalar(select(Room).where(Room.id == room_id, Room.is_active.is_(True)))
        member = await session.scalar(select(Member.id).where(Member.room_id == room_id, Member.user_id == user_id))
    if not room or not member:
        return None
    me = await bot.get_me()
    if not me.username:
        return None
    try:
        bm = await bot.get_chat_member(chat_id, me.id)
        um = await bot.get_chat_member(chat_id, user_id)
        if bm.status not in {"administrator", "creator"} or um.status not in {"member", "administrator", "creator"}:
            return None
    except Exception:
        return None
    return room, me.username


@router.callback_query(lambda c: c.data and c.data.startswith("directshareto:") and c.message and c.message.chat.type == "private")
async def direct_share_to_group_fixed(callback: CallbackQuery, bot):
    _, room_raw, chat_raw = callback.data.split(":", 2)
    room_id, chat_id = int(room_raw), int(chat_raw)
    result = await _room_invite(bot, room_id, callback.from_user.id, chat_id)
    if not result:
        await callback.answer("Akses room/grup tidak valid.", show_alert=True)
        return
    room, username = result
    # startapp is the important difference from the old ?start= link.
    # It opens the Telegram Mini App directly from a group message.
    invite_url = f"https://t.me/{username}?startapp=room_{room.code}"
    try:
        await bot.send_message(
            chat_id,
            f"🎬 <b>NOBAR</b>\n\n🎞️ {html.escape(room.title)}\n🔑 Room: <code>{room.code}</code>\n👑 Host: @{html.escape(callback.from_user.username or str(callback.from_user.id))}\n\nYuk ikut nonton bareng!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 GABUNG NOBAR", url=invite_url)]]),
        )
        await callback.answer("Undangan dikirim")
        try:
            await callback.message.delete()
        except Exception:
            pass
    except Exception:
        await callback.answer("Bot tidak dapat mengirim undangan ke grup.", show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("share:") and c.message and c.message.chat.type == "private")
async def share_fixed(callback: CallbackQuery, bot):
    room_id = int(callback.data.split(":", 1)[1])
    async with Session() as session:
        room = await session.scalar(select(Room).where(Room.id == room_id, Room.is_active.is_(True)))
        member = await session.scalar(select(Member.id).where(Member.room_id == room_id, Member.user_id == callback.from_user.id))
        group_ids = [x[0] for x in (await session.execute(select(GroupMember.chat_id).where(GroupMember.user_id == callback.from_user.id).distinct())).all()]
    if not room or not member:
        await callback.answer("Room tidak ditemukan.", show_alert=True); return
    valid = []
    me = await bot.get_me()
    for gid in group_ids:
        try:
            bm = await bot.get_chat_member(gid, me.id); um = await bot.get_chat_member(gid, callback.from_user.id)
            if bm.status in {"administrator", "creator"} and um.status in {"member", "administrator", "creator"}:
                chat = await bot.get_chat(gid); valid.append((gid, chat.title or str(gid)))
        except Exception:
            pass
    if not valid:
        await callback.answer("Tidak ada grup yang bisa dipilih.", show_alert=True); return
    rows = [[InlineKeyboardButton(text=f"👥 {title[:45]}", callback_data=f"directshareto:{room.id}:{gid}")] for gid,title in valid]
    rows.append([InlineKeyboardButton(text="❌ Batal", callback_data="ui_cancel")])
    await callback.message.edit_text("🔗 <b>SHARE NOBAR</b>\n\nPilih grup tujuan:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(lambda c: c.data == "ui_cancel")
async def ui_cancel(callback: CallbackQuery):
    await callback.answer("Dibatalkan")
    try: await callback.message.delete()
    except Exception: pass
