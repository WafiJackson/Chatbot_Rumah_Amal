"""
Setup bersama untuk seluruh test suite - dijalankan SEBELUM modul app
manapun di-import, supaya env var (terutama DB_PATH) sudah benar sejak
awal. Test suite ini TIDAK PERNAH menyentuh app/donatur.db (database
development) atau data produksi - setiap sesi pytest memakai file SQLite
sementara sendiri yang otomatis dihapus setelah selesai.
"""
import os
import sys
import tempfile

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()

os.environ.setdefault("DB_PATH", _tmp_db.name)
os.environ.setdefault("WAHA_API_KEY", "test-secret-waha-key")
os.environ.setdefault("WEBHOOK_SECRET", "test-secret-webhook-key")
os.chdir(APP_DIR)

import pytest
from fastapi.testclient import TestClient

import main as main_module
import routes.bot_webhook as bot_webhook
from services import state_manager

WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]

_pesan_terkirim = []


def _fake_send_message_to_waha(chat_id, text, session_name="default", catat_log=True):
    _pesan_terkirim.append((chat_id, text))


def _fake_send_whatsapp_reply(chat_id, text, session_name="default"):
    _pesan_terkirim.append((chat_id, text))


bot_webhook.send_message_to_waha = _fake_send_message_to_waha
bot_webhook.send_whatsapp_reply = _fake_send_whatsapp_reply


@pytest.fixture
def client():
    return TestClient(main_module.app)


@pytest.fixture
def kirim_pesan(client):
    """Helper: kirim satu pesan webhook simulasi & kembalikan (response_json, balasan_ke_user, semua_pesan_terkirim)."""
    _counter = {"n": 0}

    def _kirim(nomor: str, body: str, pushname: str = "Tester", has_media: bool = False, msg_id: str | None = None):
        _counter["n"] += 1
        chat_id = f"{nomor}@c.us"
        _pesan_terkirim.clear()
        resp = client.post(
            f"/webhook?secret={WEBHOOK_SECRET}",
            json={
                "event": "message",
                "session": "default",
                "payload": {
                    "id": msg_id or f"true_{chat_id}_M{_counter['n']}",
                    "from": chat_id,
                    "body": body,
                    "hasMedia": has_media,
                    "fromMe": False,
                    "pushname": pushname,
                },
            },
        )
        balasan_ke_user = ""
        for tujuan, teks in _pesan_terkirim:
            if tujuan == chat_id:
                balasan_ke_user = teks
        return resp.json(), balasan_ke_user, list(_pesan_terkirim)

    return _kirim


import itertools

_nomor_counter = itertools.count(1)


@pytest.fixture
def nomor_baru():
    """Nomor WA simulasi baru & bersih (status di-reset) untuk satu test.

    Counter GLOBAL lintas-test (bukan reset per test) - kalau per-test,
    banyak test yang cuma memanggil sekali akan menghasilkan nomor yang
    SAMA PERSIS, membuat msg_id antar-test ikut bentrok dan salah kena
    deduplikasi PROCESSED_MSG_IDS (yang memang sengaja global, bertahan
    sepanjang proses server)."""

    def _buat():
        n = next(_nomor_counter)
        nomor = f"62899{n:08d}"
        state_manager.reset_status(nomor)
        return nomor

    return _buat
