"""
Test regresi untuk bug-bug yang ditemukan & diperbaiki 27-28 Agustus 2026.
Tujuannya supaya bug yang sudah pernah diperbaiki tidak diam-diam muncul
lagi di perubahan kode berikutnya - sebelum ada file ini, seluruh
verifikasi hidup di script sekali-pakai yang tidak pernah dijalankan ulang
otomatis. Lihat folder pribadi/CATATAN_KEKURANGAN_PROYEK.txt untuk detail
kronologis tiap bug.

Jalankan dengan: cd app && pytest tests/ -v
"""
import pytest

from services.gender_detector import deteksi_sapaan_gender
from admin_scripts import _is_sapaan, klasifikasi_pesan, susun_balasan


# =========================================================================
# KEAMANAN: endpoint /webhook wajib menolak request tanpa secret yang benar
# =========================================================================
def test_webhook_menolak_tanpa_secret(client):
    r = client.post("/webhook", json={"event": "message", "payload": {}})
    assert r.status_code == 401


def test_webhook_menolak_secret_salah(client):
    r = client.post("/webhook?secret=salah-sekali", json={"event": "message", "payload": {}})
    assert r.status_code == 401


def test_webhook_menerima_secret_benar(client, nomor_baru, kirim_pesan):
    nomor = nomor_baru()
    resp, balasan, _ = kirim_pesan(nomor, "assalamualaikum")
    assert resp["status"] == "sukses"


# =========================================================================
# BUG: event "message.ack" (WAHA) dulu diproses seolah pesan baru, memicu
# balasan "tidak_diketahui" duplikat.
# =========================================================================
def test_event_ack_diabaikan(client, nomor_baru):
    nomor = nomor_baru()
    chat_id = f"{nomor}@c.us"
    r = client.post(
        f"/webhook?secret=test-secret-webhook-key",
        json={"event": "message.ack", "payload": {"id": "msg-1", "from": chat_id, "ack": 2}},
    )
    assert r.json()["status"] == "diabaikan"


def test_pesan_tanpa_konten_diabaikan(client, nomor_baru):
    nomor = nomor_baru()
    chat_id = f"{nomor}@c.us"
    r = client.post(
        "/webhook?secret=test-secret-webhook-key",
        json={"event": "message", "payload": {"id": "msg-2", "from": chat_id, "body": "", "hasMedia": False, "fromMe": False}},
    )
    assert r.json()["status"] == "diabaikan_tanpa_konten"


# =========================================================================
# BUG: gender detector tidak kenal nama Indonesia-Kristen/Barat umum
# =========================================================================
@pytest.mark.parametrize("nama,harapan", [
    ("Delia Yuhana", "Ibu"),
    ("Muarif", "Bapak"),
    ("Yafi Hidayatullah", "Bapak"),
    ("Natalia Putri", "Ibu"),
    ("Ahmad Fauzi", "Bapak"),
])
def test_gender_detector(nama, harapan):
    assert deteksi_sapaan_gender(nama) == harapan


# =========================================================================
# BUG: menu "5. Hubungi admin" tidak berfungsi karena "admin" dianggap sapaan
# =========================================================================
@pytest.mark.parametrize("teks,harapan", [
    ("hubungi admin", False),
    ("admin", False),
    ("kontak admin", False),
    ("halo admin", True),
    ("assalamualaikum", True),
])
def test_is_sapaan_tidak_menelan_hubungi_admin(teks, harapan):
    assert _is_sapaan(teks) is harapan


def test_hubungi_admin_end_to_end(nomor_baru, kirim_pesan):
    nomor = nomor_baru()
    resp, balasan, _ = kirim_pesan(nomor, "hubungi admin")
    assert resp["intent"] == "handoff_admin_prompt"


# =========================================================================
# BUG: curhat panjang yang kebetulan menyebut "donasi" salah dianggap
# memilih opsi 4 (Donasi) dari menu 1-4.
# =========================================================================
def test_pilih_program_kalimat_panjang_direprompt(nomor_baru, kirim_pesan):
    nomor = nomor_baru()
    kirim_pesan(nomor, "saya mau donasi")
    resp, balasan, _ = kirim_pesan(nomor, "loh kok gak paham saya mau donasi")
    assert resp["intent"] == "pilih_program_reprompt"


def test_pilih_program_balasan_pendek_tetap_jalan(nomor_baru, kirim_pesan):
    nomor = nomor_baru()
    kirim_pesan(nomor, "saya mau donasi")
    resp, balasan, _ = kirim_pesan(nomor, "infak")
    assert resp["intent"] == "pilih_program_selesai"
    assert "Infak Rutin" in balasan


def test_pilih_program_kata_normal_tidak_ketangkap_zakat_mal(nomor_baru, kirim_pesan):
    """'normal' mengandung substring 'mal' - harus TIDAK dianggap memilih Zakat Mal
    (reprompt-nya sendiri MEMANG menyebut "Zakat Mal" sebagai salah satu opsi
    menu, jadi yang diperiksa adalah intent-nya, bukan isi teksnya)."""
    nomor = nomor_baru()
    kirim_pesan(nomor, "saya mau donasi")
    resp, balasan, _ = kirim_pesan(nomor, "oh gitu normal ya")
    assert resp["intent"] == "pilih_program_reprompt"


