"""
Regresi dua bug yang dilaporkan 21 Sep 2026 lewat screenshot, menjelang
peluncuran bot dengan nomor resmi:

1. Bertanya soal PINTAS -> bot menjawab info program lalu bertanya "Apakah
   ingin disambungkan ke admin? (Balas Ya atau Batal)" -> user menjawab "ya"
   -> bot malah menjawab "Mimin kurang paham". Penanda "sedang menunggu
   Ya/Batal" tidak pernah dinyalakan di jalur PINTAS.

2. "rumah tahfiz" (tanpa h) tidak dikenali sama sekali, padahal cuma beda
   satu huruf dari "rumah tahfizh". Donatur mayoritas orang dewasa yang
   menulis apa adanya - bot harus toleran beda ejaan & salah ketik ringan.
"""
import pytest

import routes.public_web as public_web


def _chat(client, pesan):
    resp = client.post("/api/web-chat", json={"message": pesan})
    assert resp.status_code == 200
    return resp.json()["reply"]


# ---------------------------------------------------------------------------
# 1. PINTAS -> "ya" harus dilanjutkan ke langkah minta nomor WA
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pertanyaan", ["apa itu pintas?", "saya mau pinjam uang", "info pinjaman tanpa syarat"])
@pytest.mark.parametrize("jawaban_ya", ["ya", "iya", "Ya", "boleh", "oke"])
def test_pintas_lalu_ya_minta_nomor_wa_bukan_fallback(client, pertanyaan, jawaban_ya):
    balasan_pintas = _chat(client, pertanyaan)
    assert "disambungkan ke admin" in balasan_pintas.lower()

    balasan_ya = _chat(client, jawaban_ya)
    assert balasan_ya != public_web._WEB_FALLBACK_REPLY
    assert "kurang paham" not in balasan_ya.lower()
    assert "whatsapp" in balasan_ya.lower() or "nomor" in balasan_ya.lower()


def test_pintas_alur_lengkap_sampai_nomor_diteruskan_ke_admin(client, monkeypatch):
    notifikasi = []
    monkeypatch.setattr(public_web, "notify_admin", lambda pesan, *a, **k: notifikasi.append(pesan))

    _chat(client, "apa itu pintas?")
    _chat(client, "ya")
    balasan_nomor = _chat(client, "081234567890")

    assert "kurang paham" not in balasan_nomor.lower()
    assert len(notifikasi) == 1
    assert "081234567890" in notifikasi[0]


def test_pintas_tidak_mengunci_percakapan(client):
    """Tawaran admin setelah info PINTAS itu OPSIONAL: user yang lanjut
    bertanya hal lain harus dijawab normal, bukan dipaksa menjawab Ya/Batal
    (regresi yang sempat muncul saat bug di atas pertama kali diperbaiki)."""
    _chat(client, "apa itu pintas?")
    balasan = _chat(client, "program apa saja")
    assert "13 Program" in balasan
    assert "balas *ya*" not in balasan.lower()


def test_pintas_kalimat_baru_berawalan_mau_bukan_konfirmasi(client):
    _chat(client, "apa itu pintas?")
    balasan = _chat(client, "mau tanya zakat mal")
    assert "nomor WhatsApp yang aktif" not in balasan


def test_hubungi_admin_eksplisit_tetap_menunggu_ya_atau_batal(client):
    """Beda dari tawaran PINTAS: kalau user SENDIRI yang minta hubungi admin,
    jawaban yang ambigu tetap diminta konfirmasi Ya/Batal."""
    _chat(client, "hubungi admin")
    balasan = _chat(client, "program apa saja")
    assert "balas *ya*" in balasan.lower()


def test_pintas_lalu_batal_tidak_menghubungi_admin(client, monkeypatch):
    notifikasi = []
    monkeypatch.setattr(public_web, "notify_admin", lambda pesan, *a, **k: notifikasi.append(pesan))

    _chat(client, "apa itu pintas?")
    balasan_batal = _chat(client, "batal")

    assert "kurang paham" not in balasan_batal.lower()
    assert notifikasi == []


