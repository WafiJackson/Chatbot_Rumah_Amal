# ==========================================
# GENDER DETECTOR & SALUTATION NORMALIZER
# Rumah Amal USK Bot - Production Engine
# ==========================================

import re
import unicodedata

# Kamus Kata Kunci Pria (Bapak)
# Cakupan sengaja diperluas jauh dari daftar awal - nama seperti "Muarif"
# (staf sendiri) sebelumnya tidak terdeteksi karena daftarnya terlalu sempit.
PRIA_KEYWORDS = {
    "bapak", "pak", "ir", "sdr", "ustadz", "ust", "teuku", "teungku", "t",
    "muhammad", "mohammad", "moh", "m", "ahmad", "abdul", "abdullah",
    "abdurrahman", "abdurrazak", "abdillah", "syarif", "naufal", "noval",
    "yafi", "yafie", "yavie", "fajri", "hidayat", "hidayatullah", "pratama",
    "fauzi", "ardiansyah", "ramadhan", "fajar", "bambang", "budi", "hendra",
    "heru", "rizky", "rifky", "diki", "diky", "agung", "bayu", "dharma",
    "setiawan", "wijaya", "kusuma", "aditya", "surya", "yudi", "andi",
    "doni", "danang", "rudi", "rudy", "firmansyah", "adrian", "ilham",
    "ridwan", "faisal", "arif", "arifin", "maarif", "muarif", "reza",
    "iqbal", "hafiz", "hafidz", "wildan", "zulkarnain", "syahputra",
    "syahrial", "khadafi", "akbar", "farhan", "alwi", "hasan", "husein",
    "hussein", "ali", "usman", "umar", "khalid", "taufik", "taufiq", "rio",
    "dani", "ferry", "agus", "tri", "nanda", "satria", "albar", "raihan",
    "rayhan", "aziz", "azis", "bahri", "burhan", "burhanuddin", "darma",
    "dedi", "dedy", "deni", "deny", "dodi", "dody", "eko", "erwin", "fadli",
    "fadlan", "fahmi", "fahri", "fahrizal", "fikri", "fikram", "gunawan",
    "habibi", "hadi", "hakim", "halim", "hamdani", "hamzah", "hasyim",
    "hendri", "herman", "idris", "imran", "indra", "irfan", "irwan",
    "iskandar", "ismail", "ismet", "jamal", "jamaluddin", "joko",
    "junaidi", "junaid", "kamal", "kamaruddin", "kamil", "karim",
    "khairil", "khairul", "khairuddin", "kurnia", "kurniawan", "lukman",
    "makmur", "mansur", "marzuki", "mursyid", "musa", "mustafa", "nasir",
    "nazir", "nizar", "nurdin", "rahman", "rahmat", "rasyid", "rasyidi",
    "rendi", "ridho", "rizal", "rizki", "rezki", "roni", "sabri",
    "saifullah", "saiful", "salman", "samsul", "santoso", "sofyan",
    "sugianto", "sugiono", "sulaiman", "syafii", "syaiful", "syamsul",
    "taufan", "wahyu", "wahyudi", "wawan", "yanto", "yoga", "yudha",
    "yusuf", "zainal", "zainuddin", "zaki", "zulfahmi", "zulfikar",
    "zulkifli"
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
    "ratu", "maharani", "amalia", "amelia", "shinta", "sinta",
    "aini", "ainun", "ana", "ani", "asih", "atika", "azizah", "diana",
    "erna", "fitria", "hafsah", "hana", "hasanah", "husna", "ika", "irma",
    "jannah", "juwita", "karimah", "khadijah", "latifah", "lisa",
    "mardhiyah", "maryam", "mei", "melati", "nabila", "nadia", "nia",
    "novita", "rahayu", "raihanah", "rani", "rizka", "rosa", "safira",
    "salma", "salsabila", "salwa", "sabrina", "tia", "ulfa", "ulfah",
    "susanti", "vina", "wahyuni", "widya", "yasmin", "yeni", "yulianti",
    "zahra", "zainab", "zulaikha", "delia", "yuhana", "yohana", "natalia",
    "silvia", "claudia", "sonia", "lidia", "cynthia", "julia", "olivia",
    "patricia", "stevani", "stevania", "novia", "elvira", "monica",
    "veronica", "cindy", "elisabeth", "elisa", "grace", "gracia", "priska",
    "priskila", "debora", "sarah", "sara", "rebecca", "ester", "esther"
}

# Akhiran dan Substring Spesifik
SUBSTRING_PRIA = [
    "hidayat", "syahputra", "pratama", "ramadhan", "fauzi", "ardiansyah",
    "firmansyah", "zulkarnain", "arif", "rahman", "kurnia", "syaiful",
    "saiful", "zulkifli", "zulfikar", "nurdin", "kamaruddin", "burhanuddin",
    "jamaluddin", "zainuddin",
]
SUBSTRING_WANITA = [
    "fadhilah", "zahrani", "lestari", "purnamasari", "khairunnisa",
    "syarifah", "fitriana", "hasanah", "mardhiyah", "khadijah",
    "salsabila", "rahayu", "karimah", "latifah",
]


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
    - 'Bapak/Ibu' (Default Safety Net jika ambigu / low confidence - permintaan
      staf karena rentang usia donatur rata-rata sudah tidak sesuai dipanggil "Kak")
    """
    nama_clean = bersihkan_dan_normalisasi_nama(nama_raw)
    if not nama_clean:
        return "Bapak/Ibu"

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
            # "-ah" adalah penanda feminin dalam nama berakar Arab (Aisyah,
            # Fatimah, Hasanah, Latifah, dst) - jarang sekali dipakai di
            # akhir nama pria, jadi aman dipakai sebagai sinyal umum di luar
            # nama-nama yang sudah eksplisit terdaftar di atas.
            if word.endswith(("wati", "sari", "nisah", "nisa", "putri", "ah")):
                return "Ibu"
            # "-ia" adalah akhiran nama wanita yang umum di nama bercorak
            # Indonesia-Kristen/Barat (Delia, Natalia, Silvia, Claudia, Sonia,
            # Julia, dst) - belum ada satupun nama pria terdaftar di atas yang
            # berakhiran ini, jadi aman dipakai sebagai sinyal umum tambahan.
            if word.endswith("ia"):
                return "Ibu"

    # 3. Fallback Safety Net jika tidak ada kepastian 100%
    return "Bapak/Ibu"
