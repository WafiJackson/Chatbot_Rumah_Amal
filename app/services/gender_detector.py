# ==========================================
# GENDER DETECTOR & SALUTATION NORMALIZER
# Rumah Amal USK Bot - Production Engine
# ==========================================

import re
import unicodedata

# Kamus Kata Kunci Pria (Bapak)
PRIA_KEYWORDS = {
    "bapak", "pak", "ir", "sdr", "ustadz", "ust", "teuku", "t",
    "muhammad", "m", "ahmad", "abdul", "syarif", "naufal", "noval",
    "yafi", "yafie", "yavie", "fajri", "hidayat", "hidayatullah", "pratama",
    "fauzi", "ardiansyah", "ramadhan", "fajar", "bambang", "budi", "hendra",
    "heru", "rizky", "rifky", "diki", "diky", "agung", "bayu", "dharma",
    "setiawan", "wijaya", "kusuma", "aditya", "surya", "yudi", "andi",
    "doni", "danang", "rudi", "rudy", "firmansyah", "adrian", "ilham",
    "ridwan", "faisal", "arif", "arifin", "reza", "iqbal", "hafiz",
    "hafidz", "wildan", "zulkarnain", "syahputra", "syahrial", "khadafi",
    "akbar", "farhan", "alwi", "hasan", "husein", "hussein", "ali", "usman",
    "umar", "khalid", "taufik", "taufiq", "rio", "dani", "ferry", "agus",
    "tri", "nanda", "satria", "albar", "raihan", "rayhan"
}

# Kamus Kata Kunci Wanita (Ibu)
WANITA_KEYWORDS = {
    "ibu", "bu", "sdri", "ustadzah", "cut", "dara", "putri", "siti",
    "aisyah", "fatimah", "nur", "nurul", "rahmah", "fitri", "wati",
    "fadhilah", "zahrani", "lestari", "nita", "sari", "anisa", "annisa",
    "dewi", "maya", "dian", "rina", "dina", "marlina", "suci", "wulan",
    "indri", "tari", "ratna", "rahmi", "lia", "via", "tania", "vivi",
    "yulia", "yuni", "titi", "desy", "desi", "fitriana", "kartika",
    "indah", "muthia", "mutia", "intan", "khairunnisa", "syarifah",
    "meutia", "laila", "laili", "suhartini", "tini", "tuti", "triana",
    "ratu", "maharani", "amalia", "amelia", "shinta", "sinta"
}

# Akhiran dan Substring Spesifik
SUBSTRING_PRIA = ["hidayat", "syahputra", "pratama", "ramadhan", "fauzi", "ardiansyah", "firmansyah", "zulkarnain"]
SUBSTRING_WANITA = ["fadhilah", "zahrani", "lestari", "purnamasari", "khairunnisa", "syarifah", "fitriana"]


def bersihkan_dan_normalisasi_nama(nama_raw: str) -> str:
    """
    1. Unicode Normalization (NFKD): Mengonversi 'À' -> 'A', 'é' -> 'e', dll.
    2. Menghapus emoji dan karakter khusus non-alphabet.
    3. Unspacing huruf tunggal: 'N O V A L' -> 'NOVAL'.
    """
    if not nama_raw:
        return ""

    # 1. NFKD Transliteration
    normalized = unicodedata.normalize('NFKD', str(nama_raw))
    ascii_text = ''.join(c for c in normalized if not unicodedata.combining(c))

    # 2. Hapus emoji & karakter non-alfanumerik (simpan huruf dan spasi)
    clean_text = re.sub(r'[^a-zA-Z\s]', '', ascii_text).strip()

    # 3. Deteksi pola huruf tunggal terpisah spasi (contoh: N O V A L)
    tokens = clean_text.split()
    if len(tokens) > 1 and all(len(t) == 1 for t in tokens):
        clean_text = "".join(tokens)
    else:
        # Gabungkan token-token huruf tunggal berurutan saja jika ada
        new_tokens = []
        single_buffer = []
        for t in tokens:
            if len(t) == 1:
                single_buffer.append(t)
            else:
                if single_buffer:
                    new_tokens.append("".join(single_buffer))
                    single_buffer = []
                new_tokens.append(t)
        if single_buffer:
            new_tokens.append("".join(single_buffer))
        clean_text = " ".join(new_tokens)

    return clean_text.lower()


def deteksi_sapaan_gender(nama_raw: str) -> str:
    """
    Mendeteksi gender dari nama dan mengembalikan sapaan resmi:
    - 'Bapak' (jika terdeteksi Pria)
    - 'Ibu' (jika terdeteksi Wanita)
    - 'Kak' (Default Safety Net jika ambigu / low confidence)
    """
    nama_clean = bersihkan_dan_normalisasi_nama(nama_raw)
    if not nama_clean:
        return "Kak"

    words = nama_clean.split()

    # 1. Pengecekan Kata Kunci Langsung (Word Match)
    for word in words:
        if word in PRIA_KEYWORDS:
            return "Bapak"
        if word in WANITA_KEYWORDS:
            return "Ibu"

    # 2. Pengecekan Substring / Akhiran Nama (Pattern Match)
    for word in words:
        if any(sub in word for sub in SUBSTRING_PRIA):
            return "Bapak"
        if any(sub in word for sub in SUBSTRING_WANITA):
            return "Ibu"

        if len(word) >= 4:
            if word.endswith(("wan", "syah", "din", "putra", "fauzi")):
                return "Bapak"
            if word.endswith(("wati", "sari", "nisah", "nisa", "putri")):
                return "Ibu"

    # 3. Fallback Safety Net jika tidak ada kepastian 100%
    return "Kak"
