"""
Bug dilaporkan 17 Sep 2026 (screenshot dashboard admin): kolom Nomor WA
menampilkan nilai yang jelas bukan nomor telepon - string literal "status",
dan ID WhatsApp internal panjang seperti "61534046797883" (raw @lid yang
gagal diterjemahkan _dapatkan_nomor_hp_asli()). Akar masalahnya:
normalisasi_no_wa() (state_manager.py) cuma menukar awalan "628"->"0" tanpa
pernah memvalidasi isinya - nilai APA PUN lolos tersimpan apa adanya ke
kolom no_wa.
"""
from services import state_manager


def test_no_wa_bukan_angka_ditolak(baca_transaksi_terakhir):
    hasil = state_manager.simpan_transaksi_final(
        "status", "Test", 50000, kode_program="INF-RUTIN", status_verifikasi="pending",
    )
    assert hasil is None
    assert baca_transaksi_terakhir("status") is None


def test_no_wa_terlalu_pendek_ditolak(baca_transaksi_terakhir):
    hasil = state_manager.simpan_transaksi_final(
        "12345", "Test", 50000, kode_program="INF-RUTIN", status_verifikasi="pending",
    )
    assert hasil is None


def test_no_wa_valid_tetap_tersimpan(baca_transaksi_terakhir):
    hasil = state_manager.simpan_transaksi_final(
        "081200099888", "Test Valid", 50000, kode_program="INF-RUTIN", status_verifikasi="pending",
    )
    assert hasil is not None
    baris = baca_transaksi_terakhir("081200099888")
    assert baris is not None
    assert baris["nama_donatur"] == "Test Valid"


def test_no_wa_lid_panjang_tetap_tersimpan_karena_masih_donasi_asli(baca_transaksi_terakhir):
    """ID WhatsApp mentah (@lid) yang gagal diterjemahkan TETAP harus
    tersimpan (bukan ditolak) - itu tetap donasi asli yang benar-benar
    terjadi, cuma nomor teleponnya tidak diketahui. Menolaknya akan
    mengulang bug lama "resi hilang tanpa jejak"."""
    hasil = state_manager.simpan_transaksi_final(
        "61534046797883", "Test LID", 50000, kode_program="INF-RUTIN", status_verifikasi="pending",
    )
    assert hasil is not None
