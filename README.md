# 🤖 Bot WhatsApp Rumah Amal USK (Hybrid & Cloud AI Engine)

Sistem Bot WhatsApp cerdas, ter-modularisasi, dan berkemampuan hibrida (*Fast-Path Regex + State Machine + Google Gemini 2.5 Flash Cloud AI + AI Vision OCR + Supabase Cloud*) yang dibangun khusus untuk melayani informasi program, penyaluran donasi/zakat, permohonan bantuan (PINTAS/BPRA-UKT), cek riwayat transaksi, deteksi sapaan gender dinamis, dan notifikasi *alert* otomatis ke Admin Rumah Amal Masjid Jamik USK.

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
        GenderEngine["👤 Gender Detector Engine (Bapak/Ibu/Kak)"]
        MediaDecoder["🖼️ Base64 & Media URL Image Downloader"]
        LIDResolver["🔍 LID & Contact Resolver (LID -> Phone Number & Name)"]
        FastPath["⚡ Fast-Path Intent Router (0.001s Regex & Typo-Tolerant)"]
    end

    subgraph State_Layer ["💾 State Machine & Dual Storage Engine"]
        FSM["🔄 Finite State Machine (IDLE / TANYA_PROGRAM / PILIH_PROGRAM / MENUNGGU_ADMIN / NUNGGU_BUKTI_TRANSFER)"]
        SQLiteDB[("💾 Local SQLite DB (donatur.db in Docker Volume)")]
        SupabaseDB[("☁️ Supabase Cloud DB (transaksi_donasi & master_program)")]
    end

    subgraph AI_Layer ["🧠 Google Gemini Cloud AI Layer (Zero VPS Load)"]
        GeminiAPI["☁️ Google Gemini 2.5 Flash API (NLU, Q&A & NER)"]
        Guardrail["🛡️ Anti-Hallucination Guardrail Verifier"]
        VisionOCR["👁️ Multimodal Vision OCR (Resi BSI Mobile & BYOND Reader)"]
    end

    subgraph Log_Layer ["📝 Logging & Observability Layer"]
        ProdLogger["📊 Production Logger (RotatingFileHandler -> logs/app.log)"]
    end

    User -->|"1. Kirim Pesan / Resi / Panggilan"| WAHA
    WAHA -->|"2. HTTP POST Webhook Payload"| Router
    Router --> AuthCheck
    AuthCheck --> Deduplication
    Deduplication --> MediaDecoder
    MediaDecoder --> LIDResolver
    LIDResolver --> GenderEngine
    GenderEngine --> FastPath

    FastPath -->|"Cek Status Sesi & State"| FSM
    FSM <-->|"Sync Status Sesi"| SQLiteDB
    FSM <-->|"Sync Transaksi & Master Program"| SupabaseDB

    FastPath -->|"Foto Resi (Media)"| VisionOCR
    FastPath -->|"Pertanyaan Bebas (Q&A)"| GeminiAPI
    GeminiAPI --> Guardrail

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
        [*] --> Katalog10Program
        Katalog10Program --> DetailProgram : Ketik 1 s.d. 10
        Katalog10Program --> IDLE : Ketik 0 (Kembali ke Menu Utama)
        DetailProgram --> Katalog10Program : Ketik 11 (Kembali ke Daftar Program)
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
    SaveSuccess --> IDLE : Simpan ke Supabase & Reset
    RetryReceipt --> NUNGGU_BUKTI_TRANSFER : Minta Ulang Resi
