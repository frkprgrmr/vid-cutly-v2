# PRD — Viral Podcast Clipper (MVP)

**Status:** Draft v1.0  
**Platform:** Web app lokal (Linux)  
**Pengguna:** Satu pengguna pribadi  
**Tanggal:** 31 Agustus 2026

## 1. Ringkasan

Viral Podcast Clipper adalah web app lokal untuk mengubah satu podcast YouTube berbahasa Indonesia menjadi lima video pendek vertikal yang siap ditinjau dan diunduh untuk YouTube Shorts, TikTok, atau Instagram Reels.

Pengguna memasukkan URL video. App mengambil sumber video yang pengguna berhak gunakan, membuat transkrip bertimestamp, lalu memakai Gemini untuk menyarankan bagian yang paling berpotensi menarik perhatian. Setiap kandidat dapat dipreview dan batas awal/akhirnya dapat disesuaikan sebelum video akhir dirender dengan reframing vertikal, subtitle, dan thumbnail.

MVP tidak memublikasikan konten ke platform sosial secara otomatis.

## 2. Masalah yang Diselesaikan

Mengedit podcast berdurasi sekitar satu jam menjadi clip vertikal memerlukan waktu karena editor perlu:

- menonton atau menyimak seluruh video untuk menemukan momen yang kuat;
- memilih bagian yang memiliki hook, emosi, insight, humor, atau konflik;
- memotong dengan konteks yang cukup;
- menjaga pembicara utama tetap terlihat nyaman dalam format 9:16;
- membuat subtitle dan thumbnail yang menarik.

App mengotomatisasi pekerjaan berulang tersebut, sementara keputusan akhir tetap berada pada pengguna.

## 3. Tujuan dan Bukan Tujuan

### Tujuan MVP

- Memproses satu video podcast Indonesia berdurasi kurang lebih 60 menit dari sebuah URL.
- Memberikan tepat lima kandidat clip yang diberi alasan dan skor.
- Memungkinkan pengguna preview lalu mengubah batas awal dan akhir setiap kandidat sebelum render.
- Menghasilkan video MP4 vertikal 9:16, subtitle Bahasa Indonesia yang mudah dibaca, dan thumbnail terpisah.
- Berjalan sepenuhnya di komputer Linux pengguna kecuali panggilan Gemini API.

### Bukan Tujuan MVP

- Upload otomatis ke YouTube, TikTok, atau Instagram.
- Pemrosesan batch atau banyak pengguna.
- Editor video multitrack atau editor subtitle penuh.
- Dukungan bahasa selain Indonesia.
- Jaminan bahwa clip akan menjadi viral atau prediksi performa yang presisi.
- Mengakali pembatasan YouTube atau memproses konten tanpa hak penggunaan.

## 4. Pengguna dan Kondisi Penggunaan

Pengguna adalah pemilik app yang mengolah podcast YouTube dari kreator yang telah memberi izin, memiliki lisensi yang sesuai, atau konten yang memang dimiliki pengguna.

Sebelum memulai job, pengguna wajib mencentang pernyataan: **"Saya memiliki hak atau izin untuk mengunduh, mengedit, dan menggunakan video ini."** App menyimpan konfirmasi tersebut pada data job.

## 5. Definisi Clip yang Berpotensi Menarik

Gemini tidak boleh hanya memilih kalimat yang terdengar heboh. Setiap kandidat dinilai dengan rubrik berikut:

| Sinyal | Bobot awal | Yang dicari |
|---|---:|---|
| Hook | 25% | Pembuka yang membuat penonton ingin lanjut menonton dalam 1–3 detik pertama |
| Nilai/insight | 20% | Pendapat, cerita, atau pelajaran yang dapat dipahami tanpa menonton video penuh |
| Emosi/ekspresi | 15% | Tawa, kejutan, antusiasme, ketegangan, atau reaksi wajah yang jelas |
| Konflik/keunikan | 15% | Kontras pendapat, fakta mengejutkan, atau sudut pandang tidak biasa |
| Keterpahaman mandiri | 15% | Konteks cukup; tidak bergantung pada kalimat sebelum atau sesudahnya |
| Kesesuaian format pendek | 10% | Ritme baik dan dapat menjadi clip 25–90 detik |

Skor hanya merupakan rekomendasi editorial. Pengguna selalu memutuskan apakah kandidat dirender.

## 6. User Flow

1. Pengguna membuka dashboard lokal dan memasukkan URL video YouTube.
2. Pengguna mengonfirmasi hak/izin penggunaan, lalu menekan **Analisis video**.
3. App memvalidasi URL, mengambil sumber video, dan menampilkan progres tiap tahap.
4. App mengekstrak audio, membuat transkrip bertimestamp, serta menyiapkan kandidat visual/audio.
5. Gemini memilih dan memberi peringkat lima segmen dengan judul kerja, skor, alasan, dan rentang waktu.
6. Pengguna membuka setiap kandidat dalam preview, memutar video, serta menggeser waktu mulai dan selesai.
7. Pengguna memilih kandidat yang akan dirender dan dapat mengubah headline thumbnail/teks judul.
8. App merender hasil akhir serta membuat thumbnail.
9. Pengguna mengunduh MP4 dan PNG/JPG dari halaman hasil.