# ---------------------------------------------------------------------------
# 2. Toleransi beda ejaan & salah ketik ringan pada nama program
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "pesan,nama_program",
    [
        ("apa itu rumah tahfiz?", "RUMAH TAHFIZH"),
        ("apa itu rumah tahfidz?", "RUMAH TAHFIZH"),
        ("info tahfiz dong", "RUMAH TAHFIZH"),
        ("rumah tahfis itu apa", "RUMAH TAHFIZH"),
        ("apa itu tabungan kurban?", "TABUNGAN QURBAN"),
        ("tabungn qurban gimana", "TABUNGAN QURBAN"),
        ("apa itu infak bebas?", "INFAQ BEBAS"),
        ("paket senyum ramadan itu apa", "PAKET SENYUM RAMADHAN"),
        ("kolaborsi kebaikan itu apa", "KOLABORASI KEBAIKAN"),
        ("peduli yatiim apa itu", "PEDULI YATIM"),
    ],
)
def test_nama_program_dengan_typo_tetap_dikenali(client, pesan, nama_program):
    balasan = _chat(client, pesan)
    assert nama_program in balasan.upper()
    assert "kurang paham" not in balasan.lower()


@pytest.mark.parametrize(
    "pesan",
    ["saya korban bencana banjir", "korban kebakaran asrama butuh bantuan", "bantuan untuk korban bencana"],
)
def test_korban_bencana_tidak_disangka_tabungan_qurban(client, pesan):
    """'korban' (bencana) cuma beda satu huruf dari 'kurban' (qurban) - justru
    karena itu pencocokan mirip-mirip WAJIB tidak menelan kata pendek ini,
    atau korban bencana malah dijawab info Tabungan Qurban."""
    balasan = _chat(client, pesan)
    assert "TABUNGAN QURBAN" not in balasan.upper()


# ---------------------------------------------------------------------------
# 3. Bahasa sehari-hari donatur (temuan uji ekstrem 21 Sep 2026)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "pesan,harus_ada",
    [
        ("PROGRAM APA AJA MIN", "13 Program"),
        ("zakat apa aja yang dilayani", "Zakat Pertanian"),
        ("pinjem duit bisa ga", "PINJAMAN TANPA SYARAT"),
        ("donasi", "pilih dulu"),
        ("sedekah min", "pilih dulu"),
        ("pengen donasi", "pilih dulu"),
        ("mau infak", "pilih dulu"),
    ],
)
def test_bahasa_informal_dikenali(client, pesan, harus_ada):
    balasan = _chat(client, pesan)
    assert harus_ada.upper() in balasan.upper()
    assert balasan != public_web._WEB_FALLBACK_REPLY


@pytest.mark.parametrize("pesan", ["terima kasih min", "makasih banyak ya kak atas infonya", "thx min", "jazakallah khairan"])
def test_ucapan_terima_kasih_dibalas_sopan(client, pesan):
    assert "Sama-sama" in _chat(client, pesan)


def test_terima_kasih_yang_membawa_info_lain_tidak_ditelan(client):
    """'terima kasih, saya sudah transfer' membawa informasi penting - jangan
    cuma dibalas 'sama-sama'."""
    assert "Sama-sama" not in _chat(client, "terima kasih, saya sudah transfer")


