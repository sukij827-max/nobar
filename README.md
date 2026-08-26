# NOBAR Telegram

Arsitektur: **Telegram Bot + Telegram Mini App + PostgreSQL + Backblaze B2**.

## Alur film
Film **di-upload melalui Telegram Bot**, bukan melalui Mini App. Setelah berhasil disimpan ke Backblaze B2, metadata film disimpan di PostgreSQL sebagai **Film Tersimpan**.

Film yang sudah tersimpan tidak perlu di-upload ulang. Host cukup membuka **🎞️ Film Tersimpan**, memilih film, lalu memasangnya ke room NOBAR.

GitHub hanya menyimpan source code dan Railway tidak dipakai sebagai penyimpanan permanen film.

## Alur NOBAR
1. Host membuat room.
2. Host memilih film dari **Film Tersimpan**.
3. Host menekan **Share ke Grup**.
4. Bot mengirim tombol **🎬 GABUNG NOBAR** menggunakan Telegram Mini App direct link (`startapp`).
5. Saat tombol ditekan, Telegram langsung membuka Mini App — tidak diarahkan ke `/start` terlebih dahulu.
6. Mini App otomatis mendaftarkan viewer ke room.
7. Mini App mengambil film yang sudah tersimpan di B2 melalui presigned GET URL.
8. Host mengontrol play/pause/seek dan peserta melakukan sinkronisasi otomatis.

## Mini App
Mini App dibuat sederhana untuk tahap awal dan fokus pada fitur inti:
- Player video
- Judul dan informasi room
- Jumlah member
- Status play/pause
- Kontrol host
- Sinkronisasi posisi dan status pemutaran
- Streaming langsung dari Backblaze B2

**Tidak ada uploader film di Mini App.**

## Menu Bot
- 🎬 Buat Room
- 🔗 Join Room
- 🔎 Cek NOBAR
- 📋 Info Room
- 📤 Tambah Film
- 🎞️ Film Tersimpan
- 👤 Room Saya
- ❓ Bantuan
- 💬 Feedback
- 🔐 Panel Admin

## Command
- `/nobar` — membuat room.
- `/join KODE` — masuk room.
- `/room KODE` — melihat status room.
- `/play KODE` — membuka player NOBAR.
- `/upload` — petunjuk upload film melalui bot.
- `/rooms` — melihat room aktif.
- `/invite` — petunjuk share room.
- `/feedback` — mengirim feedback.

## Penyimpanan
Film disimpan sebagai object di Backblaze B2. PostgreSQL menyimpan metadata film, termasuk judul, ukuran, MIME type, SHA-256, owner, dan object key.

Satu film tersimpan dapat dipakai kembali untuk banyak room melalui `rooms.film_id`, sehingga tidak terjadi upload ulang hanya karena membuat room baru.

## Environment Railway
- `BOT_TOKEN`
- `DATABASE_URL`
- `OWNER_ID`
- `REQUIRED_CHANNEL`
- `WEBAPP_URL`
- `B2_ENDPOINT`
- `B2_BUCKET`
- `B2_KEY_ID`
- `B2_APPLICATION_KEY`
- `B2_REGION`
- `PORT`

## Backblaze B2
Gunakan bucket private dan application key dengan izin object yang diperlukan. Mini App hanya menerima presigned GET URL untuk streaming film.
