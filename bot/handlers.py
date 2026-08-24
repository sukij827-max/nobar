import asyncio
import html
import secrets
import string

import asyncpg
from aiogram import Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

router = Router()


def code():
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))


def kb(url):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text='🎬 Buka Nobar', web_app=WebAppInfo(url=url))]]
    )


async def access(m, bot, settings):
    try:
        member = await bot.get_chat_member(settings.required_channel, m.from_user.id)
        ok = member.status in {'member', 'administrator', 'creator'}
    except Exception:
        ok = False
    if not ok:
        await m.answer(f'⚠️ Join channel {html.escape(settings.required_channel)} dulu.')
        return False
    return True


async def create_room_with_retry(db, group_id, user_id, title, attempts=5):
    for _ in range(attempts):
        try:
            return await db.make_room(code(), group_id, user_id, title)
        except asyncpg.UniqueViolationError:
            continue
    raise RuntimeError('Gagal membuat kode room unik. Silakan coba lagi.')


@router.message(CommandStart())
async def start(m: Message, bot: Bot, settings, db):
    await db.user(m.from_user)
    if await access(m, bot, settings):
        await m.answer(
            '🎬 <b>Nobar</b>\nGunakan /nobar di grup untuk membuat room. '
            'Setelah room dibuat, host upload film sampai 5 GiB langsung dari Mini App.'
        )


@router.message(Command('help'))
async def help_command(m):
    await m.answer(
        '/nobar — buat room grup\n'
        '/join KODE — join\n'
        '/room KODE — info\n'
        '/play KODE — buka Mini App\n'
        '/rooms — room aktif\n'
        '/upload KODE — buka uploader host\n'
        '/broadcast — owner, reply teks/foto'
    )


@router.message(Command('nobar'))
async def nobar(m, bot, settings, db):
    if m.chat.type not in {'group', 'supergroup'}:
        return await m.answer('Gunakan /nobar di grup.')
    if not await access(m, bot, settings):
        return

    await db.user(m.from_user)
    await db.group(m.chat)
    title = m.text.partition(' ')[2].strip() or f'Nobar {m.from_user.first_name}'
    title = title[:200]
    r = await create_room_with_retry(db, m.chat.id, m.from_user.id, title)
    await db.join(r['id'], m.from_user.id)
    safe_title = html.escape(title)
    await m.answer(
        f'🍿 <b>Room dibuat</b>\n{safe_title}\n'
        f'Kode: <code>{r["code"]}</code>\n'
        'Host bisa upload film maksimal 5 GiB dari Mini App.',
        reply_markup=kb(f'{settings.webapp_url}/?room={r["code"]}'),
    )


@router.message(Command('join'))
async def join(m, bot, settings, db):
    if not await access(m, bot, settings):
        return
    await db.user(m.from_user)
    args = m.text.split(maxsplit=1)
    if len(args) < 2:
        return await m.answer('Gunakan: /join KODE')
    r = await db.room(args[1])
    if not r:
        return await m.answer('❌ Room tidak ditemukan.')
    await db.join(r['id'], m.from_user.id)
    await m.answer(
        f'✅ Masuk {html.escape(r["title"])}',
        reply_markup=kb(f'{settings.webapp_url}/?room={r["code"]}'),
    )


@router.message(Command('room'))
async def room(m, bot, settings, db):
    if not await access(m, bot, settings):
        return
    await db.user(m.from_user)
    args = m.text.split(maxsplit=1)
    if len(args) < 2:
        return await m.answer('Gunakan: /room KODE')
    r = await db.room(args[1])
    if not r:
        return await m.answer('❌ Room tidak ditemukan.')
    await m.answer(
        f'🎬 {html.escape(r["title"])}\n'
        f'Kode: {r["code"]}\n'
        f'Status: {"▶️ Playing" if r["is_playing"] else "⏸️ Paused"}\n'
        f'Posisi: {int(r["position_seconds"])} detik'
    )


@router.message(Command('play'))
async def play(m, bot, settings, db):
    if not await access(m, bot, settings):
        return
    await db.user(m.from_user)
    args = m.text.split(maxsplit=1)
    if len(args) < 2:
        return await m.answer('Gunakan: /play KODE')
    r = await db.room(args[1])
    if not r:
        return await m.answer('❌ Room tidak ditemukan.')
    await db.join(r['id'], m.from_user.id)
    await m.answer('🎥 Buka Mini App:', reply_markup=kb(f'{settings.webapp_url}/?room={r["code"]}'))


@router.message(Command('upload'))
async def upload(m, bot, settings, db):
    if not await access(m, bot, settings):
        return
    await db.user(m.from_user)
    args = m.text.split(maxsplit=1)
    if len(args) < 2:
        return await m.answer('Gunakan: /upload KODE')
    r = await db.room(args[1])
    if not r:
        return await m.answer('❌ Room tidak ditemukan.')
    if r['host_user_id'] != m.from_user.id:
        return await m.answer('❌ Hanya host room yang boleh upload film.')
    await db.join(r['id'], m.from_user.id)
    await m.answer(
        '⬆️ Buka uploader:',
        reply_markup=kb(f'{settings.webapp_url}/?room={r["code"]}&upload=1'),
    )


@router.message(Command('rooms'))
async def rooms(m, bot, settings, db):
    if not await access(m, bot, settings):
        return
    await db.user(m.from_user)
    if m.chat.type not in {'group', 'supergroup'}:
        return await m.answer('Gunakan /rooms di grup.')
    rows = await db.pool.fetch(
        'SELECT code,title FROM rooms WHERE group_chat_id=$1 AND is_active ORDER BY created_at DESC',
        m.chat.id,
    )
    if not rows:
        return await m.answer('Tidak ada nobar aktif.')
    text = '\n'.join(f'🎬 {x["code"]} — {html.escape(x["title"])}' for x in rows)
    await m.answer(text)


@router.message(Command('addfilm'))
async def addfilm(m, bot, settings, db):
    if not await access(m, bot, settings):
        return
    await m.answer(
        'ℹ️ /addfilm tidak lagi dipakai untuk menyimpan film. '
        'Gunakan /upload KODE agar film dikirim langsung dari Mini App ke B2. '
        'Batas upload 5 GiB.'
    )


@router.message(Command('broadcast'))
async def broadcast(m, bot, settings, db):
    if m.from_user.id != settings.owner_id:
        return await m.answer('❌ Khusus owner.')
    t = m.reply_to_message
    if not t:
        return await m.answer('Reply pesan teks atau foto lalu /broadcast.')

    rows = await db.pool.fetch('SELECT user_id FROM users WHERE user_id IS NOT NULL')
    ok = 0
    for x in rows:
        try:
            if t.photo:
                await bot.send_photo(x['user_id'], t.photo[-1].file_id, caption=t.caption or '')
            elif t.text:
                await bot.send_message(x['user_id'], t.text)
            else:
                await bot.copy_message(x['user_id'], m.chat.id, t.message_id)
            ok += 1
        except Exception:
            pass
        await asyncio.sleep(0.04)
    await m.answer(f'📣 Broadcast selesai: {ok}/{len(rows)}')
