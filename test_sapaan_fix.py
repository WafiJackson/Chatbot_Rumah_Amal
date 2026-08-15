"""
Self-check untuk fix bug "Kak Kak" (sapaan dobel saat nama pengirim tidak
diketahui dan fallback-nya kebetulan sama dengan kata sapaan).
Jalankan: python test_sapaan_fix.py
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, "app")

from admin_scripts import ambil_balasan
from routes.bot_webhook import _sapaan_dengan_nama

# 1. Kasus asli bug: nama_pengirim fallback "Kak" (WAHA tidak kirim pushname)
balasan = ambil_balasan("sapaan", nama_pengirim="Kak")
assert "Kak Kak" not in balasan, f"Regresi bug 'Kak Kak' terdeteksi: {balasan!r}"
assert "Assalamu'alaikum Kak!" in balasan, f"Sapaan tunggal tidak sesuai: {balasan!r}"

# 2. Nama asli tetap tampil normal, tidak boleh ikut ke-strip
balasan_budi = ambil_balasan("sapaan", nama_pengirim="Budi Santoso")
assert "Bapak Budi Santoso" in balasan_budi, f"Nama asli hilang: {balasan_budi!r}"

# 3. Nama kosong / None tidak boleh menyisakan spasi ganda atau "None"
balasan_kosong = ambil_balasan("sapaan", nama_pengirim=None)
assert "Kak Kak" not in balasan_kosong and "None" not in balasan_kosong

# 4. Helper _sapaan_dengan_nama() di bot_webhook.py (dipakai di 4 lokasi FSM)
assert _sapaan_dengan_nama("Kak", "Kak") == "Kak"
assert _sapaan_dengan_nama("Bapak", "Budi") == "Bapak Budi"
assert _sapaan_dengan_nama("Kak", "") == "Kak"
assert _sapaan_dengan_nama("Kak", None) == "Kak"
assert _sapaan_dengan_nama("Ibu", "  Siti  ") == "Ibu Siti"

print("OK - semua self-check sapaan lulus, bug 'Kak Kak' tidak regresi.")