```

---

## 👤 3. Engine Deteksi Gender & Normalisasi Sapaan (`gender_detector.py`)

Diagram alur berikut menjelaskan bagaimana sistem membersihkan nama profil WhatsApp (`pushname`) donatur dan menentukan sapaan **Bapak**, **Ibu**, atau **Kak** secara presisi:

```mermaid
flowchart TD
    StartGender["👤 Terima Nama Pengirim (Pushname WA)"] --> Transliterate["🔤 Unicode NFKD Transliteration (À -> A, é -> e)"]
    Transliterate --> CleanRegex["🧹 Clean Non-Alphabet & Emoji (Simpan Huruf & Spasi)"]
    CleanRegex --> Unspacing["🔗 Unspacing Single Letters (N O V À L ☕️ -> NOVAL)"]
    Unspacing --> Lowercase["🔤 Convert to Lowercase Tokens"]

    Lowercase --> WordMatch{"🔍 Match Kata Kunci (Pria / Wanita)?"}
    WordMatch -- "Match PRIA_KEYWORDS (Yafi, Noval, Teuku, M, etc)" --> SetBapak["👨 Set Sapaan: 'Bapak'"]
    WordMatch -- "Match WANITA_KEYWORDS (Cut, Dara, Siti, Aisyah, etc)" --> SetIbu["👩 Set Sapaan: 'Ibu'"]

    WordMatch -- "Tidak Match" --> SubstringMatch{"🔍 Match Substring / Suffix?"}
    SubstringMatch -- "Contains: hidayat, syahputra, pratama, etc / Suffix: wan, syah" --> SetBapak
    SubstringMatch -- "Contains: fadhilah, zahrani, nisa, etc / Suffix: wati, sari" --> SetIbu
    SubstringMatch -- "Low Confidence / Ambigu / Emoji Murni" --> SetKak["👥 Set Fallback Safety Net: 'Kak'"]

    SetBapak --> FormatSalutation["✨ Format Sapaan: 'Bapak [Nama]' / 'Bapak'"]
    SetIbu --> FormatSalutation["✨ Format Sapaan: 'Ibu [Nama]' / 'Ibu'"]
    SetKak --> FormatSalutation["✨ Format Sapaan: 'Bapak/Ibu [Nama]' / 'Kak'"]

    FormatSalutation --> ApplyAll["🚀 Terapkan ke Seluruh Balasan Bot (Bicara Konsisten)"]
```

---

## ⚡ 4. Fast-Path Router Bahasa Santai / Nyeleneh / Sapaan Gaul (0.001 Detik)

Diagram alur keputusan Fast-Path instan untuk menangkap pertanyaan santai/nyeleneh & sapaan gaul tanpa tergantung pada server LLM:

```mermaid
flowchart TD
    IncomingMsg["📩 Pesan Teks Diterima (Status: IDLE)"] --> FastCheck{"⚡ Jalur Fast-Path (0.001s)"}

    FastCheck -- "oi lek / woi / p / halo / hai / assalamualaikum" --> ResSapaan["👋 Balas Menu Utama Sapaan Instant"]
    FastCheck -- "rumah amal letaknya dimana / gmaps" --> ResAlamat["📍 Balas Alamat Kantor (Lantai 1 Masjid Jamik USK)"]
    FastCheck -- "info beasiswa / beasiswa apa saja" --> ResBeasiswa["🎓 Balas Katalog 4 Beasiswa Resmi USK"]
    FastCheck -- "kurang dana ukt / bayar ukt / bpra" --> ResUKT["📚 Balas Detail Program BPRA-UKT & Opsional Admin"]
    FastCheck -- "meminjam uang / pintas / pinjam" --> ResPintas["💸 Balas Detail Program PINTAS & Opsional Admin"]
    FastCheck -- "jam kerja / buka jam berapa" --> ResJam["⏰ Balas Jam Operasional (Senin-Jumat 08.00-16.30 WIB)"]
    FastCheck -- "rekening bsi / norek" --> ResRek["🏦 Balas Rekening BSI 7099400409 a.n. Rumah Amal Mesjid Unsyiah"]
    FastCheck -- "liat riwayat / riwayat donasi / Ketik 4" --> ResRiwayat["📜 Balas Riwayat Donasi Terakhir (Supabase Cloud / SQLite)"]

    ResSapaan --> FinishFast["✅ Kirim Balasan WA Instan (0.001s)"]
    ResAlamat --> FinishFast
    ResBeasiswa --> FinishFast
    ResUKT --> FinishFast
    ResPintas --> FinishFast
    ResJam --> FinishFast
    ResRek --> FinishFast
    ResRiwayat --> FinishFast

    FastCheck -- "Pertanyaan Kompleks / Bebas" --> LLMRoute["☁️ Teruskan ke Google Gemini 2.5 Flash Cloud API"]
