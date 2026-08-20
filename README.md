# 🤖 Sistem Rumah Amal USK (Bot WhatsApp + Admin Dashboard + Web Chatbot)

Sistem donasi digital Rumah Amal Masjid Jamik USK dengan 3 titik akses: **Bot WhatsApp** (hibrida Fast-Path Regex + State Machine + Google Gemini 2.5 Flash Cloud AI + Vision OCR + Supabase Cloud), **Admin Dashboard** (`/admin`, panel kendali internal staf), dan **Web Chatbot Publik** (`/`, widget chat untuk website). Melayani informasi program, penyaluran donasi/zakat, permohonan bantuan (PINTAS/BPRA-UKT), cek riwayat transaksi (dengan verifikasi OTP di kanal web), deteksi sapaan gender dinamis, generator doa syar'i acak, dan notifikasi *alert* otomatis ke Admin.

---

## 🏛️ 1. Arsitektur Sistem Utama

Berikut adalah arsitektur menyeluruh sistem **Bot WhatsApp Rumah Amal USK**, menggambarkan alur komunikasi antar-komponen dari Pengguna, WAHA Engine, FastAPI Controller, State Machine (FSM), Google Gemini Cloud AI, hingga Database Supabase Cloud dan WhatsApp Admin:

```mermaid
flowchart TD
    subgraph WA_Layer ["📱 WhatsApp & Gateway Layer"]
        User["👤 Pengguna / Donatur (WA Mobile / Web / Desktop)"]
        WAHA["⚡ WAHA Docker Container (DevLikeAPro WebJS)"]
        AdminWA["🆘 Admin WA (0812-6966-6776)"]
    end

    subgraph App_Layer ["🚀 FastAPI Webhook Engine (main.py / bot_webhook.py)"]
        Router["HTTP Router (/webhook)"]
        AuthCheck["🔒 Security Check (WAHA_API_KEY Header)"]
        Deduplication["🛡️ Message Deduplication (PROCESSED_MSG_IDS)"]
        RateLimiter["⚡ Rate Limiter (Max 20 req/min per WA)"]
        GenderEngine["👤 Gender Detector Engine (Bapak/Ibu/Kak)"]
        MediaDecoder["🖼️ Base64 & Media URL HD Image Downloader (>30KB Threshold)"]
        LIDResolver["🔍 LID & Contact Resolver (LID -> Phone Number & Name)"]
        FastPath["⚡ Fast-Path Intent Router (0.001s Regex & Typo-Tolerant)"]
        HealthCheck["🏥 WAHA Session Health Monitor (5 Min Interval)"]
    end

    subgraph State_Layer ["💾 State Machine & Dual Storage Engine"]
        FSM["🔄 Finite State Machine (IDLE / TANYA_PROGRAM / PILIH_PROGRAM / MENUNGGU_ADMIN / NUNGGU_BUKTI_TRANSFER)"]
        SQLiteDB[("💾 Local SQLite DB (donatur.db in Docker Volume)")]
        SupabaseDB[("☁️ Supabase Cloud DB (transaksi_donasi & master_program)")]
        AutoSync["🔄 Background Auto-Sync Worker (SQLite -> Supabase)"]
    end

    subgraph AI_Layer ["🧠 Google Gemini Cloud AI Layer (Zero VPS Load)"]
        GeminiAPI["☁️ Google Gemini 2.5 Flash API (Klasifikasi Intent Fallback & NER)"]
        StaticQA["📄 Jawaban Q&A dari QA_SCRIPT Statis (Tanpa Parafrase LLM)"]
        DoaGen["🤲 Random Doa Syar'i Generator (4 Variasi Doa Arab & Terjemahan)"]
        VisionOCR["👁️ Multimodal Vision OCR (Resi BSI Mobile & BYOND Reader)"]
    end

    subgraph Log_Layer ["📝 Logging & Observability Layer"]
        ProdLogger["📊 Production Logger (RotatingFileHandler -> logs/app.log)"]
    end

    User -->|"1. Kirim Pesan / Resi / Panggilan"| WAHA
    WAHA -->|"2. HTTP POST Webhook Payload"| Router
    Router --> AuthCheck
    AuthCheck --> Deduplication
    Deduplication --> RateLimiter
    RateLimiter --> MediaDecoder
    MediaDecoder --> LIDResolver
    LIDResolver --> GenderEngine
    GenderEngine --> FastPath

    FastPath -->|"Cek Status Sesi & State"| FSM
    FSM <-->|"Sync Status Sesi"| SQLiteDB
    FSM <-->|"Sync Transaksi & Master Program"| SupabaseDB
    SQLiteDB -.-> AutoSync
    AutoSync -.-> SupabaseDB

    FastPath -->|"Foto Resi (Media)"| VisionOCR
    FastPath -->|"Pertanyaan Tidak Kena Keyword Lokal"| GeminiAPI
    GeminiAPI -->|"Hasil Klasifikasi Intent"| StaticQA
    FastPath -->|"Pertanyaan Kena Keyword Lokal (Gratis, 0 Panggilan API)"| StaticQA
    FastPath --> DoaGen

    HealthCheck -.->|"Ping Alert (WAHA Down)"| AdminWA
    FastPath -->|"Pengajuan Admin (PINTAS/BPRA-UKT/DLL)"| AdminWA
    FastPath -->|"Balasan Pesan WA"| WAHA
    WAHA -->|"Balas Chat"| User

    Router -.->|"Record System Logs"| ProdLogger
    FastPath -.->|"Record Activity Logs"| ProdLogger
```