# =========================================================================
# BUG: kata "batal" tidak dibalas pesan pembatalan yang jelas (ada 2 blok
# kode duplikat yang mereset status diam-diam sebelum sempat sampai ke
# penanganan is_batal yang benar).
# =========================================================================
def test_batal_dari_pilih_program(nomor_baru, kirim_pesan):
    nomor = nomor_baru()
    kirim_pesan(nomor, "saya mau donasi")
    resp, balasan, _ = kirim_pesan(nomor, "batal")
    assert resp["intent"] == "batal_sesi"


def test_batal_dari_nunggu_bukti_transfer(nomor_baru, kirim_pesan):
    nomor = nomor_baru()
    kirim_pesan(nomor, "saya mau donasi")
    kirim_pesan(nomor, "infak")
    resp, balasan, _ = kirim_pesan(nomor, "batal")
    assert resp["intent"] == "batal_sesi"


# =========================================================================
# BUG: kata "saya"/"nya" dianggap konfirmasi "Ya" ke admin (substring "ya").
# =========================================================================
def test_saya_tidak_dianggap_konfirmasi_ya(nomor_baru, kirim_pesan):
    nomor = nomor_baru()
    kirim_pesan(nomor, "info beasiswa")
    kirim_pesan(nomor, "2")  # pilih OTA Palestina -> masuk TANYA_PROGRAM_DETAIL
    resp, balasan, semua = kirim_pesan(nomor, "saya mau donasi")
    assert resp["intent"] != "handoff_admin_success"


# =========================================================================
# BUG: user retraksi ("eh tidak jadi") langsung setelah "ya" ke admin tidak
# tersampaikan ke admin - admin sudah terlanjur dapat notifikasi.
# =========================================================================
def test_retraksi_admin_mengirim_notifikasi_susulan(nomor_baru, kirim_pesan):
    nomor = nomor_baru()
    kirim_pesan(nomor, "hubungi admin")
    resp_ya, _, semua_ya = kirim_pesan(nomor, "ya")
    assert resp_ya["intent"] == "handoff_admin_success"
    assert any("Ada permohonan dari" in teks for _, teks in semua_ya)

    resp_batal, _, semua_batal = kirim_pesan(nomor, "eh tidak jadi deh")
    assert resp_batal["intent"] == "handoff_admin_retraksi"
    assert any("PEMBATALAN" in teks for _, teks in semua_batal)


def test_pesan_setelah_ya_bukan_retraksi_diproses_normal(nomor_baru, kirim_pesan):
    nomor = nomor_baru()
    kirim_pesan(nomor, "hubungi admin")
    kirim_pesan(nomor, "ya")
    resp, balasan, _ = kirim_pesan(nomor, "info beasiswa")
    assert resp["intent"] == "info_beasiswa"


# =========================================================================
# BUG: laporan "sudah transfer X untuk kategori" dianggap niat donasi baru.
# =========================================================================
def test_lapor_sudah_transfer_dengan_kategori(nomor_baru, kirim_pesan):
    nomor = nomor_baru()
    resp, balasan, _ = kirim_pesan(nomor, "sudah transfer 100000 untuk zakat mal")
    assert resp["intent"] == "lapor_transfer_minta_resi"
    assert "Zakat Mal" in balasan


# =========================================================================
# BUG: menu "info beasiswa" tidak punya status FSM sendiri - angka 1-4
# lanjutannya kebablasan dicocokkan ke shortcut menu utama global.
# =========================================================================
def test_menu_beasiswa_punya_nomor_sendiri(nomor_baru, kirim_pesan):
    nomor = nomor_baru()
    kirim_pesan(nomor, "info beasiswa")
    resp, balasan, _ = kirim_pesan(nomor, "2")
    assert resp["intent"] == "detail_program_response"
    assert "PALESTINA" in balasan.upper()


# =========================================================================
# FITUR: sapaan waktu (pagi/siang/sore/malam) di-echo balik di balasan bot.
# =========================================================================
@pytest.mark.parametrize("waktu", ["pagi", "siang", "sore", "malam"])
def test_sapaan_waktu_di_echo(nomor_baru, kirim_pesan, waktu):
    nomor = nomor_baru()
    resp, balasan, _ = kirim_pesan(nomor, f"selamat {waktu}")
    assert f"Selamat {waktu}" in balasan


def test_sapaan_polos_tetap_generik():
    hasil = susun_balasan("assalamualaikum", nama_pengirim="Tester")
    assert "Selamat" not in hasil["reply"].split("!")[0]


# =========================================================================
# BUG: "ingin berdonasi" diarahkan ke intent lama tanpa nomor rekening.
# =========================================================================
def test_ingin_donasi_menampilkan_rekening():
    assert klasifikasi_pesan("ingin berdonasi") == "ingin_donasi"
    hasil = susun_balasan("ingin berdonasi", nama_pengirim="Tester")
    assert "7099400409" in hasil["reply"]