## 7. Kebutuhan Fungsional

### 7.1 Input dan job

- Menerima satu URL YouTube untuk setiap job.
- Menolak URL yang bukan URL video YouTube yang valid.
- Menampilkan status: antre, mengambil video, mentranskrip, menganalisis, siap direview, merender, selesai, atau gagal.
- Menyimpan hasil job dan berkas lokal agar dapat dibuka kembali selama belum dihapus pengguna.
- Memproses satu job pada satu waktu pada MVP.

### 7.2 Transkrip dan analisis

- Membuat transkrip Bahasa Indonesia bertimestamp dari audio video.
- Menampilkan transkrip yang relevan ketika kandidat sedang dipreview.
- Mengirim transcript yang sudah dipecah menjadi bagian-bagian beserta metadata visual/audio yang relevan ke Gemini.
- Menerima keluaran terstruktur: `start_time`, `end_time`, `score`, `reason`, `title`, `hook`, dan `thumbnail_headline`.
- Menolak kandidat yang tumpang tindih secara berarti dengan kandidat lebih tinggi, kecuali pengguna memilihnya sendiri.
- Menjaga durasi awal kandidat dalam rentang 25–90 detik; pengguna boleh menyesuaikan sedikit pada tahap review.

### 7.3 Reframing 9:16

- Membuat video 1080×1920 secara default, dengan fallback 720×1280 bila performa mesin tidak mencukupi.
- Mendeteksi wajah dan memperkirakan pembicara aktif dari kombinasi wajah, pergerakan mulut, dan energi suara bila tersedia.
- Mengikuti pembicara aktif dengan gerakan crop yang halus.
- Tidak memindahkan framing sebelum fokus baru stabil dalam jendela waktu minimum.
- Membatasi frekuensi perpindahan dan menerapkan easing pada gerakan crop agar penonton tidak pusing.
- Jika deteksi tidak yakin atau wajah tidak ditemukan, memakai crop tengah yang stabil, bukan berpindah acak.

### 7.4 Subtitle dan judul dalam video

- Menghasilkan subtitle Bahasa Indonesia dari transkrip bertimestamp.
- Menampilkan maksimal dua baris subtitle pada satu waktu.
- Menyorot kata atau frasa penting; tidak memakai karaoke per kata penuh secara default.
- Menghindari area wajah dan mengatur posisi subtitle bila menutupi subjek utama.
- Menambahkan judul/hook singkat di bagian atas video, dapat diedit sebelum render.

### 7.5 Thumbnail

- Memilih beberapa frame kandidat berdasarkan ketajaman, wajah/ekspresi, dan komposisi.
- Meminta Gemini memberi nilai serta headline thumbnail yang menarik tetapi tidak menyesatkan.
- Membuat thumbnail portrait dengan headline besar yang dapat diedit pengguna.
- Menyimpan thumbnail sebagai PNG atau JPG terpisah.

### 7.6 Preview dan review

- Memutar preview kandidat sebelum render akhir.
- Mengizinkan perubahan start/end melalui input waktu dan kontrol timeline sederhana.
- Menampilkan estimasi durasi hasil.
- Memungkinkan pengguna mengubah judul dalam video dan headline thumbnail.
- Mengharuskan aksi eksplisit **Render**; app tidak merender kelima clip secara otomatis setelah analisis.

## 8. Kebutuhan Nonfungsional

- Aplikasi dapat dijalankan di Linux modern dengan CPU Ryzen 7000 tanpa GPU khusus.
- Semua video sementara, hasil render, dan database job disimpan lokal.
- API key Gemini tidak pernah ditulis ke source code atau dikirim ke browser; key dibaca backend dari environment variable.
- Dashboard hanya didengarkan pada `localhost` secara default.
- Kegagalan download, transkrip, Gemini, atau render harus menampilkan pesan yang bisa dipahami dan memungkinkan retry tahap yang gagal.
- App harus menampilkan penggunaan disk sementara dan menyediakan penghapusan job secara manual.

## 9. Arsitektur MVP yang Diusulkan