---

## 🔄 2. State Machine (FSM 5 Menu Utama & Hirarki Navigasi)

Diagram berikut menjelaskan transisi status (*State Machine*) percakapan pengguna dengan 5 pilihan menu utama serta navigasi dua tingkat (**Level 1: 1-10 & 0, Level 2: 1-N, 11, 0**):

```mermaid
stateDiagram-v2
    [*] --> IDLE : Pengguna Baru / Sesi Reset

    state IDLE {
        [*] --> MenuUtama5Pilihan
        MenuUtama5Pilihan --> Pilihan1_TanyaProgram : Ketik 1 ("Program apa saja")
        MenuUtama5Pilihan --> Pilihan2_InginBerdonasi : Ketik 2 ("Ingin berdonasi")
        MenuUtama5Pilihan --> Pilihan3_AlamatKantor : Ketik 3 ("Alamat kantor")
        MenuUtama5Pilihan --> Pilihan4_CekRiwayat : Ketik 4 ("Cek riwayat transaksi")
        MenuUtama5Pilihan --> Pilihan5_HubungiAdmin : Ketik 5 ("Hubungi admin")
    }

    IDLE --> TANYA_PROGRAM : Pilihan 1
    IDLE --> PILIH_PROGRAM : Pilihan 2
    IDLE --> MENUNGGU_ADMIN : Pilihan 5

    state TANYA_PROGRAM {
        [*] --> KatalogPilihanC
        KatalogPilihanC --> DetailProgram : Ketik 1 s.d. 10
        KatalogPilihanC --> IDLE : Ketik 0 (Kembali ke Menu Utama)
        DetailProgram --> KatalogPilihanC : Ketik 11 (Kembali ke Daftar Program)
        DetailProgram --> IDLE : Ketik 0 (Kembali ke Menu Utama)
        DetailProgram --> MENUNGGU_ADMIN : Balas "Ya" (Sambung Admin)
    }

    state PILIH_PROGRAM {
        [*] --> Menu4Donasi
        Menu4Donasi --> NUNGGU_BUKTI_TRANSFER : Pilih Nomor 1-4 (Zakat/Infak/Donasi)
    }

    state MENUNGGU_ADMIN {
        [*] --> KonfirmasiAdmin
        KonfirmasiAdmin --> PingAdminSuccess : Balas "Ya" / "Iya"
        KonfirmasiAdmin --> BatalAdmin : Balas "Tidak" / "Batal"
    }

    state NUNGGU_BUKTI_TRANSFER {
        [*] --> WaitReceipt
        WaitReceipt --> ProcessingOCR : Kirim Foto Resi / Input Manual
        ProcessingOCR --> SaveSuccess : OCR / Vision Sukses
        ProcessingOCR --> RetryReceipt : Gambar Buram / Error
    }

    PingAdminSuccess --> IDLE : Send Alert to Admin WA & Reset
    BatalAdmin --> IDLE : Reset State
    SaveSuccess --> IDLE : Simpan ke Supabase & Reset + Random Doa
    RetryReceipt --> NUNGGU_BUKTI_TRANSFER : Minta Ulang Resi
```

