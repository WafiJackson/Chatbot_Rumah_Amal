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
def test_ingin_donasi_generik_menampilkan_katalog_bukan_rekening_langsung():
    """Diperbarui 2 Sep 2026: niat donasi GENERIK (tanpa kategori disebutkan)
    sengaja tidak lagi langsung dikasih nomor rekening - tanpa kategori yang
    jelas, resi yang diunggah setelahnya cuma bisa ditebak asal oleh AI baca
    gambar. Sekarang menampilkan katalog kategori dulu (lihat
    QA_SCRIPT["ingin_donasi"] di admin_scripts.py)."""
    assert klasifikasi_pesan("ingin berdonasi") == "ingin_donasi"
    hasil = susun_balasan("ingin berdonasi", nama_pengirim="Tester")
    assert "7099400409" not in hasil["reply"]
    assert "Zakat Mal" in hasil["reply"]


def test_ingin_donasi_dengan_kategori_spesifik_langsung_ke_rekening():
    """Kalau kategori SUDAH disebutkan eksplisit di kalimat yang sama, tidak
    perlu ditanya ulang lewat katalog - langsung beri nomor rekening,
    sekaligus melacak kode_program_donasi ke sesi (dipakai upload_resi() di
    public_web.py sebagai sinyal kategori, bukan tebakan OCR)."""
    hasil = susun_balasan("saya ingin berdonasi zakat mal min", nama_pengirim="Tester")
    assert "Zakat Mal" in hasil["reply"]
    assert "7099400409" in hasil["reply"]
    assert hasil["kode_program_donasi"] == "ZKT-MAL"


# =========================================================================
# KEPUTUSAN 29 Agustus: resi WhatsApp yang TIDAK didahului percakapan
# eksplisit (mis. "saya mau infak" dulu) HARUS selalu "pending" menunggu
# admin - walau OCR berhasil membaca kategori dari catatan di struk resinya
# sendiri. Sebelumnya OCR yang berhasil membaca catatan langsung dianggap
# "program diketahui" dan auto-validated, walau user tidak pernah
# menyatakan niatnya lewat chat - celah ini bisa disalahgunakan resi apapun
# (termasuk yang dimanipulasi) dengan catatan yang "kebetulan" terbaca.
# =========================================================================
def test_resi_dingin_dengan_ocr_tetap_pending(nomor_baru, kirim_pesan, mock_ocr_resi, baca_transaksi_terakhir):
    nomor = nomor_baru()
    mock_ocr_resi(nama="Vera Fitria", nominal="2000", program="INF-RUTIN")
    resp, balasan, semua = kirim_pesan(nomor, has_media=True)
    assert resp["intent"] == "konfirmasi_sukses"

    # DB menyimpan format lokal "0..." (lihat _dapatkan_nomor_hp_asli), bukan "62..." mentah.
    baris = baca_transaksi_terakhir("0" + nomor[2:])
    assert baris is not None
    assert baris["status_verifikasi"] == "pending"
    assert baris["kode_program"] == "INF-RUTIN"  # tetap terisi sbg dugaan, cuma statusnya pending

    # Admin harus diberi tahu ini masih perlu divalidasi manual
    assert any("RESI PERLU DIVALIDASI" in teks for _, teks in semua)
    # Balasan ke user harus jujur (tidak mengklaim kepastian program)
    assert "untuk program" not in balasan


def test_resi_setelah_pilih_program_di_chat_tetap_validated(nomor_baru, kirim_pesan, mock_ocr_resi, baca_transaksi_terakhir):
    nomor = nomor_baru()
    kirim_pesan(nomor, "saya mau donasi")
    kirim_pesan(nomor, "infak")  # eksplisit pilih program lewat chat
    mock_ocr_resi(nama="Fauzan", nominal="50000", program="UMUM")  # OCR gagal baca kategori, TIDAK masalah
    resp, balasan, _ = kirim_pesan(nomor, has_media=True)
    assert resp["intent"] == "konfirmasi_sukses"

    baris = baca_transaksi_terakhir("0" + nomor[2:])
    assert baris["status_verifikasi"] == "validated"
    assert baris["kode_program"] == "INF-RUTIN"
    assert "Infak Rutin" in balasan


