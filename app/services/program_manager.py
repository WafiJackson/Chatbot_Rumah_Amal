# ==========================================
# PROGRAM MANAGER - Data & Logic Program Rumah Amal
# ==========================================

import difflib
import re
from functools import lru_cache

# Database Program resmi disesuaikan dengan "Buku Saku Program Fundraising
# Rumah Amal Mesjid Jamik USK - 13 Program Kebaikan" (diperbarui 20 Sep 2026).
PROGRAMS = {
    "senyum_ramadhan": {
        "nama": "PAKET SENYUM RAMADHAN",
        "deskripsi": "Program penyaluran paket sembako kepada masyarakat tidak mampu di sekitar kawasan USK maupun lokasi terdampak, untuk membantu memenuhi kebutuhan pokok keluarga penerima manfaat, khususnya pada bulan Ramadhan dan Hari Raya Idul Fitri.",
        "syarat": [
            "Masyarakat tidak mampu di sekitar kawasan USK atau lokasi terdampak bencana",
            "Diprioritaskan pada periode Ramadhan dan Hari Raya Idul Fitri"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": []
    },
    "ota_beasiswa": {
        "nama": "BEASISWA ORANG TUA ASUH (OTA)",
        "deskripsi": "Program beasiswa unggulan berupa bantuan biaya pendidikan setiap bulan selama satu tahun untuk mahasiswa/i jenjang DIII/S1 USK yang berasal dari keluarga kurang mampu dan berprestasi, dengan sumber dana dari donatur khusus yang menjadi \"Orang Tua Asuh\".",
        "syarat": [
            "Mahasiswa berprestasi namun kurang mampu",
            "Bersedia memberikan laporan perkembangan studi kepada donatur"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": [
            {
                "tanya": "Bagaimana sistem skema beasiswa Orang Tua Asuh (OTA)?",
                "jawab": "Donatur (Orang Tua Asuh) memberikan bantuan beasiswa rutin untuk mendukung keberlangsungan studi mahasiswa dhuafa berprestasi di USK.",
                "kata_kunci": ["sistem", "skema"]
            }
        ]
    },
    "ota_palestina": {
        "nama": "BEASISWA ORANG TUA ASUH (OTA) PALESTINA",
        "deskripsi": "Program beasiswa unggulan berupa bantuan biaya pendidikan setiap bulan selama satu tahun untuk mahasiswa/i jenjang S1/S2 USK yang berasal dari Palestina, guna meringankan beban pendidikan selama menempuh studi di USK.",
        "syarat": [
            "Mahasiswa berpaspor/berasal dari Palestina",
            "Terdaftar sebagai mahasiswa aktif di USK"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": [
            {
                "tanya": "Apakah Rumah Amal menggalang bantuan khusus untuk mahasiswa Palestina?",
                "jawab": "Ya, Rumah Amal mengelola skema beasiswa dan bantuan biaya hidup khusus solidaritas global untuk mahasiswa asal Palestina di USK.",
                "kata_kunci": ["menggalang", "galang dana", "galang bantuan"]
            }
        ]
    },
    "pintas": {
        "nama": "PINTAS (Pinjaman Tanpa Syarat)",
        "deskripsi": "Bantuan berupa pemberian dana dalam bentuk pinjaman tanpa imbalan dengan akad qardhul hasan kepada mahasiswa jenjang D3/S1/Profesi/Pascasarjana, Pegawai, dan Dosen USK yang terdesak keuangan untuk kebutuhan hidup dan biaya pendidikan.",
        "syarat": [
            "WNI dan memiliki kartu identitas",
            "Menyerahkan form pendaftaran",
            "Bersedia mengikuti wawancara dengan admin"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": [
            {
                "tanya": "Apakah permohonan dana PINTAS wajib mengikuti sesi wawancara langsung dengan admin?",
                "jawab": "Ya, untuk pengajuan bantuan dana atau program PINTAS, proses validasi dan wawancara wajib dilakukan langsung bersama tim admin Rumah Amal.",
                "kata_kunci": ["wawancara"]
            }
        ]
    },
    "nasi_bungkus": {
        "nama": "BANTUAN NASI BUNGKUS",
        "deskripsi": "Program penyediaan makanan siap santap bagi masyarakat yang membutuhkan, mahasiswa, pekerja harian, dan warga yang terdampak kondisi darurat di sekitar Banda Aceh.",
        "syarat": [
            "Tidak ada syarat khusus",
            "Diprioritaskan bagi yang membutuhkan dalam kondisi darurat"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": [
            {
                "tanya": "Kepada siapa saja bantuan makanan/nasi bungkus ini didistribusikan?",
                "jawab": "Makanan siap santap didistribusikan kepada masyarakat yang membutuhkan, mahasiswa, pekerja harian, dan warga yang terdampak kondisi darurat di sekitar Banda Aceh.",
                "kata_kunci": ["kepada siapa", "didistribusikan", "siapa saja"]
            }
        ]
    },
    "kolaborasi_kebaikan": {
        "nama": "KOLABORASI KEBAIKAN",
        "deskripsi": "Program kerja sama Rumah Amal USK dengan lembaga mahasiswa, fakultas, komunitas dakwah, serta mitra eksternal dalam mengelola dan menyalurkan zakat, infaq, dan sedekah untuk berbagai kegiatan sosial dan keagamaan di lingkungan kampus maupun masyarakat sekitar.",
        "syarat": [
            "Lembaga mahasiswa, fakultas, komunitas dakwah, atau mitra eksternal",
            "Mengajukan kerja sama penyaluran ZIS kepada Rumah Amal USK"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": []
    },
    "rumah_tahfizh": {
        "nama": "RUMAH TAHFIZH",
        "deskripsi": "Program pembinaan dan pendampingan bagi mahasiswa penghafal Al-Qur'an yang memberikan dukungan berupa biaya hidup, tempat tinggal, serta pembinaan kepada mahasiswa penerima manfaat, berkolaborasi bersama Human Initiative (HI) Aceh.",
        "syarat": [
            "Mahasiswa aktif USK penghafal Al-Qur'an",
            "Bersedia mengikuti pembinaan dan pendampingan"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": []
    },
    "dsu_umum": {
        "nama": "DANA SOLIDARITAS UMAT (DSU) UMUM",
        "deskripsi": "Dana bantuan kemanusiaan bagi masyarakat yang mengalami kesulitan pemenuhan kebutuhan pokok (sandang, pangan, papan) akibat bencana alam maupun bencana sosial di Aceh, meliputi kebutuhan darurat seperti bahan makanan, air bersih, perlengkapan ibadah, dan kebutuhan dasar lainnya.",
        "syarat": [
            "Masyarakat terdampak bencana alam atau bencana sosial di Aceh",
            "Disalurkan secara cepat dan tepat sasaran"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": []
    },
    "dsu_palestina": {
        "nama": "DANA SOLIDARITAS UMAT (DSU) PALESTINA",
        "deskripsi": "Bagian dari Dana Solidaritas Umat yang dikhususkan sebagai bentuk kepedulian dan solidaritas kemanusiaan Rumah Amal USK bagi rakyat Palestina yang terdampak konflik.",
        "syarat": [
            "Disalurkan khusus untuk kebutuhan kemanusiaan rakyat Palestina"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": []
    },
    "tabungan_qurban": {
        "nama": "TABUNGAN QURBAN",
        "deskripsi": "Program menabung secara berkala dalam jangka waktu tertentu untuk mengumpulkan dana yang cukup guna membeli hewan qurban seperti sapi, kambing, atau domba, sehingga ibadah qurban lebih ringan dan terencana. Tersedia pula paket Qurban 1 Sapi untuk lembaga, patungan keluarga, atau komunitas.",
        "syarat": [
            "Terbuka bagi siapa saja yang ingin menabung atau berqurban",
            "Dapat dilakukan perorangan maupun patungan/lembaga"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": [
            {
                "tanya": "Bagaimana sistem penyaluran hewan/daging kurban di Rumah Amal USK?",
                "jawab": "Rumah Amal menerima titipan hewan/donasi kurban lewat Tabungan Qurban, mengelola pemotongan, dan menyalurkan kupon daging kurban secara merata kepada masyarakat serta mahasiswa kurang mampu.",
                "kata_kunci": ["penyaluran", "daging kurban", "hewan kurban"]
            }
        ]
    },
    "infaq_bebas": {
        "nama": "INFAQ BEBAS",
        "deskripsi": "Sarana bagi muzakki dan donatur untuk menyalurkan infaq tanpa peruntukan khusus, sehingga dananya dapat dialokasikan secara fleksibel oleh Rumah Amal USK untuk program-program yang paling membutuhkan.",
        "syarat": [
            "Tidak ada syarat khusus, terbuka bagi siapa saja"
        ],
        "proses": "Dapat disalurkan langsung melalui rekening resmi atau scan QRIS Rumah Amal USK.",
        "qna": []
    },
    "peduli_yatim": {
        "nama": "PEDULI YATIM",
        "deskripsi": "Program santunan anak yatim berupa bantuan uang tunai atau paket sembako, ditujukan bagi anak-anak yang kehilangan orang tua agar dapat hidup dengan lebih baik.",
        "syarat": [
            "Anak yatim yang membutuhkan bantuan",
            "Diverifikasi oleh tim Rumah Amal USK"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": []
    },
    "peduli_sigra": {
        "nama": "PEDULI SIGRA",
        "deskripsi": "Program penyaluran paket sembako atau bantuan berupa uang tunai untuk mendukung mahasiswa maupun masyarakat yang berada dalam kondisi serba terbatas di lingkungan Universitas Syiah Kuala (USK), Kota Banda Aceh, dan Kabupaten Aceh Besar.",
        "syarat": [
            "Mahasiswa atau masyarakat dalam kondisi ekonomi terbatas",
            "Berada di lingkungan USK, Kota Banda Aceh, atau Kabupaten Aceh Besar"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": []
    }
}

PROGRAM_ALIASES = {
    "pinjaman tanpa syarat": "pintas",
    "pinjaman": "pintas",
    "palestina": "ota_palestina",
    "qurban": "tabungan_qurban",
    "tabungan qurban": "tabungan_qurban",
    "green qurban": "tabungan_qurban",
    "nasi": "nasi_bungkus",
    "nasi bungkus": "nasi_bungkus",
    "jumat berkah": "nasi_bungkus",
    "orang tua asuh": "ota_beasiswa",
    "ota": "ota_beasiswa",
    "senyum ramadhan": "senyum_ramadhan",
    "paket senyum ramadhan": "senyum_ramadhan",
    "kolaborasi kebaikan": "kolaborasi_kebaikan",
    "tahfizh": "rumah_tahfizh",
    "rumah tahfizh": "rumah_tahfizh",
    "dsu palestina": "dsu_palestina",
    "dana solidaritas umat palestina": "dsu_palestina",
    "dsu": "dsu_umum",
    "dana solidaritas umat": "dsu_umum",
    "infaq bebas": "infaq_bebas",
    "infak bebas": "infaq_bebas",
    "peduli yatim": "peduli_yatim",
    "yatim": "peduli_yatim",
    "sigra": "peduli_sigra",
    "peduli sigra": "peduli_sigra"
}


# Urutan nomor di katalog get_program_list() - SATU sumber kebenaran untuk
# semua tempat yang menerjemahkan balasan angka ("3") jadi program: menu
# bernomor WhatsApp (bot_webhook.py) dan web chat (public_web.py).
URUTAN_KATALOG = [
    "ota_beasiswa", "ota_palestina", "pintas", "senyum_ramadhan", "nasi_bungkus",
    "dsu_umum", "dsu_palestina", "peduli_sigra", "peduli_yatim",
    "kolaborasi_kebaikan", "rumah_tahfizh", "tabungan_qurban", "infaq_bebas",
]


def kunci_program_dari_nomor(nomor: str) -> str | None:
    """'1'..'13' (boleh diakhiri titik) -> kunci program sesuai urutan katalog."""
    cocok = re.fullmatch(r"\s*(\d{1,2})\s*\.?\s*", nomor or "")
    if not cocok:
        return None
    idx = int(cocok.group(1)) - 1
    return URUTAN_KATALOG[idx] if 0 <= idx < len(URUTAN_KATALOG) else None


def kueri_untuk_program(kunci: str) -> str:
    """Kalimat tanya yang PASTI dikenali extract_program_keyword() sebagai
    program `kunci` - dipakai web chat untuk menerjemahkan balasan angka dari
    katalog. Alias terpanjang dipilih supaya tidak tertelan alias lain yang
    lebih pendek (mis. "dana solidaritas umat" menelan versi Palestinanya)."""
    alias = max((a for a, k in PROGRAM_ALIASES.items() if k == kunci), key=len, default=kunci)
    return f"apa itu {alias}"


def _contains_keyword(text: str, keyword: str) -> bool:
    """
    Pencocokan aman berbasis batas kata.
    Mencegah false positive seperti `nasi` yang terbaca dari kata `donasi`.
    """
    text = (text or "").lower()
    keyword = (keyword or "").lower().strip()
    if not keyword:
        return False
    pattern = r"(?<!\w)" + re.escape(keyword) + r"(?!\w)"
    return re.search(pattern, text) is not None


# Pasangan ejaan transliterasi Arab-Indonesia yang lazim ditulis berbeda-beda
# oleh donatur: tahfizh/tahfidz/tahfiz, qurban/kurban, infaq/infak,
# shadaqah/sadaqah, mu'allaf/muallaf. Donatur mayoritas orang dewasa yang
# menulis apa adanya - satu huruf beda seharusnya tidak membuat bot gagal
# paham (diminta 21 Sep 2026 setelah "rumah tahfiz" tanpa h tidak dikenali).
_EJAAN_VARIAN = [
    ("dz", "z"), ("zh", "z"), ("dh", "d"), ("kh", "h"),
    ("sy", "s"), ("sh", "s"), ("ts", "s"), ("ph", "f"),
    ("v", "f"), ("q", "k"), ("x", "ks"),
]

# Kata informal sehari-hari -> bentuk bakunya, diganti per KATA UTUH (bukan
# potongan kata) sebelum aturan ejaan di atas. Karena dipakai di KEDUA sisi
# pencocokan (pesan user & daftar kata kunci), aman selama tiap pasangan
# memang bermakna sama. Sengaja tidak memasukkan kata negasi (ga/gak/nggak)
# karena dipakai terpisah di alur konfirmasi Ya/Batal.
_KATA_INFORMAL = {
    "aja": "saja", "ajah": "saja",
    "pinjem": "pinjam", "minjem": "pinjam", "minjam": "pinjam",
    "duit": "uang", "doku": "uang",
    "pengen": "ingin", "pingin": "ingin", "pengin": "ingin", "pgn": "ingin",
    "mo": "mau", "mw": "mau",
    "gimana": "bagaimana", "gmn": "bagaimana", "gmna": "bagaimana",
    "brp": "berapa", "brapa": "berapa",
    "yg": "yang", "dgn": "dengan", "utk": "untuk", "untk": "untuk",
    "kalo": "kalau", "klo": "kalau", "kl": "kalau",
    "udah": "sudah", "udh": "sudah", "sdh": "sudah",
    "blm": "belum", "tau": "tahu", "apaan": "apa",
    "sy": "saya", "trf": "transfer", "tf": "transfer",
    "rek": "rekening", "prog": "program", "progam": "program",
}


@lru_cache(maxsize=4096)
def normalisasi_ejaan(teks: str) -> str:
    """Bentuk 'kanonik' sebuah kata supaya varian ejaan yang bunyinya sama
    jatuh ke tulisan yang sama. Hanya untuk PENCOCOKAN kata kunci - jangan
    dipakai untuk teks yang ditampilkan ke user atau untuk ekstraksi angka
    (huruf dobel dirapatkan, angka sengaja tidak disentuh)."""
    teks = (teks or "").lower()
    teks = re.sub(r"[^a-z0-9\s]", " ", teks)
    teks = " ".join(_KATA_INFORMAL.get(kata, kata) for kata in teks.split())
    for asal, ganti in _EJAAN_VARIAN:
        teks = teks.replace(asal, ganti)
    # Huruf dobel -> tunggal ("sunnah" -> "sunah", "qurbaan" -> "kurban").
    # Sengaja hanya huruf: angka dobel pada nominal TIDAK boleh ikut hilang.
    teks = re.sub(r"([a-z])\1+", r"\1", teks)
    return re.sub(r"\s+", " ", teks).strip()


# Alias yang lebih pendek dari ini tidak ikut pencocokan mirip-mirip -
# kata pendek terlalu gampang mirip dengan kata lain yang maksudnya beda.
_MIN_PANJANG_FUZZY = 5
# 0.86, bukan lebih rendah: satu huruf beda pada kata 6 huruf skornya 0.83,
# dan "korban" (bencana) vs "kurban" (qurban) persis kasus itu - korban
# bencana malah dijawab info Tabungan Qurban. Dengan 0.86 kata pendek wajib
# cocok persis/ejaan, sementara frasa panjang ("kolaborasi kebaikn",
# "paket senyum ramdhan") tetap toleran satu-dua huruf salah ketik.
_AMBANG_KEMIRIPAN = 0.86


def _cari_alias_mirip(pesan_ejaan: str) -> str | None:
    """Lapisan terakhir pencocokan program: bandingkan tiap potongan 1-3 kata
    dari pesan dengan alias program, toleran salah ketik ringan (huruf
    tertukar/hilang). Dipakai HANYA kalau pencocokan persis & pencocokan
    ejaan sudah gagal, supaya tidak pernah menimpa hasil yang sudah tepat."""
    kata = pesan_ejaan.split()
    if not kata:
        return None

    alias_ejaan = [(normalisasi_ejaan(a), kunci) for a, kunci in PROGRAM_ALIASES.items()]
    kandidat_terbaik = None
    skor_terbaik = 0.0

    for n in (1, 2, 3):
        for i in range(len(kata) - n + 1):
            potongan = " ".join(kata[i:i + n])
            if len(potongan) < _MIN_PANJANG_FUZZY:
                continue
            for alias, kunci in alias_ejaan:
                if len(alias) < _MIN_PANJANG_FUZZY:
                    continue
                skor = difflib.SequenceMatcher(None, potongan, alias).ratio()
                if skor >= _AMBANG_KEMIRIPAN and skor > skor_terbaik:
                    skor_terbaik = skor
                    kandidat_terbaik = kunci

    return kandidat_terbaik

def get_all_programs_context() -> str:
    """
    Mengubah dictionary PROGRAMS menjadi string terstruktur 
    agar mudah dibaca dan dinalar oleh LLM.
    """
    konteks_teks = "DATA RESMI PROGRAM RUMAH AMAL USK:\n\n"
    
    for key, data in PROGRAMS.items():
        konteks_teks += f"Nama Program: {data['nama']}\n"
        konteks_teks += f"Proses Pengajuan: {data['proses']}\n"
        konteks_teks += "-" * 40 + "\n\n"
        
    return konteks_teks

def get_program_list():
    return (
        "✨ *KATALOG PROGRAM & BANTUAN RUMAH AMAL USK*\n\n"
        "Berikut 13 Program Kebaikan yang tersedia:\n\n"
        "🎓 *Pendidikan:*\n"
        " 1. 👨‍👩‍👧 Beasiswa Orang Tua Asuh (OTA)\n"
        " 2. 🇵🇸 Beasiswa Orang Tua Asuh (OTA) Palestina\n\n"
        "🤝 *Pemberdayaan:*\n"
        " 3. 💳 PINTAS (Pinjaman Tanpa Syarat)\n\n"
        "💚 *Sosial & Kemanusiaan:*\n"
        " 4. 🍚 Paket Senyum Ramadhan\n"
        " 5. 🍱 Bantuan Nasi Bungkus\n"
        " 6. 🆘 Dana Solidaritas Umat (DSU) Umum\n"
        " 7. 🇵🇸 Dana Solidaritas Umat (DSU) Palestina\n"
        " 8. 🧕 Peduli Sigra\n"
        " 9. 🧒 Peduli Yatim\n\n"
        "🕌 *Kemitraan:*\n"
        " 10. 🤲 Kolaborasi Kebaikan\n"
        " 11. 📖 Rumah Tahfizh\n\n"
        "🐄 *Syiar & Dakwah:*\n"
        " 12. 🐐 Tabungan Qurban\n\n"
        "💰 *Infaq:*\n"
        " 13. 📦 Infaq Bebas\n\n"
        "----------------------------------------\n"
        "📌 *Pilihan Navigasi:*\n"
        "• Ketik angka *1 s.d. 13* untuk melihat detail program\n"
        "• Ketik *0* untuk Kembali ke Menu Utama"
    )

def get_program_info(program_name: str) -> dict:
    keyword = (program_name or "").lower().strip()
    if keyword in PROGRAM_ALIASES:
        keyword = PROGRAM_ALIASES[keyword]
    if keyword in PROGRAMS:
        return PROGRAMS[keyword]
    for key, prog in PROGRAMS.items():
        if keyword in key or keyword in prog["nama"].lower():
            return prog
    # Terakhir: izinkan beda ejaan / salah ketik ringan. Pemanggil di jalur
    # WhatsApp meneruskan teks bebas user ke sini (bukan cuma kunci program),
    # jadi toleransi ini yang membuat "rumah tahfiz" tetap ketemu.
    kunci_mirip = extract_program_keyword(keyword)
    if kunci_mirip in PROGRAMS:
        return PROGRAMS[kunci_mirip]
    return None

def extract_program_keyword(pesan: str) -> str:
    """Tiga lapis, dari yang paling ketat ke paling longgar - lapisan longgar
    hanya dicoba kalau yang lebih ketat sudah gagal, jadi hasil yang sudah
    tepat tidak pernah ditimpa tebakan mirip-mirip."""
    pesan_lower = (pesan or "").lower()

    # 1. Persis seperti tertulis.
    for alias in sorted(PROGRAM_ALIASES.keys(), key=len, reverse=True):
        if _contains_keyword(pesan_lower, alias):
            return PROGRAM_ALIASES[alias]

    if _contains_keyword(pesan_lower, "pintas"):
        return "pintas"

    # 2. Beda ejaan tapi bunyinya sama (tahfizh/tahfiz, qurban/kurban).
    pesan_ejaan = normalisasi_ejaan(pesan_lower)
    for alias in sorted(PROGRAM_ALIASES.keys(), key=len, reverse=True):
        if _contains_keyword(pesan_ejaan, normalisasi_ejaan(alias)):
            return PROGRAM_ALIASES[alias]

    # 3. Salah ketik ringan (huruf tertukar/hilang/kelebihan).
    return _cari_alias_mirip(pesan_ejaan)

def format_program_response(program_data: dict, sapaan: str = "Bapak/Ibu") -> str:
    if not program_data: return None
    
    response = f"*{program_data['nama']}*\n\n{program_data['deskripsi']}\n\n*Syarat & Ketentuan:*\n"
    for i, syarat in enumerate(program_data['syarat'], 1):
        response += f"{i}. {syarat}\n"
    
    response += (
        f"\n*Proses Pendaftaran:*\n"
        f"{program_data['proses']}\n\n"
        f"🌐 *Website Resmi:* https://rumahamal.usk.ac.id"
    )

    qna_list = program_data.get("qna", [])
    if qna_list:
        response += "\n\n💡 *Pertanyaan Populer:*"
        for i, q in enumerate(qna_list, 1):
            response += f"\n{i}. {q['tanya']}"

    response += "\n\n----------------------------------------\n📌 *Pilihan Navigasi:*"
    if qna_list:
        max_q = len(qna_list)
        if max_q == 1:
            response += "\n• Ketik *1* untuk membaca jawaban pertanyaan di atas"
        else:
            response += f"\n• Ketik *1 s.d. {max_q}* untuk membaca jawaban pertanyaan di atas"

    response += "\n• Ketik *11* untuk Kembali ke Daftar Program"
    response += "\n• Ketik *0* untuk Kembali ke Menu Utama"

    return response
