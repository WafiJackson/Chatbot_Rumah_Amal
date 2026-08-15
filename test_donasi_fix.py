"""
Self-check untuk 3 bug donasi yang ditemukan lewat log produksi:
1. PETA_NAMA NameError yang membuat doa fallback ke sapaan "Kak" generik
   walau gender sudah terdeteksi benar di awal percakapan.
2. Nominal hasil ekstraksi LLM (teks) tidak divalidasi sebelum disimpan,
   sehingga nilai kecil/halusinasi (mis. "5") bisa lolos tersimpan sebagai
   transaksi donasi.
Jalankan: python test_donasi_fix.py
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, "app")

from routes.bot_webhook import _dapatkan_doa_spesifik, _nominal_valid, PETA_NAMA

# 1. PETA_NAMA harus bisa diakses dari _dapatkan_doa_spesifik tanpa NameError,
#    dan nama donatur yang dioper harus benar-benar muncul di balasan doa
#    (bukan fallback generik yang kehilangan nama/sapaan).
balasan = _dapatkan_doa_spesifik("ZKT-MAL", nama_donatur="Bapak Yafi Hidayatullah", nominal_fmt="84.000")
assert "Bapak Yafi Hidayatullah" in balasan, f"Nama donatur hilang dari doa: {balasan!r}"
assert "Zakat Mal" in balasan, f"Nama program hilang dari doa: {balasan!r}"
assert PETA_NAMA.get("ZKT-MAL") == "Zakat Mal"

# 2. Nominal valid (angka murni, >= 1000) harus lolos
assert _nominal_valid("90000") == "90000"
assert _nominal_valid("Rp 500.000") == "500000"
assert _nominal_valid(90000) == "90000"

# 3. Nominal kecil/halusinasi/bukan angka harus ditolak (None), bukan
#    lolos tersimpan sebagai transaksi
assert _nominal_valid("5") is None, "Nominal kecil seharusnya ditolak, bukan lolos ke database"
assert _nominal_valid("0") is None
assert _nominal_valid("") is None
assert _nominal_valid(None) is None
assert _nominal_valid("abc") is None

print("OK - semua self-check donasi lulus (doa tidak lagi jatuh ke 'Kak', nominal kecil ditolak).")
