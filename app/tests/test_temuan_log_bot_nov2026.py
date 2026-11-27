"""
Regresi temuan review Log Bot produksi (31 percakapan, 30 Sep - 27 Nov 2026).

Gelombang 1 (alur percakapan):
1. "Ya"/"Batal" setelah tawaran admin hasil intent minta_bantuan_pintas
   (tebakan LLM, mis. "saya butuh bantuan") dibalas "Mimin kurang paham".
2. Satu potongan pesan tidak dikenali -> SELURUH balasan web diganti fallback.
3. Kategori "3. Infak Rutin" tidak memberi rekening & keluar dari alur kategori.
4. Angka tanpa konteks jatuh ke menu sapaan ("4" -> Cek Riwayat), dan katalog
   program "lupa" setelah diselingi pertanyaan lain.
5. "oke"/"baik"/"ga jadi"/"batal" tanpa konteks -> "kurang paham".
7. "mal" saat memilih kategori -> daftar jenis zakat, bukan Zakat Mal.
9. "lapar"/"bantu saya makan" -> PINTAS, bukan program Nasi Bungkus.

Gelombang 2 (perapian): salah ketik rekening, petunjuk "panel kiri" yang
tidak berlaku di HP, sapaan "Bapak/Ibu N" dari nama profil WA satu huruf.
"""
import pytest

import routes.public_web as public_web
from admin_scripts import QA_SCRIPT, ambil_balasan
from services import llm_agent

REKENING = "7099400409"


def _chat(client, pesan):
    resp = client.post("/api/web-chat", json={"message": pesan})
    assert resp.status_code == 200
    return resp.json()


def _reply(client, pesan):
    return _chat(client, pesan)["reply"]


@pytest.fixture
def llm(monkeypatch):
    """Atur tebakan get_intent() (Gemini) tanpa memanggil API sungguhan."""
    def _set(intent):
        monkeypatch.setattr(llm_agent, "get_intent", lambda pesan: intent)
    _set("tidak_diketahui")
    return _set


# ---------------------------------------------------------------------------
# 1. minta_bantuan_pintas -> Ya/Batal dikenali
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("jawaban,penanda", [("ya", "nomor whatsapp"), ("Batal", "dibatalkan")])
def test_web_minta_bantuan_pintas_lalu_ya_atau_batal(client, llm, jawaban, penanda):
    llm("minta_bantuan_pintas")
    assert "Balas *Ya* atau *Batal*" in _reply(client, "saya butuh bantuan")
    llm("tidak_diketahui")
    balasan = _reply(client, jawaban)
    assert "kurang paham" not in balasan.lower()
    assert penanda in balasan.lower()


def test_wa_minta_bantuan_pintas_lalu_ya_masuk_alur_admin(client, llm, nomor_baru, kirim_pesan):
    from services import state_manager

    nomor = nomor_baru()
    llm("minta_bantuan_pintas")
    _, balasan, _ = kirim_pesan(nomor, "saya butuh bantuan")
    assert "Balas *Ya* atau *Batal*" in balasan
    assert state_manager.get_status(nomor) == "MENUNGGU_ADMIN"
    llm("tidak_diketahui")
    _, balasan_ya, _ = kirim_pesan(nomor, "ya")
    assert "kurang paham" not in balasan_ya.lower()


# ---------------------------------------------------------------------------
# 2. Jawaban sebagian tidak lagi dibuang seluruhnya
# ---------------------------------------------------------------------------

def test_sebagian_dipahami_tetap_dijawab(client, llm):
    balasan = _reply(client, "yafi siapa? sarjana?")
    assert "Yafi Hidayatullah" in balasan
    assert "kurang paham" not in balasan.lower()
    # Fallback versi WhatsApp ("Ketik *1*") tidak boleh ikut terbawa.
    assert "Ketik *1*" not in balasan


def test_semua_tidak_dipahami_tetap_fallback_web(client, llm):
    assert _reply(client, "qwerty asdfgh") == public_web._WEB_FALLBACK_REPLY


# ---------------------------------------------------------------------------
# 3 & 7. Pilihan kategori: angka 3 (Infak Rutin) dan jawaban singkat
# ---------------------------------------------------------------------------

def test_kategori_3_infak_rutin_memberi_formulir_dan_rekening(client, llm):
    _reply(client, "mau donasi")
    balasan = _reply(client, "3")
    assert "FORMULIR INFAK RUTIN" in balasan
    assert REKENING in balasan