---

## 💸 3. Alur Konfirmasi Pembayaran (Foto Resi -> Baca Otomatis -> Simpan)

Diagram berikut menjelaskan apa yang terjadi saat donatur mengirim foto bukti transfer, dari foto diterima sampai tercatat di sistem - termasuk pengaman yang memastikan data yang tersimpan benar-benar valid, tidak asal simpan meski hasil bacaan AI kurang jelas:

```mermaid
flowchart TD
    Start["👤 Donatur Kirim Foto Bukti Transfer"] --> Download["📥 Bot Mengunduh Foto Resolusi Penuh"]
    Download --> Baca["🔍 Bot Membaca Nama & Nominal dari Foto Pakai AI"]
    Baca --> Cek{"✅ Apakah Nominal Terbaca Jelas & Masuk Akal?"}

    Cek -- "Ya, Terbaca Jelas" --> Simpan["💾 Catat Transaksi ke Database"]
    Simpan --> Doa["🤲 Kirim Balasan Doa & Konfirmasi ke Donatur"]

    Cek -- "Tidak / Foto Buram / Meragukan" --> Retry["✍️ Bot Minta Donatur Ketik Ulang Nama & Nominal Secara Manual"]
    Retry --> Baca
```

---

## 🤲 4. Random Doa Syar'i Generator Engine (`admin_scripts.py`)

Diagram alur berikut menjelaskan bagaimana sistem menghasilkan **Variasi Doa Syar'i Acak** berbahasa Arab + terjemahan yang berganti-ganti secara alami saat donatur berdonasi:

```mermaid
flowchart TD
    StartDoa["🤲 Panggilan Konfirmasi Donasi (Zakat/Infak)"] --> GetSalutation["👤 Ambil Sapaan Gender (Bapak / Ibu / Kak)"]
    GetSalutation --> FormatNominal["💰 Format Nominal (Rp 100.000)"]
    FormatNominal --> RandomSelect{"🎲 Select Random Doa (1 s.d 4)"}

    RandomSelect -- "Variasi 1" --> Doa1["🤲 Doa Penyucian Harta & Pahala ('آجَرَكَ اللهُ فِيْمَا أَعْطَيْتَ...')"]
    RandomSelect -- "Variasi 2" --> Doa2["🤲 Doa Keberkahan Kelipatan Rezeki ('اللَّهُمَّ أَعْطِ مُنْفِقًا خَلَفًا...')"]
    RandomSelect -- "Variasi 3" --> Doa3["🤲 Doa Kemudahan Urusan & Kebahagiaan Keluarga"]
    RandomSelect -- "Variasi 4" --> Doa4["🤲 Doa Perlindungan & Kesucian Rezeki"]

    Doa1 --> FormatFinal["✨ Gabungkan Teks Terjemahan, Nama Donatur & Nominal"]
    Doa2 --> FormatFinal
    Doa3 --> FormatFinal
    Doa4 --> FormatFinal

    FormatFinal --> SendDoaWA["🚀 Kirim Pesan Doa Syar'i ke WhatsApp Pengguna"]
```

---

## ⚡ 5. Fast-Path Router Bahasa Santai, Typo-Tolerant & Priority Engine (0.001s)

Diagram alur keputusan Fast-Path instan untuk menangkap sapaan gaul, typo, dan prioritas PINTAS di atas BPRA-UKT:

