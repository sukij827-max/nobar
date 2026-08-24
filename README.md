# Nobar Telegram — 5 GiB production layout

Arsitektur final memakai **Telegram Bot + Telegram Mini App + PostgreSQL + Backblaze B2**.

## Penyimpanan film
Film **tidak disimpan di GitHub** dan tidak ditampung di Railway. GitHub hanya menyimpan source code. Film dikirim langsung dari browser Mini App ke Backblaze B2 memakai S3-compatible multipart upload.

## Batas upload
Film maksimal **5 GiB** per object. Upload memakai multipart upload dengan part 64 MiB dan 4 worker paralel di browser.

## Alur
1. `/nobar` membuat room.
2. Host membuka Mini App.
3. Host memilih video maksimal 5 GiB.
4. Backend membuat multipart upload dan presigned URL.
5. Browser mengirim part langsung ke B2 — Railway tidak menampung file 5 GiB.
6. Backend memverifikasi seluruh part dan ukuran object lalu memasang film ke room.
7. Mini App memakai presigned GET URL B2 untuk streaming dan seek.
8. Host mengontrol play/pause/seek; penonton melakukan sinkronisasi otomatis.

## Command
- `/nobar` — membuat room di grup.
- `/join KODE` — masuk room.
- `/room KODE` — melihat status room.
- `/play KODE` — membuka Mini App.
- `/upload KODE` — membuka uploader khusus host.
- `/rooms` — melihat room aktif di grup.
- `/broadcast` — owner mengirim broadcast dengan reply pesan.

`/addfilm` tidak lagi mengunduh film melalui Telegram Bot API. Film besar harus memakai Mini App supaya file tidak melewati Railway.

## Environment Railway
Isi:

- `BOT_TOKEN`
- `DATABASE_URL`
- `OWNER_ID`
- `REQUIRED_CHANNEL`
- `WEBAPP_URL`
- `B2_ENDPOINT`
- `B2_BUCKET`
- `B2_KEY_ID`
- `B2_APPLICATION_KEY`
- `B2_REGION` — contoh `us-east-005`; sesuaikan dengan region endpoint bucket B2 kamu.
- `PORT` — Railway biasanya mengisi sendiri.

Backblaze B2 S3-compatible API memakai endpoint sesuai region bucket dan AWS Signature V4. citeturn0search0turn0search7

## Backblaze B2
Buat bucket private dan application key yang mempunyai izin object yang diperlukan. Endpoint S3 B2 berbentuk `https://s3.<region>.backblazeb2.com` dan region harus sesuai dengan endpoint bucket. citeturn0search0turn0search7

Atur CORS bucket agar domain Mini App boleh melakukan `PUT` dan membaca header `ETag`. Contoh:

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
`schema.sql` melakukan migrasi idempotent untuk tabel yang dipakai bot. Film upload sekarang memiliki `room_id` sehingga upload gagal/ulang pada satu room tidak mencampur upload room lain.

## Streaming
Film tidak diekstrak ke `/tmp`, tidak di-zip ulang, dan tidak di-download ke Railway. B2 mengirim object langsung ke browser melalui presigned URL.
