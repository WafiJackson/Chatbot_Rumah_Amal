# ==========================================
# PROGRAM MANAGER - Data & Logic Program Rumah Amal
# ==========================================

import re

# Database Program resmi disesuaikan 100% dengan dokumen tanya jawab staf USK
PROGRAMS = {
    "pintas": {
        "nama": "PINTAS (Pinjaman Tanpa Syarat)",
        "deskripsi": "Program pinjaman dana bergulir tanpa bunga untuk mahasiswa atau masyarakat.",
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
    "bpra_ukt": {
        "nama": "BPRA-UKT",
        "deskripsi": "Program bantuan biaya pendidikan UKT untuk mahasiswa kurang mampu.",
        "syarat": [
            "Mahasiswa aktif Universitas Syiah Kuala",
            "Memiliki status ekonomi kurang mampu",
            "Melampirkan surat keterangan tidak mampu (SKTM)"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": [
            {
                "tanya": "Apa saja syarat utama mendaftar beasiswa BPRA-UKT?",
                "jawab": "Syarat utama yaitu mahasiswa aktif USK berstatus kurang mampu yang melampirkan SKTM serta melengkapi berkas administrasi.",
                "kata_kunci": ["syarat utama", "syarat mendaftar", "syarat pendaftaran"]
            },
            {
                "tanya": "Berapa batas IPK minimal dan untuk semester berapa saja?",
                "jawab": "Syarat IPK minimal disesuaikan saat periode pendaftaran dibuka (biasanya terbuka untuk mahasiswa aktif minimal semester 2 ke atas).",
                "kata_kunci": ["ipk"]
            },
            {
                "tanya": "Berkas/dokumen apa saja yang wajib disiapkan?",
                "jawab": "KTM, KTP, Kartu Keluarga, SKTM dari desa/kelurahan, Slip UKT, dan Transkrip Nilai terbaru.",
                "kata_kunci": ["berkas", "dokumen"]
            },
            {
                "tanya": "Apakah penerima KIP-Kuliah / beasiswa lain boleh mendaftar (double funding)?",
                "jawab": "Tidak diperbolehkan double funding jika sudah menerima beasiswa beasiswa rutin penuh seperti KIP-Kuliah.",
                "kata_kunci": ["kip kuliah", "kip-kuliah", "double funding", "beasiswa lain"]
            },
            {
                "tanya": "Bagaimana aturan mutlak mengenai akhlak (merokok, berpacaran, judi online)?",
                "jawab": "Penerima manfaat wajib menjaga akhlak karimah. Pelanggaran aturan akhlak (seperti judi online/judol) akan didiskualifikasi secara otomatis.",
                "kata_kunci": ["akhlak", "merokok", "berpacaran", "judi online", "judol"]
            },
            {
                "tanya": "Berapa kali periode pendaftaran dibuka dalam setahun?",
                "jawab": "Beasiswa BPRA-UKT biasanya dibuka 2 kali dalam setahun mengikuti kalender akademik semester ganjil dan genap.",
                "kata_kunci": ["periode pendaftaran", "berapa kali", "kapan dibuka"]
            }
        ]
    },
    "ota_beasiswa": {
        "nama": "BEASISWA ORANG TUA ASUH (OTA)",
        "deskripsi": "Program beasiswa di mana donatur (Orang Tua Asuh) membiayai langsung satu atau lebih mahasiswa asuh.",
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
    "muallaf": {
        "nama": "BEASISWA MUALLAF",
        "deskripsi": "Program dukungan pendidikan khusus bagi mahasiswa atau masyarakat yang baru memeluk agama Islam (Muallaf).",
        "syarat": [
            "Memiliki sertifikat/surat keterangan syahadat",
            "Membutuhkan dukungan finansial pendidikan"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": [
            {
                "tanya": "Apakah ada pembinaan khusus selain bantuan biaya bagi penerima beasiswa Muallaf?",
                "jawab": "Ya, selain beasiswa pendidikan, penerima manfaat juga mendapatkan pendampingan dan pembinaan keagamaan.",
                "kata_kunci": ["pembinaan"]
            }
        ]
    },
    "ota_palestina": {
        "nama": "OTA PALESTINA (Orang Tua Asuh Mahasiswa Palestina)",
        "deskripsi": "Program beasiswa dan bantuan biaya hidup khusus untuk mahasiswa asal Palestina.",
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
    "green_qurban": {
        "nama": "GREEN QURBAN",
        "deskripsi": "Program qurban ramah lingkungan dengan hewan berkualitas yang didistribusikan ke masyarakat.",
        "syarat": [
            "Terbuka bagi pekurban yang ingin menyalurkan hewannya",
            "Menggunakan kemasan ramah lingkungan (non-plastik)"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": [
            {
                "tanya": "Bagaimana sistem penyaluran hewan/daging kurban di Rumah Amal USK?",
                "jawab": "Rumah Amal menerima titipan hewan/donasi kurban, mengelola pemotongan ramah lingkungan (non-plastik), dan menyalurkan kupon daging kurban secara merata kepada masyarakat miskin serta mahasiswa kurang mampu.",
                "kata_kunci": ["penyaluran", "daging kurban", "hewan kurban"]
            }
        ]
    },
    "nasi_bungkus": {
        "nama": "BANTUAN NASI BUNGKUS",
        "deskripsi": "Program distribusi makanan (nasi bungkus) gratis untuk masyarakat dhuafa, pekerja informal, dan yatim piatu.",
        "syarat": [
            "Tidak ada syarat khusus",
            "Didistribusikan pada hari tertentu (misal: Jumat Berkah)"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": [
            {
                "tanya": "Kepada siapa saja bantuan makanan/nasi bungkus ini didistribusikan?",
                "jawab": "Makanan gratis didistribusikan pada Jumat Berkah untuk masyarakat dhuafa, pekerja informal di lingkungan kampus, dan anak yatim piatu.",
                "kata_kunci": ["kepada siapa", "didistribusikan", "siapa saja"]
            }
        ]
    },
    "ecra": {
        "nama": "ECRA (Entrepreneurship Club Rumah Amal)",
        "deskripsi": "Klub wirausaha untuk melatih dan mendanai mahasiswa yang memiliki rintisan usaha.",
        "syarat": [
            "Mahasiswa dengan minat wirausaha",
            "Memiliki proposal atau rintisan bisnis"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": []
    },
    "p2emd": {
        "nama": "P2EMD",
        "deskripsi": "Program Pemberdayaan Ekonomi Masyarakat Dhuafa berupa modal usaha dan pendampingan.",
        "syarat": [
            "Masyarakat dhuafa di sekitar wilayah kampus",
            "Memiliki kemauan untuk berwirausaha"
        ],
        "proses": "Informasi berkas persyaratan dan pendaftaran dapat diakses melalui website resmi kami saat periode dibuka.",
        "qna": [
            {
                "tanya": "Bagaimana bentuk bantuan P2EMD bagi masyarakat dhuafa?",
                "jawab": "Berupa bantuan modal usaha, pelatihan, dan pendampingan UMKM dhuafa yang seleksinya dilakukan melalui survei lapangan oleh tim Rumah Amal.",
                "kata_kunci": ["bentuk bantuan"]
            }
        ]
    }
}

PROGRAM_ALIASES = {
    "pinjaman tanpa syarat": "pintas",
    "pinjaman": "pintas",
    "bpra": "bpra_ukt",
    "ukt": "bpra_ukt",
    "palestina": "ota_palestina",
    "qurban": "green_qurban",
    "nasi": "nasi_bungkus",
    "nasi bungkus": "nasi_bungkus",
    "jumat berkah": "nasi_bungkus",
    "entrepreneur": "ecra",
    "pemberdayaan": "p2emd",
    "orang tua asuh": "ota_beasiswa",
    "ota": "ota_beasiswa",
    "mualaf": "muallaf"
}


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
        "Berikut program penyaluran & beasiswa yang tersedia:\n\n"
        "🎓 *Beasiswa & Bantuan:*\n"
        " 1. 🎓 PINTAS (Pinjaman Tanpa Syarat)\n"
        " 2. 📚 BPRA-UKT (Bantuan Pembayaran UKT)\n"
        " 3. 👨‍👩‍👧 Beasiswa Orang Tua Asuh (OTA)\n"
        " 4. 🌙 Beasiswa Muallaf\n\n"
        "💚 *Penyaluran & Pemberdayaan Sosial:*\n"
        " 5. 🇵🇸 OTA Palestina\n"
        " 6. 🥩 Green Qurban\n"
        " 7. 🍱 Bantuan Nasi Bungkus\n"
        " 8. 🚀 ECRA (Entrepreneurship Club)\n"
        " 9. 🏦 P2EMD (Modal Usaha Dhuafa)\n\n"
        "----------------------------------------\n"
        "📌 *Pilihan Navigasi:*\n"
        "• Ketik angka *1 s.d. 9* untuk melihat detail program\n"
        "• Ketik *0* untuk Kembali ke Menu Utama"
    )

def get_program_info(program_name: str) -> dict:
    keyword = program_name.lower().strip()
    if keyword in PROGRAM_ALIASES:
        keyword = PROGRAM_ALIASES[keyword]
    if keyword in PROGRAMS:
        return PROGRAMS[keyword]
    for key, prog in PROGRAMS.items():
        if keyword in key or keyword in prog["nama"].lower():
            return prog
    return None

def extract_program_keyword(pesan: str) -> str:
    pesan_lower = pesan.lower()
    for alias in sorted(PROGRAM_ALIASES.keys(), key=len, reverse=True):
        if _contains_keyword(pesan_lower, alias):
            return PROGRAM_ALIASES[alias]
    
    keywords = ["pintas", "bpra", "ukt", "palestina", "qurban", "nasi", "ecra", "p2emd", "ota", "muallaf", "mualaf"]
    for keyword in keywords:
        if _contains_keyword(pesan_lower, keyword):
            if keyword in ["muallaf", "mualaf"]: return "muallaf"
            if keyword == "nasi": return "nasi_bungkus"
            return keyword
    return None

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