```mermaid
flowchart TD
    IncomingMsg["📩 Pesan Teks Diterima (Status: IDLE)"] --> FastCheck{"⚡ Jalur Fast-Path (0.001s)"}

    FastCheck -- "oi lek / woi / p / halo / hai / assalamualaikum" --> ResSapaan["👋 Balas Menu Utama Sapaan Instant"]
    FastCheck -- "pintas / meminjam / pinjam uang" --> ResPintas["💸 Balas Detail PINTAS + Opsi Handoff Admin (Priority Over UKT)"]
    FastCheck -- "info beasiswa / beasiswa apa saja" --> ResBeasiswa["🎓 Balas Katalog Beasiswa Resmi USK"]
    FastCheck -- "kurang dana ukt / bpra ukt" --> ResUKT["📚 Balas Detail Program BPRA-UKT & QnA"]
    FastCheck -- "rumah amal letaknya dimana / gmaps" --> ResAlamat["📍 Balas Alamat Kantor (Lantai 1 Masjid Jamik USK)"]
    FastCheck -- "jam kerja / buka jam berapa" --> ResJam["⏰ Balas Jam Operasional (Senin-Jumat 08.00-16.30 WIB)"]
    FastCheck -- "rekening bsi / norek" --> ResRek["🏦 Balas Rekening BSI 7099400409 a.n. Rumah Amal Mesjid Unsyiah"]
    FastCheck -- "liat riwayat / riawayat / riwayat donasi" --> ResRiwayat["📜 Balas Riwayat Donasi Terakhir (Typo-Tolerant)"]

    ResSapaan --> FinishFast["✅ Kirim Balasan WA Instan (0.001s)"]
    ResPintas --> FinishFast
    ResBeasiswa --> FinishFast
    ResUKT --> FinishFast
    ResAlamat --> FinishFast
    ResJam --> FinishFast
    ResRek --> FinishFast
    ResRiwayat --> FinishFast

    FastCheck -- "Pertanyaan Kompleks / Bebas (Tidak Kena Keyword)" --> LLMRoute["☁️ Gemini Hanya Klasifikasi Intent (Bukan Menyusun Jawaban) -> Balas dari QA_SCRIPT Statis"]
    FastCheck -- "Pertanyaan OOT / Iseng" --> ResOOT["😊 Balas Jawaban Penolakan OOT Ramah + Navigasi Cepat"]
```

---

## 🧭 6. Evolusi Arsitektur AI (Ollama Lokal -> Cloud -> Optimasi Kuota)

Pemilihan mesin AI pada proyek ini melewati 3 fase, masing-masing dipicu oleh temuan nyata di lapangan - bukan keputusan sekali jalan yang tidak pernah dievaluasi ulang:

```mermaid
flowchart LR
    subgraph Fase1 ["📍 Fase 1: Model Lokal (11 Agustus)"]
        Ollama["🖥️ Ollama Self-Hosted qwen2.5:7b (host.docker.internal:11434)"]
    end

    subgraph Fase2 ["📍 Fase 2: Migrasi Cloud (12-14 Agustus)"]
        Gemini1["☁️ Gemini 2.5 Flash - dipakai untuk SEMUA tugas: Klasifikasi, NER, Parafrase Q&A, Vision OCR"]
    end

    subgraph Fase3 ["📍 Fase 3: Optimasi Kuota (15 Agustus)"]
        Gemini2["☁️ Gemini 2.5 Flash - dipakai HANYA untuk Klasifikasi Intent Fallback, NER & Vision OCR"]
        Static["📄 QA_SCRIPT Statis (Jawaban Q&A Langsung, Tanpa Parafrase LLM)"]
    end

    Ollama -->|"cloud api migration"| Gemini1
    Gemini1 -->|"Ditemukan: kuota free-tier cuma 20 request/hari/model - parafrase Q&A memakai kuota untuk hal yang tidak butuh kecerdasan"| Gemini2
    Gemini2 --> Static
```

---

## 🌟 Ringkasan Fitur Unggulan Sistem

