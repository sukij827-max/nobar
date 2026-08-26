import html

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from db import Film, Room, Session
from storage import delete_object

router = Router()


def library_keyboard(film_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑️ Hapus dari Penyimpanan", callback_data=f"filmdelete:{film_id}")],
    ])


@router.callback_query(lambda c: c.data == "menu:films")
async def saved_films(callback: CallbackQuery, bot):
    from bot import handlers as legacy
    if not await legacy.channel_access(bot, callback.from_user.id):
        await callback.answer("Join channel owner dulu.", show_alert=True)
        return
    await callback.answer()
    async with Session() as session:
        films = (await session.scalars(
            select(Film).where(
                Film.owner_user_id == callback.from_user.id,
                Film.status == "ready",
                Film.library_deleted.is_(False),
            ).order_by(Film.created_at.desc()).limit(50)
        )).all()
    if not films:
        await callback.message.edit_text(
            "🎞️ <b>FILM TERSIMPAN</b>\n\nBelum ada film tersimpan. Kirim film/video langsung ke bot."
        )
        return
    buttons = [[InlineKeyboardButton(text=f"🎬 {film.title[:45]}", callback_data=f"filmdeleteview:{film.id}")] for film in films]
    await callback.message.edit_text(
        "🎞️ <b>FILM TERSIMPAN</b>\n\nPilih film untuk melihat detail atau menghapusnya dari penyimpanan pribadi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("filmdeleteview:"))
async def film_delete_view(callback: CallbackQuery, bot):
    await callback.answer()
    fid = int(callback.data.split(":", 1)[1])
    async with Session() as session:
        film = await session.scalar(select(Film).where(
            Film.id == fid,
            Film.owner_user_id == callback.from_user.id,
            Film.status == "ready",
            Film.library_deleted.is_(False),
        ))
    if not film:
        await callback.message.edit_text("❌ Film tidak ditemukan di penyimpanan kamu.")
        return
    size = film.size_bytes / (1024 ** 3) if film.size_bytes >= 1024 ** 3 else film.size_bytes / (1024 ** 2)
    unit = "GB" if film.size_bytes >= 1024 ** 3 else "MB"
    await callback.message.edit_text(
        f"🎞️ <b>{html.escape(film.title)}</b>\n\n📦 Ukuran: {size:.2f} {unit}\n🔐 SHA-256: <code>{html.escape(film.sha256 or '-')}</code>\n\nFilm ini hanya akan dihapus dari <b>penyimpanan pribadi kamu</b>.\n\nJika sedang dipakai room lain, room tersebut <b>tetap berjalan</b> dan file B2 tidak akan dihapus selama masih digunakan.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑️ Ya, Hapus dari Penyimpanan", callback_data=f"filmdelete:{film.id}")],
            [InlineKeyboardButton(text="⬅️ Batal", callback_data="menu:films")],
        ]),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("filmdelete:"))
async def delete_saved_film(callback: CallbackQuery, bot):
    fid = int(callback.data.split(":", 1)[1])
    await callback.answer("Memproses penghapusan…")
    object_key = None
    delete_b2 = False
    async with Session() as session:
        film = await session.scalar(select(Film).where(
            Film.id == fid,
            Film.owner_user_id == callback.from_user.id,
            Film.status == "ready",
            Film.library_deleted.is_(False),
        ))
        if not film:
            await callback.message.edit_text("❌ Film tidak ditemukan atau sudah dihapus.")
            return
        active_rooms = (await session.scalars(select(Room).where(
            Room.film_id == film.id,
            Room.is_active.is_(True),
        ))).all()
        object_key = film.object_key
        film.library_deleted = True
        # Keep the Film row and its object_key as a historical/reference record.
        # Active rooms continue resolving the same Film row, so deleting from a
        # user's library cannot interrupt another person's active watch party.
        delete_b2 = len(active_rooms) == 0
        await session.commit()
    if delete_b2 and object_key:
        try:
            delete_object(object_key)
        except Exception:
            # The library deletion remains successful; an unavailable B2 delete
            # is intentionally not allowed to break the user's database action.
            pass
    if delete_b2:
        text = "✅ <b>Film dihapus dari penyimpanan.</b>\n\nKarena tidak sedang dipakai room aktif, file B2 juga sudah dibersihkan."
    else:
        text = "✅ <b>Film dihapus dari penyimpanan kamu.</b>\n\nℹ️ Film masih dipakai room aktif, jadi file B2 <b>tetap dipertahankan</b>. Room dan penonton lain tidak terganggu."
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎞️ Film Tersimpan", callback_data="menu:films")],
    ]))
