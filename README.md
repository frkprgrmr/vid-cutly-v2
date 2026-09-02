# VidCutly

Web app lokal untuk mengubah satu podcast YouTube Indonesia menjadi lima kandidat clip vertikal. Gemini menganalisis audio dan visual video, lalu pengguna meninjau timing dan headline sebelum FFmpeg merender video 9:16, subtitle, dan thumbnail.

> Gunakan hanya video yang Anda miliki atau yang telah memberikan izin/lisensi untuk diunduh, diedit, dan dipublikasikan ulang.

## Fitur MVP

- Input satu URL YouTube dan konfirmasi hak penggunaan.
- Analisis multimodal Gemini langsung dari URL publik.
- Lima kandidat dengan skor hook, insight, emosi, keunikan, konteks mandiri, dan kecocokan short-form.
- Preview video sumber serta edit start/end, judul, dan headline thumbnail.
- Auto-reframe 9:16 dengan face tracking, smoothing, dan hysteresis agar perpindahan fokus tidak agresif.
- Pilihan framing per clip: Auto, Kiri, Tengah, Kanan, Fit + Blur, atau Split-screen untuk dialog dua orang.
- Subtitle dua baris dari subtitle Indonesia YouTube, dengan highlight kata penting.
- Thumbnail portrait dari frame tajam dengan headline besar.
- Penyimpanan SQLite dan file video sepenuhnya lokal.
- Upload langsung ke channel YouTube melalui OAuth, lengkap dengan pilihan private/unlisted/public dan progres upload.

## Kebutuhan

- Linux
- Python 3.11+
- Node.js 20+
- Gemini API key

## Instalasi

Jalankan setup. Binary FFmpeg akan ikut dipasang di virtual environment sehingga tidak memerlukan akses root:

```bash
./scripts/setup.sh
```

Isi `.env`:

```dotenv
GEMINI_API_KEY=masukkan_key_di_sini
GEMINI_MODEL=gemini-3.6-flash
```

## Menyiapkan upload YouTube

Akun Google Cloud boleh berbeda dengan akun pemilik channel. Project Google Cloud hanya menyediakan aplikasi OAuth; saat menekan **Hubungkan YouTube**, loginlah memakai akun yang memiliki channel tujuan.

1. Di Google Cloud Console, aktifkan **YouTube Data API v3**.
2. Buka **Google Auth Platform**, isi OAuth consent screen, lalu pilih audience **External**.
3. Selama aplikasi masih berstatus Testing, tambahkan email akun pemilik channel sebagai **Test user**.
4. Buat OAuth Client dengan application type **Web application**.
5. Tambahkan Authorized redirect URI persis: `http://127.0.0.1:8000/api/youtube/callback`.
6. Salin Client ID dan Client Secret ke `.env`:

```dotenv
YOUTUBE_CLIENT_ID=client_id_dari_gcp
YOUTUBE_CLIENT_SECRET=client_secret_dari_gcp
YOUTUBE_REDIRECT_URI=http://127.0.0.1:8000/api/youtube/callback
```

Restart aplikasi setelah mengubah `.env`, lalu klik **Hubungkan YouTube** di kanan atas. Upload baru dibuat sebagai **private** secara default agar dapat ditinjau lebih dahulu. Kredensial akses channel disimpan lokal di `data/youtube-token.json` dan folder `data/` tidak masuk Git.

> YouTube API key tidak dapat dipakai untuk mengunggah video. Upload memerlukan OAuth Client ID dan Client Secret.

Jalankan aplikasi:

```bash
./scripts/run.sh
```

Buka [http://127.0.0.1:8000](http://127.0.0.1:8000).

Untuk development dengan hot reload backend dan frontend:

```bash
./scripts/dev.sh
```

Frontend tersedia di `http://127.0.0.1:5173`.

## Cara kerja

1. `yt-dlp` menyimpan video dan subtitle otomatis Indonesia ke `data/jobs/<id>`.
2. Gemini memahami video YouTube publik dan mengembalikan lima kandidat terstruktur.
3. Pengguna meninjau kandidat di dashboard dan menyimpan revisi timing/tulisan.
4. OpenCV mengestimasi fokus wajah dengan smoothing dan hysteresis.
5. FFmpeg merender MP4 1080×1920; Pillow membuat thumbnail.
6. Jika diminta, backend mengunggah MP4 hasil render ke channel yang terhubung melalui YouTube Data API.

URL video dikirim ke Gemini untuk analisis. Video hasil download, hasil render, database, dan thumbnail tetap berada di komputer lokal.

## Test

```bash
.venv/bin/pytest
cd frontend && npm run build
```

Test tidak mengunduh video dan tidak memanggil Gemini API.

## Dokumen produk

Lihat [PRD](docs/PRD.md).