1. **Katalog Program Pilihan C (Gabungan):**
   - **1 s.d 5 (Mahasiswa):** `🎓 PINTAS`, `📚 BPRA-UKT`, `👨‍👩‍👧 OTA`, `🌙 Muallaf`, `💼 BPMI`.
   - **6 s.d 10 (Sosial):** `🇵🇸 OTA Palestina`, `🥩 Green Qurban`, `🍱 Nasi Bungkus`, `🚀 ECRA`, `🏦 P2EMD`.

2. **Random Doa Syar'i Generator:**
   - 4 Variasi Doa Syar'i (Lafadz Arab + Terjemahan + Doa Keberkahan) yang berganti-ganti secara acak saat donatur berdonasi.

3. **Dual-write SQLite + Supabase Cloud saat transaksi terjadi:**
   - Tiap transaksi ditulis ke SQLite lokal dan Supabase Cloud secara bersamaan (kalau Supabase dikonfigurasi). Catatan: fungsi *catch-up sync* untuk transaksi yang sempat gagal ke Supabase (`sync_offline_sqlite_to_supabase`) sudah ada di kode tapi belum dijadwalkan berjalan otomatis - lihat catatan internal.

4. **WAHA Session Health Monitor & Rate Limiter:**
   - Peringatan otomatis ke Admin WA jika WhatsApp bot terputus + Proteksi anti-spam (Max 20 req/min per WA).

5. **HD Media Downloader (>30KB Threshold):**
   - Memaksa WAHA mengunduh foto resi asli beresolusi tinggi (HD > 30KB) dari HP pengirim.

6. **Hemat Kuota Cloud AI (Q&A Tanpa Parafrase LLM):**
   - Jawaban Q&A dikirim langsung dari template statis (`QA_SCRIPT`) tanpa disusun ulang oleh Gemini - LLM hanya dipakai untuk hal yang benar-benar butuh pemahaman bebas: klasifikasi intent fallback, ekstraksi NER, dan OCR resi. Memangkas jumlah panggilan Gemini per pertanyaan secara signifikan tanpa mengubah kualitas jawaban.

---

## 🗂️ 7. Tiga Titik Akses Sistem

| Titik Akses | Route | Untuk Siapa | Status |
|---|---|---|---|
| Bot WhatsApp | Webhook `/webhook` (dipanggil WAHA) | Donatur, lewat WhatsApp | Teruji lewat pemakaian nyata |
| Admin Dashboard | `/admin/login`, `/admin/dashboard`, `/admin/transactions` | Staf Rumah Amal (internal) | Baru dibangun - data masih contoh, lihat catatan internal |
| Web Chatbot Publik | `/` (halaman chat), `/api/web-chat`, `/api/web-otp/*`, `/api/web-chat/upload-resi` | Pengunjung website (publik) | Baru dibangun - tersambung ke mesin jawaban bot asli, belum ada pembatas anti-spam |
| Health Check | `/health` | Pemantauan server | - |

Web Chatbot Publik memakai mesin jawaban (`susun_balasan`) yang **sama persis** dengan Bot WhatsApp, jadi jawaban untuk pertanyaan yang sama akan konsisten di kedua kanal. Fitur "Cek Riwayat Transaksi" di kanal web mewajibkan verifikasi kode OTP yang dikirim ke WhatsApp asli pengguna terlebih dulu, demi menjaga data donasi tidak bisa diintip sembarang orang.

---

## ⚙️ Pengaturan Environment (`.env`)

```env
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-supabase-anon-key

WAHA_ENDPOINT=http://waha-gateway:3000
WAHA_API_KEY=your-waha-api-key

GEMINI_API_KEY=your-gemini-api-key
MODEL_NAME=gemini-2.5-flash

ADMIN_WA_NUMBER=6281269666776@c.us

# Login Admin Dashboard (/admin) - wajib diisi ADMIN_DASHBOARD_PASSWORD sebelum deploy
ADMIN_DASHBOARD_USERNAME=admin
ADMIN_DASHBOARD_PASSWORD=your-strong-password-here
```

---

## 🚀 Panduan Deployment Docker

```bash
docker compose up -d --build
```

---

## 🤝 Lisensi & Hak Cipta
Dikembangkan untuk **Rumah Amal Masjid Jamik Universitas Syiah Kuala (USK)**.
