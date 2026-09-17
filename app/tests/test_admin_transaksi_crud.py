"""
Diminta 17 Sep 2026: admin harus tetap bisa mengoreksi kategori/status DAN
menghapus transaksi apa pun secara permanen, walau statusnya sudah
'validated' - khawatir bot/admin pernah keliru memvalidasi, atau ada
ketentuan lain yang mengharuskan penghapusan data.
"""
from services import state_manager


def _buat_transaksi_tervalidasi(no_wa="081200077766"):
    return state_manager.simpan_transaksi_final(
        no_wa, "Donatur Uji", 50000, kode_program="INF-RUTIN", status_verifikasi="validated",
    )


def test_kategori_transaksi_tervalidasi_tetap_bisa_dikoreksi(admin_login, baca_transaksi_terakhir):
    trx_id = _buat_transaksi_tervalidasi("081200077701")
    resp = admin_login.post(
        f"/admin/transactions/{trx_id}/status",
        data={"status": "validated", "kode_program": "ZKT-MAL"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "sukses"
    baris = baca_transaksi_terakhir("081200077701")
    assert baris["kode_program"] == "ZKT-MAL"
    assert baris["status_verifikasi"] == "validated"


def test_transaksi_tervalidasi_bisa_dikembalikan_ke_menunggu(admin_login, baca_transaksi_terakhir):
    trx_id = _buat_transaksi_tervalidasi("081200077702")
    resp = admin_login.post(
        f"/admin/transactions/{trx_id}/status",
        data={"status": "pending"},
    )
    assert resp.status_code == 200
    baris = baca_transaksi_terakhir("081200077702")
    assert baris["status_verifikasi"] == "pending"


def test_hapus_transaksi_tervalidasi_berhasil(admin_login):
    trx_id = _buat_transaksi_tervalidasi("081200077703")
    resp = admin_login.post(f"/admin/transactions/{trx_id}/delete")
    assert resp.status_code == 200
    assert resp.json()["status"] == "sukses"

    # Benar-benar hilang dari database, bukan cuma disembunyikan.
    resp2 = admin_login.post(f"/admin/transactions/{trx_id}/delete")
    assert resp2.status_code == 404


def test_hapus_transaksi_tanpa_login_ditolak(client):
    trx_id = _buat_transaksi_tervalidasi("081200077704")
    resp = client.post(f"/admin/transactions/{trx_id}/delete")
    assert resp.status_code == 401


def test_hapus_transaksi_tidak_ada_mengembalikan_404(admin_login):
    resp = admin_login.post("/admin/transactions/9999999/delete")
    assert resp.status_code == 404
