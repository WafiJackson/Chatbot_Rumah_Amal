# 🤖 Bot WhatsApp Rumah Amal USK (Hybrid & Cloud AI Engine)

Sistem Bot WhatsApp cerdas, ter-modularisasi, dan berkemampuan hibrida (*Fast-Path Regex + State Machine + Google Gemini 2.5 Flash Cloud AI + AI Vision OCR + Supabase Cloud*) yang dibangun khusus untuk melayani informasi program, penyaluran donasi/zakat, permohonan bantuan (PINTAS/BPRA-UKT), cek riwayat transaksi, deteksi sapaan gender dinamis, generator doa syar'i acak, dan notifikasi *alert* otomatis ke Admin Rumah Amal Masjid Jamik USK.

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
        GeminiAPI["☁️ Google Gemini 2.5 Flash API (NLU, Q&A & NER)"]
        DoaGen["🤲 Random Doa Syar'i Generator (4 Variasi Doa Arab & Terjemahan)"]
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
    FastPath -->|"Pertanyaan Bebas (Q&A)"| GeminiAPI
    GeminiAPI --> Guardrail
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

## 🤲 3. Random Doa Syar'i Generator Engine (`admin_scripts.py`)

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

## ⚡ 4. Fast-Path Router Bahasa Santai, Typo-Tolerant & Priority Engine (0.001s)

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

    FastCheck -- "Pertanyaan Kompleks / Bebas" --> LLMRoute["☁️ Teruskan ke Google Gemini 2.5 Flash Cloud API"]
    FastCheck -- "Pertanyaan OOT / Iseng" --> ResOOT["😊 Balas Jawaban Penolakan OOT Ramah + Navigasi Cepat"]
```

---

## 🌟 Ringkasan Fitur Unggulan Sistem

1. **Katalog Program Pilihan C (Gabungan):**
   - **1 s.d 5 (Mahasiswa):** `🎓 PINTAS`, `📚 BPRA-UKT`, `👨‍👩‍👧 OTA`, `🌙 Muallaf`, `💼 BPMI`.
   - **6 s.d 10 (Sosial):** `🇵🇸 OTA Palestina`, `🥩 Green Qurban`, `🍱 Nasi Bungkus`, `🚀 ECRA`, `🏦 P2EMD`.

2. **Random Doa Syar'i Generator:**
   - 4 Variasi Doa Syar'i (Lafadz Arab + Terjemahan + Doa Keberkahan) yang berganti-ganti secara acak saat donatur berdonasi.

3. **Background Auto-Sync SQLite $\rightarrow$ Supabase Cloud:**
   - Mengunggah ulang transaksi offline SQLite ke Supabase Cloud saat jaringan pulih.

4. **WAHA Session Health Monitor & Rate Limiter:**
   - Peringatan otomatis ke Admin WA jika WhatsApp bot terputus + Proteksi anti-spam (Max 20 req/min per WA).

5. **HD Media Downloader (>30KB Threshold):**
   - Memaksa WAHA mengunduh foto resi asli beresolusi tinggi (HD > 30KB) dari HP pengirim.

---

## ⚙️ Pengaturan Environment (`.env`)

```env
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-supabase-anon-key

WAHA_ENDPOINT=http://waha-gateway:3000
WAHA_API_KEY=amalmaximal123

GEMINI_API_KEY=your-gemini-api-key
MODEL_NAME=gemini-2.5-flash

ADMIN_WA_NUMBER=6281269666776@c.us
```

---

## 🚀 Panduan Deployment Docker

```bash
docker compose up -d --build
```

---

## 🤝 Lisensi & Hak Cipta
Dikembangkan untuk **Rumah Amal Masjid Jamik Universitas Syiah Kuala (USK)**.