def test_bayar_zakat_mal_mencatat_kategori_zakat_mal(client, monkeypatch, baca_transaksi_terakhir):
    """'bayar zakat mal' sebelumnya dijawab cara donasi generik dan kategori
    Zakat Mal hilang - resi yang diunggah sesudahnya tidak ikut tertandai."""
    import io
    monkeypatch.setattr(
        public_web, "ekstrak_resi_vision",
        lambda image_bytes, caption="": {"nama": "Donatur Uji", "nominal": 50000, "program": "UMUM"},
    )
    balasan = _chat(client, "saya mau bayar zakat mal")
    assert "*Zakat Mal*" in balasan

    nomor = "081299887766"
    client.post(
        "/api/web-chat/upload-resi",
        data={"wa_number": nomor, "caption": ""},
        files={"file": ("resi.jpg", io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 6000), "image/jpeg")},
    )
    assert baca_transaksi_terakhir(nomor)["kode_program"] == "ZKT-MAL"


# ---------------------------------------------------------------------------
# 4. Balasan angka dari daftar bernomor terakhir yang ditampilkan bot
# ---------------------------------------------------------------------------

def test_angka_dari_menu_sapaan(client):
    _chat(client, "halo")
    assert "13 Program" in _chat(client, "1")


def test_angka_dari_katalog_dan_bisa_berpindah_program(client):
    _chat(client, "program apa saja")
    assert "PINJAMAN TANPA SYARAT" in _chat(client, "3").upper()
    # Masih menelusuri katalog - angka berikutnya tetap berarti program.
    assert "RUMAH TAHFIZH" in _chat(client, "11").upper()
    assert "INFAQ BEBAS" in _chat(client, "13.").upper()


def test_angka_dari_daftar_kategori_donasi(client):
    _chat(client, "mau donasi")
    balasan = _chat(client, "1")
    assert "*Zakat Mal*" in balasan
    assert "7099400409" in balasan


def test_setiap_nomor_katalog_menunjuk_program_yang_benar():
    """Urutan URUTAN_KATALOG, teks get_program_list(), dan kalimat tanya yang
    dipakai web chat harus selalu sejalan - kalau salah satu diubah tanpa
    yang lain, nomor yang diketik donatur menunjuk program yang salah."""
    import re
    from services.program_manager import (
        PROGRAMS, URUTAN_KATALOG, extract_program_keyword, get_program_list, kueri_untuk_program,
    )
    assert sorted(URUTAN_KATALOG) == sorted(PROGRAMS)

    nomor_di_katalog = [int(n) for n in re.findall(r"^\s*(\d+)\.", get_program_list(), flags=re.M)]
    assert nomor_di_katalog == list(range(1, len(URUTAN_KATALOG) + 1))

    for kunci in URUTAN_KATALOG:
        assert extract_program_keyword(kueri_untuk_program(kunci)) == kunci


# ---------------------------------------------------------------------------
# 5. Tidak boleh ada jalan buntu saat dimintai nomor WA
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pembatalan", ["batal", "gak jadi deh", "tidak jadi"])
def test_bisa_membatalkan_saat_dimintai_nomor_wa(client, pembatalan):
    """Sebelumnya SEMUA jawaban selain nomor - termasuk "batal" - dibalas
    "bukan format nomor yang valid" selamanya. Sesi tersimpan di cookie,
    jadi memuat ulang halaman pun tidak menolong: jalan buntu permanen."""
    _chat(client, "hubungi admin")
    _chat(client, "ya")
    balasan = _chat(client, pembatalan)
    assert "dibatalkan" in balasan
    # Benar-benar keluar dari alur: pertanyaan berikutnya dijawab normal.
    assert "13 Program" in _chat(client, "program apa saja")


def test_beralih_topik_saat_dimintai_nomor_dijawab_dan_diberi_tahu(client):
    _chat(client, "hubungi admin")
    _chat(client, "ya")
    balasan = _chat(client, "berapa nomor rekening")
    assert "7099400409" in balasan
    assert "hubungi admin" in balasan.lower()  # cara menyambung lagi disebutkan


def test_nomor_belum_lengkap_tetap_diminta_ulang(client):
    _chat(client, "hubungi admin")
    _chat(client, "ya")
    assert "bukan format nomor" in _chat(client, "0812")
