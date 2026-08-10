# ==========================================
# PRODUCTION LOGGER - Logging System Rapi & Rotasi File
# ==========================================

import os
import sys
import logging
from logging.handlers import RotatingFileHandler

# Buat folder logs jika belum ada
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "app.log")

# Format Tampilan Log (Timestamp - Level - Component - Message)
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

# 1. Rotating File Handler (Max 5MB per file, simpan 5 file cadangan)
file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=5,
    encoding="utf-8"
)
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.INFO)

# 2. Console Handler (Untuk tampilan terminal/stdout)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
console_handler.setLevel(logging.INFO)

# 3. Logger Utama Aplikasi
logger = logging.getLogger("RumahAmalBot")
logger.setLevel(logging.INFO)

# Cegah handler ganda jika diajukan berulang kali
if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

def get_logger(name: str = None):
    if name:
        return logger.getChild(name)
    return logger
