import sys

# Cegah UnicodeEncodeError saat print()/logging menulis emoji ke konsol non-UTF-8
# (mis. cp1252 di Windows) - tanpa ini, satu balasan berisi emoji bisa membuat
# seluruh request webhook gagal (500) meski isi balasannya sendiri valid.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure") and (_stream.encoding or "").lower() != "utf-8":
        _stream.reconfigure(encoding="utf-8", errors="replace")

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from routes import bot_webhook, admin_web, public_web
from services import state_manager

from services.logger import logger

# Inisialisasi SQLite State Store
state_manager.init_db()

# Retensi log_percakapan (90 hari) - dijalankan tiap kali aplikasi start
# (bukan penjadwalan rutin sungguhan, tapi cukup untuk mencegah tabel ini
# tumbuh tanpa batas selamanya seperti sebelumnya).
try:
    _jumlah_dihapus = state_manager.bersihkan_log_percakapan_lama(hari=90)
    if _jumlah_dihapus:
        logger.info(f"[Startup] Membersihkan {_jumlah_dihapus} baris log_percakapan yang lebih tua dari 90 hari.")
except Exception as e:
    logger.warning(f"[Startup] Gagal membersihkan log_percakapan lama: {e}")

logger.info("[Startup] Bot Rumah Amal USK Modular Aktif & Production Logger Siap.")

app = FastAPI(
    title="Rumah Amal Bot API",
    description="Sistem Ter-modularisasi Stateful & Hybrid",
    version="3.0.0"
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Menyambungkan rute webhook dari folder routes (/api/webhook dan /webhook)
app.include_router(bot_webhook.router)

# Menyambungkan Admin Dashboard (/admin/...)
app.include_router(admin_web.router)

# Menyambungkan Web Chatbot publik (/ dan /api/web-chat)
app.include_router(public_web.router)


@app.get("/health")
def health():
    logger.info("Health check endpoint dipanggil.")
    return {"status": "online", "message": "Bot Rumah Amal Modular Aktif."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)