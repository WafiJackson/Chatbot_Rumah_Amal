import sys

# Cegah UnicodeEncodeError saat print()/logging menulis emoji ke konsol non-UTF-8
# (mis. cp1252 di Windows) - tanpa ini, satu balasan berisi emoji bisa membuat
# seluruh request webhook gagal (500) meski isi balasannya sendiri valid.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure") and (_stream.encoding or "").lower() != "utf-8":
        _stream.reconfigure(encoding="utf-8", errors="replace")

import uvicorn
from fastapi import FastAPI
from routes import bot_webhook
from services import state_manager

from services.logger import logger

# Inisialisasi SQLite State Store
state_manager.init_db()
logger.info("[Startup] Bot Rumah Amal USK Modular Aktif & Production Logger Siap.")

app = FastAPI(
    title="Rumah Amal Bot API",
    description="Sistem Ter-modularisasi Stateful & Hybrid",
    version="3.0.0"
)

# Menyambungkan rute webhook dari folder routes (/api/webhook dan /webhook)
app.include_router(bot_webhook.router)


@app.get("/")
def root():
    logger.info("Health check endpoint dipanggil.")
    return {"status": "online", "message": "Bot Rumah Amal Modular Aktif."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)