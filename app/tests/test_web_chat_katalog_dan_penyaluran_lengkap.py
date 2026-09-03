"""
User test menyeluruh untuk Web Chat (diminta 3 Sep 2026): (1) satu test
menanyakan SELURUH katalog program (bukan cuma donasi), dan (2) test untuk
SELURUH jenis penyaluran (5 kategori donasi ZIS) plus beberapa skenario umum.

Ditemukan lewat test ini: kategori ke-5 di katalog donasi ("Donasi (Bantuan
Kemanusiaan)") ternyata TIDAK PUNYA keyword pengenal sama sekali di
KAMUS_PENDAFTARAN (admin_scripts.py) - memilihnya dari katalog balik lagi ke
katalog ("ingin_donasi"), dan variasi seperti "bantuan kemanusiaan" malah
nyasar ke fallback LLM yang menjawab info galang dana bencana
("posko_bencana") - bukan konfirmasi kategori + nomor rekening seperti 4
kategori lainnya. Sudah diperbaiki (lihat KAMUS_PENDAFTARAN,
QA_SCRIPT["daftar_donasi_kemanusiaan"], _INTENT_KE_KODE_DONASI).
"""
import io

import pytest

import routes.public_web as public_web

NOMOR_REKENING = "7099400409"


def _mock_ocr(monkeypatch, nama=None, nominal=None, program="UMUM"):
    monkeypatch.setattr(
        public_web,
        "ekstrak_resi_vision",
        lambda image_bytes, caption="": {"nama": nama, "nominal": nominal, "program": program},
    )


# ---------------------------------------------------------------------------
# 1. Katalog SELURUH program (bukan cuma yang bisa didonasikan langsung)
# ---------------------------------------------------------------------------

def test_katalog_semua_program_lengkap(client):
    resp = client.post("/api/web-chat", json={"message": "Program apa saja yang tersedia di Rumah Amal?"})
    assert resp.status_code == 200
    reply = resp.json()["reply"]
    for nama_program in [
        "PINTAS",
        "BPRA-UKT",
        "Orang Tua Asuh",
        "Muallaf",
        "OTA Palestina",
        "Green Qurban",
        "Nasi Bungkus",
        "ECRA",
        "P2EMD",
    ]:
        assert nama_program in reply, f"Program '{nama_program}' hilang dari katalog lengkap"


@pytest.mark.parametrize(
    "pesan,nama_diharapkan",
    [
        ("apa itu PINTAS?", "PINTAS"),
        ("apa itu BPRA-UKT?", "BPRA-UKT"),
        ("apa itu program Orang Tua Asuh?", "ORANG TUA ASUH"),
        ("apa itu beasiswa Muallaf?", "MUALLAF"),
        ("apa itu OTA Palestina?", "OTA PALESTINA"),
        ("apa itu Green Qurban?", "GREEN QURBAN"),
        ("apa itu program Nasi Bungkus?", "NASI BUNGKUS"),
        ("apa itu ECRA?", "ECRA"),
        ("apa itu P2EMD?", "P2EMD"),
    ],
)
def test_detail_setiap_program_bisa_ditanya(client, pesan, nama_diharapkan):
    resp = client.post("/api/web-chat", json={"message": pesan})
    assert resp.status_code == 200
    reply = resp.json()["reply"]
    assert nama_diharapkan in reply.upper()
    assert "Syarat & Ketentuan" in reply
    assert "Proses Pendaftaran" in reply