@pytest.mark.parametrize(
    "jawaban,nama_kategori",
    [
        ("mal", "*Zakat Mal*"),
        ("maal min", "*Zakat Mal*"),
        ("penghasilan", "*Zakat Penghasilan*"),
        ("palestina aja", "*OTA Palestina*"),
        ("kemanusiaan", "*Donasi (Bantuan Kemanusiaan)*"),
        ("infak rutin", "FORMULIR INFAK RUTIN"),
    ],
)
def test_jawaban_singkat_saat_memilih_kategori(client, llm, jawaban, nama_kategori):
    _reply(client, "ingin berdonasi")
    balasan = _reply(client, jawaban)
    assert nama_kategori in balasan
    assert REKENING in balasan


# ---------------------------------------------------------------------------
# 4. Angka mengikuti daftar terakhir yang benar-benar tampil
# ---------------------------------------------------------------------------

def test_angka_4_setelah_detail_program_tidak_membuka_cek_riwayat(client, llm):
    _reply(client, "halo")
    _reply(client, "apa itu rumah tahfizh?")
    hasil = _chat(client, "4")
    assert hasil["requires_otp"] is False
    assert "nomor *4*" in hasil["reply"]


def test_angka_tanpa_daftar_apa_pun_ditanyakan_balik(client, llm):
    hasil = _chat(client, "2")
    assert "nomor *2*" in hasil["reply"]


def test_menu_sapaan_4_tetap_cek_riwayat(client, llm):
    _reply(client, "assalamualaikum")
    assert _chat(client, "4")["requires_otp"] is True


def test_katalog_tetap_berlaku_setelah_diselingi_pertanyaan(client, llm):
    _reply(client, "program apa saja")
    _reply(client, "nomor rekeningnya berapa?")
    assert "RUMAH TAHFIZH" in _reply(client, "11").upper()
    _reply(client, "cek riwayat")
    assert "INFAQ BEBAS" in _reply(client, "13").upper()


def test_daftar_baru_menggantikan_katalog(client, llm):
    _reply(client, "program apa saja")
    _reply(client, "mau donasi")
    balasan = _reply(client, "1")
    assert "*Zakat Mal*" in balasan


def test_salah_nomor_kategori_masih_bisa_memilih_ulang(client, llm):
    _reply(client, "mau donasi")
    assert "nomor *7*" in _reply(client, "7")
    assert "*Zakat Mal*" in _reply(client, "1")


# ---------------------------------------------------------------------------
# 5. Ungkapan penutup singkat
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pesan", ["oke", "baik", "ga jadi lah min", "batal", "sip min", "ok deh"])
def test_penutup_singkat_tidak_dibalas_kurang_paham(client, llm, pesan):
    balasan = _reply(client, pesan)
    assert "kurang paham" not in balasan.lower()
    assert "Mimin siap bantu" in balasan


def test_oke_dengan_pertanyaan_tetap_dijawab_pertanyaannya(client, llm):
    balasan = _reply(client, "oke, nomor rekeningnya berapa?")
    assert REKENING in balasan


# ---------------------------------------------------------------------------
# 9. Lapar -> Nasi Bungkus, bukan PINTAS
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pesan", ["Saya lapar min", "bantu saya makan min", "saya belum makan dari kemarin"])
def test_lapar_diarahkan_ke_nasi_bungkus(client, llm, pesan):
    llm("minta_bantuan_pintas")  # tebakan LLM lama tidak boleh dipakai lagi
    balasan = _reply(client, pesan)
    assert "NASI BUNGKUS" in balasan.upper()
    assert "PINTAS" not in balasan


# ---------------------------------------------------------------------------
# Gelombang 2
# ---------------------------------------------------------------------------

def test_teks_rekening_tanpa_salah_ketik():
    assert "zakat/infak/donasi" in QA_SCRIPT["info_rekening"]
    assert "infak.donasi" not in QA_SCRIPT["info_rekening"]


def test_fallback_web_tidak_menyebut_panel_kiri():
    assert "panel kiri" not in public_web._WEB_FALLBACK_REPLY


@pytest.mark.parametrize("nama", ["N", "ab", "A B"])
def test_nama_profil_terlalu_pendek_tidak_dipakai_di_sapaan(nama):
    balasan = ambil_balasan("sapaan", nama_pengirim=nama)
    assert f" {nama.replace(' ', '').title()}!" not in balasan


def test_nama_profil_wajar_tetap_dipakai():
    assert "Budi" in ambil_balasan("sapaan", nama_pengirim="Budi")