# =========================================================================
# BUG (ditemukan 29 Agustus saat menyelidiki resi yang tetap tervalidasi):
# jalur "FORMULIR INFAK RUTIN" (bot_webhook.py FAST-PATH 5) memanggil
# simpan_transaksi_final() TANPA status_verifikasi sama sekali, diam-diam
# memakai default lama "validated" - satu pesan dingin berisi kata kunci
# "FORMULIR INFAK RUTIN" + nama + nominal langsung tervalidasi tanpa
# pernah melalui menu pilih program. Diperbaiki jadi selalu "pending",
# dan status_verifikasi di simpan_transaksi_final() dijadikan wajib diisi
# (tanpa default) supaya kelas bug ini tidak terulang di pemanggil baru.
# =========================================================================
def test_formulir_infak_dingin_tetap_pending(nomor_baru, kirim_pesan, baca_transaksi_terakhir):
    nomor = nomor_baru()
    resp, balasan, semua = kirim_pesan(nomor, "FORMULIR INFAK RUTIN\nNama: Budi\nInstansi/Pekerjaan: Dosen\nNominal Komitmen: 25000")

    baris = baca_transaksi_terakhir("0" + nomor[2:])
    if baris is not None:  # hanya lanjut cek kalau ekstraksi nama/nominal berhasil
        assert baris["status_verifikasi"] == "pending"
        assert any("FORMULIR PERLU DIVALIDASI" in teks for _, teks in semua)


# =========================================================================
# BUG (ditemukan 29 Agustus): reset_status() tidak pernah membersihkan
# target_program lama - transaksi yang SUDAH SELESAI (mis. "Zakat Mal")
# nyangkut di sesi selamanya dan "bocor" ke resi BARU yang sama sekali
# tidak berhubungan, membuatnya salah dianggap program_dari_sesi=True dan
# lolos auto-validated dengan kategori basi.
# =========================================================================
def test_reset_status_membersihkan_target_program_lama(nomor_baru, kirim_pesan, mock_ocr_resi, baca_transaksi_terakhir):
    nomor = nomor_baru()

    # Sesi 1: pilih Zakat Mal eksplisit lewat chat, selesaikan transaksinya
    kirim_pesan(nomor, "saya mau donasi")
    kirim_pesan(nomor, "zakat mal")
    mock_ocr_resi(nama="Yafi", nominal="500000", program="UMUM")
    kirim_pesan(nomor, has_media=True)

    from services import state_manager
    sesi = state_manager.get_session("0" + nomor[2:])
    assert sesi["target_program"] is None, "target_program lama harus bersih setelah transaksi selesai"

    # Sesi 2: BARU, TANPA chat sama sekali - resi dingin yang tidak berhubungan
    mock_ocr_resi(nama="Yafi", nominal="84000", program="UMUM")
    resp, balasan, _ = kirim_pesan(nomor, has_media=True)

    baris = baca_transaksi_terakhir("0" + nomor[2:])
    assert baris["status_verifikasi"] == "pending"  # BUKAN ikut "validated" warisan sesi lama
    assert baris["kode_program"] != "ZKT-MAL"  # tidak boleh mewarisi kategori basi