| Komponen | Pilihan awal | Tanggung jawab |
|---|---|---|
| Dashboard | React + TypeScript | Input URL, progres, preview, review, download |
| API lokal | Python + FastAPI | Job orchestration, API, validasi, penyimpanan metadata |
| Worker | Python process/queue lokal | Tahap download, transkrip, analisis, dan render agar UI tidak macet |
| Pengambil sumber | Alat pengambil yang sesuai izin dan aturan platform | Mengambil sumber video yang diizinkan pengguna |
| Video/render | FFmpeg | Extract audio, cut, crop/reframe, subtitle burn-in, encode MP4 |
| Transkripsi | Subtitle YouTube + fallback transkripsi Gemini | Transcript Bahasa Indonesia dengan timestamp tanpa beban Whisper pada CPU |
| Visual analysis | OpenCV + MediaPipe atau ekuivalen | Face tracking, kandidat frame thumbnail, data reframing |
| AI editor | Gemini API | Seleksi segmen, alasan/skor, judul, headline thumbnail |
| Penyimpanan | SQLite + filesystem lokal | Job, kandidat, keputusan review, lokasi artefak |

### Diagram alur

```text
URL + konfirmasi hak
          │
          ▼
 Ambil sumber video → audio/transkrip → analisis visual
          │                    │              │
          └────────────────────┴──────► Gemini memilih 5 kandidat
                                                │
                                                ▼
                                    Preview + edit batas/writing
                                                │
                                                ▼
                                  FFmpeg render 9:16 + subtitle
                                                │
                                                ▼
                                   5 MP4 + thumbnail untuk download
```

## 10. Data Utama

### Job

- ID, URL sumber, judul video, durasi video, status, waktu dibuat/diperbarui.
- Konfirmasi hak penggunaan dan waktu konfirmasinya.
- Lokasi file sumber, audio, transkrip, preview, hasil render, dan thumbnail.
- Pesan error tahap terakhir bila ada.

### Kandidat clip

- ID, job ID, urutan, waktu mulai/selesai rekomendasi dan versi yang diedit.
- Skor total, rincian skor, alasan Gemini, hook, dan transcript terkait.
- Judul dalam video dan headline thumbnail yang dapat diedit.
- Status review: pending, dipilih, tidak dipilih, rendered, atau gagal.

## 11. Kriteria Penerimaan MVP

MVP dinyatakan siap diuji ketika, pada minimal dua podcast Indonesia yang pengguna berhak gunakan:

1. Pengguna dapat memasukkan URL, mengonfirmasi hak, dan melihat progres tiap tahap.
2. App menghasilkan lima kandidat yang memiliki timestamp, skor, alasan, dan preview.
3. Pengguna dapat mengubah batas start/end dan teks judul sebelum render.
4. Minimal satu kandidat dapat dirender menjadi MP4 9:16 yang dapat diputar normal.
5. Hasil memiliki subtitle Indonesia yang sinkron dan terbaca di layar ponsel.
6. Framing tidak berganti secara cepat atau acak; bila deteksi gagal, crop tetap stabil.
7. Setiap hasil render memiliki thumbnail terpisah dengan headline yang dapat diedit.
8. API key tidak terlihat di browser, source code, atau file yang dibagikan.

## 12. Risiko dan Mitigasi

| Risiko | Dampak | Mitigasi MVP |
|---|---|---|
| Hak cipta/izin tidak jelas | Risiko penggunaan konten | Checkbox konfirmasi hak; hanya proses sumber yang pengguna berwenang gunakan |
| Unduhan sumber gagal | Job terhenti | Pesan error jelas, retry, serta opsi masa depan untuk upload file yang sudah dimiliki pengguna |
| Transkrip kurang akurat | Subtitle/seleksi clip buruk | Review pengguna; simpan transcript untuk koreksi tahap berikutnya |
| Gemini memilih momen kurang tepat | Kandidat tidak menarik | Tampilkan 5 kandidat dengan alasan dan skor; iterasi prompt/rubrik pada video uji |
| CPU-only lambat | Waktu proses lama | Satu job per waktu, progres jelas, preview resolusi lebih rendah, opsi GPU di fase lanjut |
| Reframe terlalu agresif | Video melelahkan ditonton | Hysteresis, jeda perpindahan, easing, dan fallback crop tengah stabil |
| Judul clickbait menyesatkan | Kepercayaan audiens turun | Headline selalu dapat diedit dan harus didasarkan pada isi segmen |

## 13. Fase Setelah MVP

- Upload file lokal sebagai alternatif URL.
- Pemrosesan batch dan antrean lebih dari satu video.
- Pilihan template visual subtitle/thumbnail.
- Preset per channel atau jenis podcast.
- Deteksi beberapa pembicara yang lebih akurat.
- Integrasi upload ke platform sosial setelah alur review stabil.
- GPU acceleration opsional untuk transkripsi dan render.

## 14. Keputusan yang Ditunda

- Kalibrasi model Gemini paling hemat/akurat setelah pengujian pada podcast nyata (default awal dapat diubah lewat konfigurasi).
- Resolusi preview final dan batas ukuran storage.
- Batas maksimal durasi sumber yang didukung.
- Template visual/warna/jenis font default.
- Strategi menghapus file sumber sementara setelah hasil disetujui.