```

---

## 📜 5. Alur Cek Riwayat Transaksi Donasi Berbasis Nomor WA

Diagram alur berikut menjelaskan bagaimana fitur Cek Riwayat Transaksi bekerja secara aman berbasis nomor WhatsApp pengirim:

```mermaid
flowchart TD
    UserReq["📜 Pengguna Memilih Menu 4 / Ketik 'liat riwayat'"] --> GetPhone["📱 Ekstrak Nomor HP Real via LID Resolver"]
    GetPhone --> QuerySupabase["☁️ Query DB Supabase / SQLite (transaksi_donasi WHERE no_wa = phone)"]
    QuerySupabase --> CheckData{"📊 Data Transaksi Ditemukan?"}

    CheckData -- "Ada Transaksi" --> FormatHistory["✨ Format List Transaksi (Tanggal | Nominal | Program | Status)"]
    FormatHistory --> SumTotal["💰 Hitung Akumulasi Total Penyaluran Donasi"]
    SumTotal --> SendHistory["💬 Kirim Balasan Riwayat Transaksi + Doa Spesifik"]

    CheckData -- "Kosong" --> SendEmpty["Mohon maaf, Mimin belum menemukan riwayat transaksi donasi... Yuk donasi pertama!"]

    SendHistory --> FinishRiwayat["✅ Reset State ke IDLE"]
    SendEmpty --> FinishRiwayat
```

---

## 📸 6. Alur Pemrosesan Resi & Multimodal Vision OCR (`Gemini 2.5 Flash`)

Diagram urutan berikut menjelaskan alur pemrosesan foto resi transfer BSI Mobile / BYOND dari donatur hingga pencatatan ke database:

```mermaid
flowchart TD
    StartResi["📸 Donatur Mengirim Foto Resi (BSI Mobile / BYOND)"] --> DownloadImg["📥 WAHA HTTP Downloader (Headers: X-Api-Key)"]
    DownloadImg --> ExecOCR["👁️ Ekstraksi Multimodal Vision (Google Gemini 2.5 Flash API)"]
    ExecOCR --> CheckNominal{"🔍 Nominal & Data Terbaca?"}

    CheckNominal -- "Ya (Sukses)" --> SaveSupabase["☁️ Simpan Transaksi Donasi ke Supabase Cloud / SQLite"]
    SaveSupabase --> ResetFSM["🔄 Reset Status Pengguna ke IDLE"]
    ResetFSM --> SendDoa["🙏 Kirim Pesan Terimakasih & Doa Spesifik Program"]
    SendDoa --> EndSuccess["✅ Alur Resi Selesai"]

    CheckNominal -- "Tidak / Gambar Buram" --> PromptRetry["⚠️ Kirim Pesan: Gambar kurang terbaca, silakan ketik manual..."]
    PromptRetry --> SetStateWait["🔄 Update State: NUNGGU_BUKTI_TRANSFER"]
    SetStateWait --> EndRetry["⏳ Menunggu Input Manual Donatur"]
```

---

## 🆘 7. Notifikasi Alert Admin & LID Resolver

Diagram urutan berikut menjelaskan alur penerjemahan ID WhatsApp Privacy (`@lid`) dan pengiriman pesan *ping* peringatan otomatis ke WhatsApp Admin (`0812-6966-6776`):

```mermaid
flowchart TD
    StartAdmin["💬 Pengguna Membalas 'Ya' pada Penawaran Admin"] --> FetchLID["🔍 Panggil LID Contact Resolver (_dapatkan_nomor_hp_asli)"]
    FetchLID --> QueryWAHA["🌐 Query GET /api/contacts/all ke WAHA Engine"]
    QueryWAHA --> MapPhone["📱 Terjemahkan ID Privacy (@lid) -> Nomor HP Real (0812...) & Nama"]
    MapPhone --> BuildAlert["✉️ Susun Pesan Alert: 🆘 [NAMA_PROGRAM] Ada permohonan dari..."]
    BuildAlert --> SendAdmin["🚀 Send Text ke WhatsApp Admin (0812-6966-6776)"]
    SendAdmin --> ConfirmUser["💬 Kirim Konfirmasi ke Pengguna: Pesan Anda sedang diteruskan ke Admin..."]
    ConfirmUser --> ResetIdle["🔄 Reset State Pengguna ke IDLE"]
    ResetIdle --> EndAdmin["✅ Alur Handoff Admin Selesai"]
