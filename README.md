# Nobar Telegram — 5 GiB production layout

Arsitektur final memakai **Telegram Bot + Telegram Mini App + PostgreSQL + Cloudflare R2**.

## Kenapa bukan GitHub untuk film?
GitHub Contents API bukan object storage untuk film besar. Versi ini tidak lagi membuat ZIP film atau menyimpan film di GitHub.

## Batas upload
Film maksimal **5 GiB** per object. Upload dilakukan dengan **S3 multipart upload** langsung dari browser ke R2, 4 part paralel, ukuran part 64 MiB. R2 mendukung multipart upload dan jauh lebih cocok untuk video besar.

## Alur
1. `/nobar` membuat room.
2. Host membuka Mini App.
3. Host memilih video maksimal 5 GiB.
4. Backend membuat multipart upload dan presigned URL.
5. Browser mengirim part langsung ke R2 — Railway tidak menampung file 5 GiB.
6. Backend memverifikasi ukuran object lalu otomatis memasang film ke room.
7. Mini App memakai presigned GET URL R2 untuk streaming, sehingga browser dapat melakukan range request/seek tanpa download seluruh film ke Railway.
8. Host mengontrol play/pause/seek; penonton melakukan sync otomatis setiap detik.

## Penting: `/addfilm`
Telegram Bot API resmi saat ini hanya mengizinkan bot **mengunduh file sampai 20 MB**. Karena itu film besar **tidak boleh** diambil dengan `bot.download_file()`. Gunakan `/upload` atau tombol upload di Mini App.

## Environment Railway
Isi:

- `BOT_TOKEN`
- `DATABASE_URL`
- `OWNER_ID`
- `REQUIRED_CHANNEL`
- `WEBAPP_URL`
- `R2_ENDPOINT`
- `R2_BUCKET`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_REGION=auto`
- `PORT` (Railway biasanya mengisi sendiri)

## Cloudflare R2
Buat bucket private, API token dengan permission object read/write, lalu isi endpoint berbentuk:
`https://<ACCOUNT_ID>.r2.cloudflarestorage.com`

Atur CORS bucket agar Mini App boleh `PUT` ke R2 dan membaca header `ETag`. Contoh minimal:

```json
[
  {
    "AllowedOrigins": ["https://DOMAIN-MINI-APP-KAMU"],
    "AllowedMethods": ["PUT", "GET", "HEAD"],
    "AllowedHeaders": ["Content-Type", "*"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

## Database
`schema.sql` memakai `CREATE TABLE IF NOT EXISTS` dan `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, jadi database lama dapat melakukan migrasi ringan saat startup.

## Streaming
Film tidak diextract ke `/tmp`, tidak di-zip ulang, dan tidak di-download ke Railway. R2 mengirim file langsung ke browser memakai presigned URL. Ini jauh lebih aman untuk film multi-GB.