# ---------------------------------------------------------------------------
# 2. SELURUH jenis penyaluran (5 kategori donasi ZIS) - alur penuh: katalog ->
# pilih kategori -> kategori terbawa ke resi yang diunggah setelahnya.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "pesan_pilih_kategori,nama_kategori,kode_program,penanda_konfirmasi",
    [
        ("saya ingin berdonasi zakat mal min", "Zakat Mal", "ZKT-MAL", NOMOR_REKENING),
        ("saya ingin berdonasi zakat penghasilan min", "Zakat Penghasilan", "ZKT-PENGHASILAN", NOMOR_REKENING),
        # Infak Rutin BUKAN transfer sekali jalan seperti 4 kategori lain -
        # ini komitmen rutin, jadi balasannya form pendaftaran (nama/instansi/
        # nominal komitmen), bukan nomor rekening langsung. Perilaku existing
        # yang sengaja, bukan bug.
        ("saya ingin berdonasi infak rutin min", "Infak Rutin", "INF-RUTIN", "FORMULIR INFAK RUTIN"),
        ("saya ingin berdonasi ota palestina min", "OTA Palestina", "DON-PALESTINA", NOMOR_REKENING),
        ("saya ingin berdonasi bantuan kemanusiaan min", "Donasi (Bantuan Kemanusiaan)", "DONASI", NOMOR_REKENING),
    ],
)
def test_setiap_jenis_penyaluran_dikonfirmasi_dan_terbawa_ke_resi(
    client, monkeypatch, baca_transaksi_terakhir, pesan_pilih_kategori, nama_kategori, kode_program, penanda_konfirmasi
):
    _mock_ocr(monkeypatch, nama="Donatur Uji", nominal=75000, program="UMUM")

    resp1 = client.post("/api/web-chat", json={"message": pesan_pilih_kategori})
    reply1 = resp1.json()["reply"]
    assert nama_kategori in reply1
    assert penanda_konfirmasi in reply1

    nomor_wa = f"0812{abs(hash(kode_program)) % 10**8:08d}"
    resp2 = client.post(
        "/api/web-chat/upload-resi",
        data={"wa_number": nomor_wa, "caption": ""},
        files={"file": ("resi.jpg", io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 6000), "image/jpeg")},
    )
    assert resp2.status_code == 200

    baris = baca_transaksi_terakhir(nomor_wa)
    assert baris is not None
    assert baris["kode_program"] == kode_program
    assert baris["status_verifikasi"] == "pending"


@pytest.mark.parametrize(
    "pesan_pilih_kategori",
    [
        "Donasi (Bantuan Kemanusiaan)",
        "donasi kemanusiaan",
    ],
)
def test_variasi_penulisan_donasi_kemanusiaan_tetap_dikenali(client, pesan_pilih_kategori):
    """Bug yang ditemukan: mengetik ulang PERSIS teks katalog ("Donasi (Bantuan
    Kemanusiaan)") sebelumnya malah dianggap niat donasi generik lagi (balik
    ke katalog), bukan konfirmasi kategori."""
    resp = client.post("/api/web-chat", json={"message": pesan_pilih_kategori})
    reply = resp.json()["reply"]
    assert NOMOR_REKENING in reply
    assert "Syarat & Ketentuan" not in reply  # bukan nyasar ke info program


# ---------------------------------------------------------------------------
# 3. Skenario umum (di luar donasi & program) - jalur keyword deterministik,
# sengaja tidak menyentuh fallback LLM supaya test stabil & tidak bergantung
# jaringan/API key.
# ---------------------------------------------------------------------------

def test_skenario_umum_sapaan(client):
    resp = client.post("/api/web-chat", json={"message": "assalamualaikum"})
    assert resp.status_code == 200
    assert "Assalamu" in resp.json()["reply"]


def test_skenario_umum_info_kontak(client):
    resp = client.post("/api/web-chat", json={"message": "ada nomor kontak admin?"})
    assert resp.status_code == 200
    assert resp.json()["reply"]


def test_skenario_umum_kalkulator_zakat_link_tampil(client):
    resp = client.post("/api/web-chat", json={"message": "apakah ada kalkulator zakat di situs resmi?"})
    assert resp.status_code == 200
    assert "rumahamal.usk.ac.id" in resp.json()["reply"]


def test_skenario_umum_donatur_umum(client):
    resp = client.post("/api/web-chat", json={"message": "apakah masyarakat umum boleh berdonasi di sini?"})
    assert resp.status_code == 200
    assert resp.json()["reply"]


def test_skenario_umum_laporan_publik(client):
    resp = client.post("/api/web-chat", json={"message": "boleh lihat laporan keuangan tahunan?"})
    assert resp.status_code == 200
    assert "rumahamal.usk.ac.id" in resp.json()["reply"]