```

---

## 🌟 Ringkasan Fitur Unggulan Sistem

1. **Menu Utama 5 Pilihan Bebas Tabrakan:**
   - `1. Program apa saja?` (Katalog 10 Program)
   - `2. Ingin berdonasi?` (Menu Zakat & Donasi)
   - `3. Alamat kantor?` (Lokasi Masjid Jamik USK)
   - `4. Cek riwayat transaksi` (Histori Donasi Terverifikasi)
   - `5. Hubungi admin` (Sambungkan ke Admin WA)

2. **Dua Tingkat Navigasi Program (Level 1 & Level 2):**
   - **Level 1 (Daftar Program):** Ketik `1 s.d. 10` (Pilih Program), Ketik `0` (Kembali ke Menu Utama).
   - **Level 2 (Detail Program & QNA):** Ketik `1 s.d. N` (Baca QNA), Ketik `11` (Kembali ke Daftar Program), Ketik `0` (Kembali ke Menu Utama).

3. **Gender Detector & Salutation Engine (`services/gender_detector.py`):**
   - Deteksi gender otomatis dari nama/pushname (Unicode NFKD Transliteration + Unspacing Single-Letter).
   - Menyapa **Bapak** / **Ibu** secara konsisten di seluruh layar percakapan.

4. **Fast-Path Router Bahasa Santai & Typo-Tolerant (0.001 Detik):**
   - Respon instan kilat untuk sapaan gaul (*"oi lek"*, *"woi"*), alamat (*"letaknya dimana"*), info beasiswa (*"info beasiswa"*), bantuan UKT (*"kurang dana ukt"*), pinjaman (*"meminjam uang"*), jam kerja (*"buka jam berapa"*), nomor rekening (*"norek bsi"*), dan riwayat (*"liat riwayat"*).

5. **Google Gemini 2.5 Flash Cloud AI (Zero VPS Load):**
   - Menggunakan model cloud `gemini-2.5-flash` untuk NLU, Q&A, dan Vision OCR resi transfer. Latensi super cepat (~0.3s) dan beban VPS 0%.

6. **Dual Database Sync (Supabase Cloud + Local SQLite Volume):**
   - Sinkronisasi real-time ke Supabase Cloud dengan proteksi offline fallback otomatis ke SQLite lokal (`sqlite_data` volume).

---

## ⚙️ Pengaturan Environment (`.env`)

Buat atau perbarui berkas `.env` di direktori utama proyek dengan variabel berikut:

```env
# Credentials Supabase Cloud (Opsional - Fallback ke SQLite)
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-supabase-anon-key

# WAHA WhatsApp Gateway Configuration
WAHA_ENDPOINT=http://waha-gateway:3000
WAHA_API_KEY=amalmaximal123

# Google Gemini Cloud AI API Key
GEMINI_API_KEY=your-gemini-api-key-from-google-ai-studio
MODEL_NAME=gemini-2.5-flash

# Nomor WhatsApp Admin Penerima Notifikasi Alert
ADMIN_WA_NUMBER=6281269666776@c.us
```

---

## 🚀 Panduan Jalankan & Local Docker Deployment

### Jalankan Komplit via Docker Compose (Rekomendasi Utama)
```bash
docker compose up -d --build
```

- **Dashboard WAHA:** `http://localhost:3000` (Scan QR Code)
- **FastAPI Bot Webhook:** `http://localhost:8000/webhook`

---

## 🧪 Pengujian Otomatis (Test Suite)

Skrip pengujian otomatis komprehensif untuk memverifikasi seluruh alur tanpa error:

```bash
python test_hybrid.py
```

---

## 📂 Struktur Folder Proyek

```text
bot-rumah-amal/
├── Dockerfile               # Konfigurasi container Docker FastAPI
├── docker-compose.yml       # Production stack (api-bot + waha-gateway + volumes)
├── .env                     # File konfigurasi rahasia (API Key & Supabase)
├── .env.example             # Template file environment
├── README.md                # Dokumentasi arsitektur & panduan sistem lengkap
└── app/
    ├── main.py              # Entry point FastAPI & route listener
    ├── admin_scripts.py     # Skrip fakta resmi & matcher intent
    ├── routes/
    │   └── bot_webhook.py   # Handler webhook WAHA, FSM, & router utama
    └── services/
        ├── gender_detector.py # Engine deteksi gender (Bapak/Ibu/Kak)
        ├── logger.py          # Production logger (RotatingFileHandler)
        ├── program_manager.py # Pengelola 10 data resmi program Rumah Amal
        ├── state_manager.py   # Pengelola FSM State (SQLite + Supabase sync)
        ├── supabase_client.py # Client Supabase & PostgREST fallback
        ├── form_parser.py     # Parser regex formulir donasi
        └── llm_agent.py       # Client Google Gemini 2.5 Flash API & Vision OCR
```

---

## 🤝 Lisensi & Hak Cipta
Dikembangkan untuk **Rumah Amal Masjid Jamik Universitas Syiah Kuala (USK)**.
