"""
Self-check untuk bug FSM ter-reset diam-diam saat user mengetik nominal
yang mengandung angka 0 (mis. "Yafi 90000") di tengah alur konfirmasi
donasi. Root cause: KATA_KUNCI_OVERRIDE dulu berisi token pendek "0"/"p"
yang dicocokkan pakai substring, jadi COCOK dengan "90000" dan sesi
donasi ter-reset ke IDLE sebelum sempat diproses sebagai konfirmasi.

Gemini API di-mock supaya lolos tanpa API key / kuota asli (persis skenario
produksi yang memicu bug ini: Gemini 429 quota exceeded).
Jalankan: python test_fsm_unlock_fix.py
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, "app")

from unittest.mock import patch
from fastapi.testclient import TestClient

import services.llm_agent as llm_agent
from main import app

client = TestClient(app)


def kirim(phone: str, pesan: str, msg_id: str, pushname: str = "Yafi Hidayatullah") -> dict:
    payload = {
        "event": "message",
        "session": "default",
        "payload": {
            "id": msg_id,
            "from": f"{phone}@c.us",
            "fromMe": False,
            "pushname": pushname,
            "body": pesan,
            "type": "chat",
        },
    }
    return client.post("/webhook", json=payload).json()


with patch.object(llm_agent, "_panggil_gemini_api", return_value=""), \
     patch("routes.bot_webhook.send_message_to_waha", return_value=None):
    phone = "6281300000999"
    r1 = kirim(phone, "halo", "u1")
    r2 = kirim(phone, "2", "u2")
    r3 = kirim(phone, "1", "u3")
    r4 = kirim(phone, "Yafi 90000", "u4")

assert r1["intent"] == "sapaan", r1
assert r2["intent"] == "pilih_program_prompt", r2
assert r3["intent"] == "pilih_program_selesai", r3
assert r4["intent"] == "konfirmasi_sukses", (
    f"Regresi bug FSM-unlock terdeteksi: nominal berangka 0 ('Yafi 90000') "
    f"seharusnya masuk sebagai konfirmasi donasi, bukan {r4!r}"
)

print("OK - self-check FSM-unlock lulus, nominal berangka 0 tidak lagi mereset sesi donasi.")
