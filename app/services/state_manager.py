import os
import re
import sqlite3
from datetime import datetime, timezone, timedelta

WIB = timezone(timedelta(hours=7))
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "donatur.db")


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Inisialisasi skema relational 3 tabel SQLite dan Seeder master_program."""
    with get_db_connection() as conn:
        # 1. TABEL master_program
        conn.execute("""
            CREATE TABLE IF NOT EXISTS master_program (
                kode_program TEXT PRIMARY KEY,
                nama_program TEXT,
                kategori TEXT
            )
        """)

        # Seeder master_program
        cursor = conn.execute("SELECT COUNT(*) FROM master_program")
        if cursor.fetchone()[0] == 0:
            conn.executemany("""
                INSERT INTO master_program (kode_program, nama_program, kategori)
                VALUES (?, ?, ?)
            """, [
                ('INF-RUTIN', 'Infak Rutin', 'Infak'),
                ('ZKT-MAL', 'Zakat Mal', 'Zakat'),
                ('ZKT-PENGHASILAN', 'Zakat Penghasilan', 'Zakat')
            ])

        # 2. TABEL transaksi_donasi (Clean Schema: tanpa kolom pekerjaan)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transaksi_donasi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                no_wa TEXT,
                nama_donatur TEXT,
                kode_program TEXT,
                nominal INTEGER,
                waktu_transaksi DATETIME
            )
        """)

        # 3. TABEL sesi_percakapan
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sesi_percakapan (
                no_wa TEXT PRIMARY KEY,
                status TEXT DEFAULT 'IDLE',
                target_program TEXT,
                waktu_update DATETIME
            )
        """)

        # Migration check: tambahkan kolom target_program jika database lama sudah ada
        cursor = conn.execute("PRAGMA table_info(sesi_percakapan)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "target_program" not in columns:
            conn.execute("ALTER TABLE sesi_percakapan ADD COLUMN target_program TEXT")

        conn.commit()



from services.supabase_client import (
    is_supabase_configured,
    get_status as supabase_get_status,
    update_status as supabase_update_status,
    reset_status as supabase_reset_status,
    get_session as supabase_get_session,
    simpan_transaksi_final as supabase_simpan_transaksi,
    ambil_riwayat_donasi as supabase_ambil_riwayat
)


def get_status(no_wa: str) -> str:
    """Mengembalikan status percakapan pengguna saat ini (default: 'IDLE')."""
    if not no_wa:
        return "IDLE"
    if is_supabase_configured():
        try:
            st = supabase_get_status(no_wa)
            if st and st != "IDLE":
                return st
        except Exception as e:
            print(f"[Supabase Fallback to SQLite - get_status] {e}")

    with get_db_connection() as conn:
        cursor = conn.execute("SELECT status FROM sesi_percakapan WHERE no_wa = ?", (no_wa,))
        row = cursor.fetchone()
        return row["status"] if row and row["status"] else "IDLE"


def update_status(no_wa: str, status_baru: str, target_program: str | None = None):
    """Memperbarui status percakapan pengguna di SQLite dan Supabase."""
    if not no_wa:
        return

    now_str = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")

    if is_supabase_configured():
        try:
            supabase_update_status(no_wa, status_baru, target_program)
        except Exception as e:
            print(f"[Supabase Fallback to SQLite - update_status] {e}")

    with get_db_connection() as conn:
        cursor = conn.execute("SELECT no_wa FROM sesi_percakapan WHERE no_wa = ?", (no_wa,))
        row = cursor.fetchone()
        if row:
            if target_program:
                conn.execute(
                    "UPDATE sesi_percakapan SET status = ?, target_program = ?, waktu_update = ? WHERE no_wa = ?",
                    (status_baru, target_program, now_str, no_wa)
                )
            else:
                conn.execute(
                    "UPDATE sesi_percakapan SET status = ?, waktu_update = ? WHERE no_wa = ?",
                    (status_baru, now_str, no_wa)
                )
        else:
            conn.execute(
                "INSERT INTO sesi_percakapan (no_wa, status, target_program, waktu_update) VALUES (?, ?, ?, ?)",
                (no_wa, status_baru, target_program, now_str)
            )
        conn.commit()


def reset_status(no_wa: str):
    """Mereset status percakapan pengguna ke 'IDLE'."""
    update_status(no_wa, "IDLE")


def get_session(no_wa: str) -> dict:
    """Mengambil informasi sesi lengkap (status dan target_program)."""
    if not no_wa:
        return {"no_wa": no_wa, "status": "IDLE", "target_program": None}

    if is_supabase_configured():
        try:
            sess = supabase_get_session(no_wa)
            if sess and sess.get("status") != "IDLE":
                return sess
        except Exception as e:
            print(f"[Supabase Fallback to SQLite - get_session] {e}")

    with get_db_connection() as conn:
        cursor = conn.execute("SELECT no_wa, status, target_program FROM sesi_percakapan WHERE no_wa = ?", (no_wa,))
        row = cursor.fetchone()
        if row:
            return {
                "no_wa": row["no_wa"],
                "status": row["status"] if row["status"] else "IDLE",
                "target_program": row["target_program"]
            }
        return {"no_wa": no_wa, "status": "IDLE", "target_program": None}


def simpan_transaksi_final(no_wa: str, nama: str, nominal: str | int, kode_program: str | None = None, pekerjaan: str | None = None):
    """
    Menyimpan pendaftaran/transaksi ke tabel `transaksi_donasi`
    berdasarkan `kode_program` eksplisit atau `target_program` dari `sesi_percakapan`, lalu mereset status ke IDLE.
    """
    if not no_wa:
        return

    if not kode_program or kode_program in {"UMUM", "Donasi"}:
        session = get_session(no_wa)
        kode_program = session.get("target_program") or "INF-RUTIN"

    # Bersihkan nominal menjadi integer murni
    nominal_clean = 0
    if nominal:
        digits = re.sub(r"[^\d]", "", str(nominal))
        if digits:
            nominal_clean = int(digits)

    # Format nomor wa jika berawalan 628 -> 08
    no_wa_clean = str(no_wa).strip()
    if no_wa_clean.startswith("628"):
        no_wa_clean = "0" + no_wa_clean[2:]

    waktu_sekarang = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")

    if is_supabase_configured():
        try:
            supabase_simpan_transaksi(no_wa_clean, nama, nominal_clean, kode_program, waktu_transaksi=waktu_sekarang)
        except Exception as e:
            print(f"[Supabase Fallback to SQLite - simpan_transaksi] {e}")

    with get_db_connection() as conn:
        # Check if table has 'pekerjaan' column for backward compatibility with existing SQLite DB
        cursor = conn.execute("PRAGMA table_info(transaksi_donasi)")
        cols = [r["name"] for r in cursor.fetchall()]
        if "pekerjaan" in cols:
            conn.execute(
                "INSERT INTO transaksi_donasi (no_wa, nama_donatur, pekerjaan, kode_program, nominal, waktu_transaksi) VALUES (?, ?, ?, ?, ?, ?)",
                (no_wa_clean, nama, "-", kode_program, nominal_clean, waktu_sekarang)
            )
        else:
            conn.execute(
                "INSERT INTO transaksi_donasi (no_wa, nama_donatur, kode_program, nominal, waktu_transaksi) VALUES (?, ?, ?, ?, ?)",
                (no_wa_clean, nama, kode_program, nominal_clean, waktu_sekarang)
            )
        conn.commit()

    # Reset status sesi ke IDLE
    reset_status(no_wa)


def simpan_pendaftaran_one_shot(no_wa: str, nama: str, nominal: str, kode_program: str = "INF-RUTIN"):
    """Alias kompatibilitas untuk menyimpan transaksi final."""
    simpan_transaksi_final(no_wa, nama, nominal, kode_program=kode_program)


def ambil_riwayat_donasi(no_wa: str) -> list[dict]:
    """Mengambil daftar riwayat transaksi donasi berdasarkan no_wa dari Supabase atau SQLite."""
    if not no_wa:
        return []

    if is_supabase_configured():
        try:
            items = supabase_ambil_riwayat(no_wa)
            if items:
                return items
        except Exception as e:
            print(f"[Supabase Fallback to SQLite - ambil_riwayat] {e}")

    digits = "".join(filter(str.isdigit, no_wa))
    if not digits:
        return []
    pattern = f"%{digits[-8:]}%" if len(digits) >= 8 else f"%{digits}%"

    with get_db_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM transaksi_donasi WHERE no_wa LIKE ? ORDER BY waktu_transaksi DESC",
            (pattern,)
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def sync_offline_sqlite_to_supabase():
    """Background helper untuk menyinkronkan data transaksi lokal SQLite ke Supabase Cloud."""
    if not is_supabase_configured():
        return
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM transaksi_donasi")
        rows = cursor.fetchall()
        for r in rows:
            try:
                supabase_simpan_transaksi(
                    r["no_wa"],
                    r["nama_donatur"],
                    r["nominal"],
                    r["kode_program"],
                    waktu_transaksi=r["waktu_transaksi"]
                )
            except Exception:
                pass
