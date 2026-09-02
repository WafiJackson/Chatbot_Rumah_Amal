"""
Regression test untuk bug kategori donasi via Web Chat (dilaporkan 2 Sep 2026):
user menyatakan niat donasi dengan kategori spesifik ("saya ingin berdonasi
zakat mal min"), tapi kategori itu hilang begitu saja - reply generik tanpa
kategori, dan resi yang diunggah setelahnya cuma ditebak asal oleh AI baca
gambar (seringkali salah, mis. default ke "Infak Rutin"/"UMUM").

Akar masalahnya ada di dua tempat:
1. admin_scripts.py klasifikasi_pesan() - frasa niat donasi GENERIK ("ingin
   berdonasi") dicek SEBELUM kategori spesifik ("zakat mal"), jadi kalimat
   yang mengandung keduanya salah ke-klasifikasi sebagai niat generik saja.
2. public_web.py upload_resi() - tidak pernah membaca kategori yang sudah
   disebutkan di sesi chat sebelumnya sama sekali, murni mengandalkan
   tebakan AI baca gambar resi.
"""
import io

import routes.public_web as public_web


def _mock_ocr(monkeypatch, nama=None, nominal=None, program="UMUM"):
    monkeypatch.setattr(
        public_web,
        "ekstrak_resi_vision",
        lambda image_bytes, caption="": {"nama": nama, "nominal": nominal, "program": program},
    )


def test_niat_donasi_generik_menampilkan_katalog(client):
    resp = client.post("/api/web-chat", json={"message": "saya ingin berdonasi min"})
    reply = resp.json()["reply"]
    assert "Zakat Mal" in reply
    assert "Infak Rutin" in reply
    # Belum boleh langsung dikasih nomor rekening tanpa kategori jelas.
    assert "7099400409" not in reply


def test_niat_donasi_dengan_kategori_spesifik_disebutkan_di_reply(client):
    resp = client.post("/api/web-chat", json={"message": "saya ingin berdonasi zakat mal min"})
    reply = resp.json()["reply"]
    assert "Zakat Mal" in reply
    assert "7099400409" in reply


def test_kategori_dari_chat_terbawa_ke_resi_upload(client, monkeypatch, baca_transaksi_terakhir):
    _mock_ocr(monkeypatch, nama="Yafi Hidayatullah", nominal=84000, program="UMUM")

    # 1. User menyatakan niat donasi zakat mal secara eksplisit di chat.
    resp1 = client.post("/api/web-chat", json={"message": "saya ingin berdonasi zakat mal min"})
    assert "Zakat Mal" in resp1.json()["reply"]

    # 2. Lalu unggah resi TANPA menyebut kategori apa pun di caption -
    # kategori seharusnya diambil dari niat yang sudah dinyatakan di langkah 1,
    # BUKAN dari tebakan OCR ("UMUM") yang sengaja di-mock ambigu di atas.
    resp2 = client.post(
        "/api/web-chat/upload-resi",
        data={"wa_number": "081269666776", "caption": ""},
        files={"file": ("resi.jpg", io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 6000), "image/jpeg")},
    )
    assert resp2.status_code == 200

    baris = baca_transaksi_terakhir("081269666776")
    assert baris is not None
    assert baris["kode_program"] == "ZKT-MAL"
    assert baris["status_verifikasi"] == "pending"


def test_kategori_tidak_bocor_ke_resi_donasi_tanpa_kategori(client, monkeypatch, baca_transaksi_terakhir):
    """Kategori yang tersimpan di sesi HARUS dibersihkan setelah dipakai sekali -
    donasi kedua yang tidak menyebut kategori apa pun tidak boleh diam-diam
    mewarisi kategori dari donasi pertama di sesi web yang sama."""
    _mock_ocr(monkeypatch, nama="Budi", nominal=50000, program="UMUM")

    client.post("/api/web-chat", json={"message": "saya ingin berdonasi zakat mal min"})
    client.post(
        "/api/web-chat/upload-resi",
        data={"wa_number": "081200011122", "caption": ""},
        files={"file": ("resi1.jpg", io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 6000), "image/jpeg")},
    )

    # Resi kedua, tanpa niat kategori apa pun dinyatakan lagi di antaranya.
    client.post(
        "/api/web-chat/upload-resi",
        data={"wa_number": "081200011122", "caption": ""},
        files={"file": ("resi2.jpg", io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 6000), "image/jpeg")},
    )

    baris = baca_transaksi_terakhir("081200011122")
    assert baris is not None
    # BUKAN "ZKT-MAL" (tidak boleh bocor dari transaksi sebelumnya). Jatuh ke
    # "INF-RUTIN", bukan "UMUM" - state_manager.simpan_transaksi_final()
    # SENGAJA menimpa kode_program "UMUM"/"Donasi" apa pun dengan fallback
    # "INF-RUTIN" (lihat state_manager.py sekitar baris 278) kalau tidak ada
    # target_program tersimpan di sesi WhatsApp untuk nomor itu - inilah akar
    # asli kenapa OCR yang menebak "UMUM" selalu berakhir sebagai "Infak
    # Rutin" di dashboard, bukan cuma tebakan acak. Ini perilaku LAMA & sudah
    # ada sebelum perbaikan sesi kategori di atas - dibiarkan apa adanya di
    # sini karena fungsinya dipakai bersama alur WhatsApp juga.
    assert baris["kode_program"] == "INF-RUTIN"


def test_resi_dengan_nominal_tidak_terbaca_tetap_tersimpan(client, monkeypatch, baca_transaksi_terakhir):
    """Bug lama: kalau OCR gagal baca nominal, transaksi TIDAK tersimpan sama
    sekali walau pesan notifikasi ke admin bilang 'cek di dashboard' - resi
    lenyap tanpa jejak apa pun untuk dikoreksi manual."""
    _mock_ocr(monkeypatch, nama=None, nominal=None, program="UMUM")

    resp = client.post(
        "/api/web-chat/upload-resi",
        data={"wa_number": "081233344455", "caption": ""},
        files={"file": ("resi.jpg", io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 6000), "image/jpeg")},
    )
    assert resp.status_code == 200

    baris = baca_transaksi_terakhir("081233344455")
    assert baris is not None
    assert baris["status_verifikasi"] == "pending"