# =========================================================================
# BUG (ditemukan 29 Agustus): pesan yang kena rate limit (>20/menit) lenyap
# TANPA JEJAK sama sekali - tidak dicatat ke Log Bot, tidak ada balasan
# apapun ke user. Diperbaiki: tetap dicatat, dan user diberi tahu jujur
# untuk kirim ulang nanti (bukan dijanjikan otomatis dibalas - server
# 1-worker tidak bisa "menunggu" tanpa membekukan semua user lain).
# =========================================================================
def test_pesan_kena_rate_limit_tetap_tercatat_dan_diberi_tahu(nomor_baru, kirim_pesan):
    from services import state_manager
    nomor = nomor_baru()

    # "halo" sengaja dipakai (bukan teks bebas) - dijawab lewat fast-path
    # sapaan langsung tanpa panggilan Gemini, supaya test ini tetap cepat
    # dan deterministik (tidak tergantung kuota/jaringan API sungguhan).
    hasil = [kirim_pesan(nomor, "halo") for _ in range(22)]

    # Pesan ke-21 (index 20, pertama kali melampaui batas) HARUS dapat
    # peringatan "mohon tunggu". Pesan ke-22 (index 21) TIDAK - jendela
    # cooldown 20 detik sengaja mencegah spam balasan berulang.
    resp_21, balasan_21, _ = hasil[20]
    resp_22, balasan_22, _ = hasil[21]
    assert resp_21["status"] == "rate_limit_exceeded"
    assert "tunggu" in balasan_21.lower()
    assert resp_22["status"] == "rate_limit_exceeded"
    assert balasan_22 == ""  # cooldown - tidak dobel peringatan

    baris = state_manager.ambil_pesan_kontak("whatsapp", "0" + nomor[2:], limit=50)
    assert len(baris) == 22, "pesan yang kena rate limit harus tetap tercatat ke Log Bot"


# =========================================================================
# BUG (ditemukan 30 Agustus di WA asli): resi yang dikirim SAAT status FSM
# sedang menunggu pilihan menu (PILIH_PROGRAM) ditangkap oleh logika
# pencocokan menu (yang cuma cek teks), gagal cocok karena foto tidak ada
# teksnya, dan berakhir cuma dibalas "belum menangkap pilihannya" - resi-
# nya sendiri TIDAK PERNAH sampai ke logika baca resi/simpan transaksi,
# hilang tanpa jejak sama sekali (tidak ada baris transaksi tersimpan).
# Kejadian nyata: user tidak sengaja memicu PILIH_PROGRAM (pesan berisi
# kata "donasi" tanpa maksud), lalu kirim resi - resi itu lenyap total.
# =========================================================================
def test_resi_saat_pilih_program_tidak_hilang(nomor_baru, kirim_pesan, mock_ocr_resi, baca_transaksi_terakhir):
    nomor = nomor_baru()
    kirim_pesan(nomor, "saya mau donasi")  # masuk PILIH_PROGRAM
    mock_ocr_resi(nama="Budi", nominal="50000", program="UMUM")
    resp, balasan, _ = kirim_pesan(nomor, has_media=True)  # resi dikirim SAAT masih PILIH_PROGRAM

    assert resp["intent"] == "konfirmasi_sukses"  # bukan "pilih_program_reprompt"
    baris = baca_transaksi_terakhir("0" + nomor[2:])
    assert baris is not None, "resi yang dikirim saat PILIH_PROGRAM tidak boleh hilang tanpa tersimpan"
    assert baris["status_verifikasi"] == "pending"


def test_resi_saat_menunggu_admin_tidak_hilang(nomor_baru, kirim_pesan, mock_ocr_resi, baca_transaksi_terakhir):
    nomor = nomor_baru()
    kirim_pesan(nomor, "hubungi admin")  # masuk MENUNGGU_ADMIN
    mock_ocr_resi(nama="Budi", nominal="50000", program="UMUM")
    resp, balasan, _ = kirim_pesan(nomor, has_media=True)

    assert resp["intent"] == "konfirmasi_sukses"
    baris = baca_transaksi_terakhir("0" + nomor[2:])
    assert baris is not None, "resi yang dikirim saat MENUNGGU_ADMIN tidak boleh hilang tanpa tersimpan"
