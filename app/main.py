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