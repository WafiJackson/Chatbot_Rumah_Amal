import os
import re
import sqlite3
from datetime import datetime

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

        # 2. TABEL transaksi_donasi
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transaksi_donasi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                no_wa TEXT,
                nama_donatur TEXT,
                pekerjaan TEXT,
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


def get_session(no_wa: str) -> dict:
    """Mengembalikan data sesi percakapan pengguna."""
    default_session = {
        "no_wa": no_wa,
        "status": "IDLE",
        "target_program": None,
        "waktu_update": None
    }
    if not no_wa:
        return default_session
    if is_supabase_configured():
        try:
            sess = supabase_get_session(no_wa)
            if sess and sess.get("status") and sess.get("status") != "IDLE":
                return sess
        except Exception as e:
            print(f"[Supabase Fallback to SQLite - get_session] {e}")

    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM sesi_percakapan WHERE no_wa = ?", (no_wa,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return default_session



def update_status(no_wa: str, status_baru: str, target_program: str = None):
    """Memperbarui status percakapan dan opsi target_program di sesi_percakapan."""
    if not no_wa:
        return
    if is_supabase_configured():
        try:
            supabase_update_status(no_wa, status_baru, target_program)
            # Selalu update ke SQLite juga sebagai sync backup
        except Exception as e:
            print(f"[Supabase Fallback to SQLite - update_status] {e}")

    waktu_sekarang = datetime.now().isoformat()
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT no_wa FROM sesi_percakapan WHERE no_wa = ?", (no_wa,))
        exists = cursor.fetchone() is not None

        if not exists:
            conn.execute(
                "INSERT INTO sesi_percakapan (no_wa, status, target_program, waktu_update) VALUES (?, ?, ?, ?)",
                (no_wa, status_baru, target_program, waktu_sekarang)
            )
        else:
            if target_program:
                conn.execute(
                    "UPDATE sesi_percakapan SET status = ?, target_program = ?, waktu_update = ? WHERE no_wa = ?",
                    (status_baru, target_program, waktu_sekarang, no_wa)
                )
            else:
                conn.execute(
                    "UPDATE sesi_percakapan SET status = ?, waktu_update = ? WHERE no_wa = ?",
                    (status_baru, waktu_sekarang, no_wa)
                )
        conn.commit()


def reset_status(no_wa: str):
    """Mengembalikan status percakapan pengguna ke 'IDLE'."""
    if not no_wa:
        return
    if is_supabase_configured():
        try:
            supabase_reset_status(no_wa)
        except Exception as e:
            print(f"[Supabase Fallback to SQLite - reset_status] {e}")

    waktu_sekarang = datetime.now().isoformat()
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE sesi_percakapan SET status = 'IDLE', waktu_update = ? WHERE no_wa = ?",
            (waktu_sekarang, no_wa)
        )
        conn.commit()


def simpan_transaksi_final(no_wa: str, nama: str, pekerjaan: str, nominal: str, kode_program: str | None = None):
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

    if is_supabase_configured():
        try:
            supabase_simpan_transaksi(no_wa_clean, nama, pekerjaan, nominal_clean, kode_program)
        except Exception as e:
            print(f"[Supabase Fallback to SQLite - simpan_transaksi] {e}")

    waktu_sekarang = datetime.now().isoformat()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO transaksi_donasi (no_wa, nama_donatur, pekerjaan, kode_program, nominal, waktu_transaksi) VALUES (?, ?, ?, ?, ?, ?)",
            (no_wa_clean, nama, pekerjaan, kode_program, nominal_clean, waktu_sekarang)
        )
        conn.commit()

    # Reset status sesi ke IDLE
    reset_status(no_wa)



def simpan_pendaftaran_one_shot(no_wa: str, nama: str, pekerjaan: str, nominal: str):
    """Alias kompatibilitas untuk menyimpan transaksi final."""
    simpan_transaksi_final(no_wa, nama, pekerjaan, nominal)


def ambil_riwayat_donasi(no_wa: str) -> list[dict]:
    """Mengambil riwayat transaksi donasi (maksimal 5 transaksi terakhir)."""
    if not no_wa:
        return []
    
    digits = "".join(filter(str.isdigit, no_wa))
    if is_supabase_configured():
        try:
            items = supabase_ambil_riwayat(no_wa)
            if items:
                return items
        except Exception as e:
            print(f"[Supabase Fallback to SQLite - ambil_riwayat_donasi] {e}")

    with get_db_connection() as conn:
        pattern = f"%{digits[-8:]}%" if len(digits) >= 8 else f"%{digits}%"
        cursor = conn.execute(
            "SELECT * FROM transaksi_donasi WHERE no_wa LIKE ? ORDER BY waktu_transaksi DESC LIMIT 5",
            (pattern,)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def sync_offline_sqlite_to_supabase():
    """
    Background Task:
    Memeriksa transaksi offline di SQLite lokal yang belum tersinkron ke Supabase Cloud (synced_supabase = 0)
    dan mengunggahnya secara otomatis ketika jaringan Supabase online kembali.
    """
    if not is_supabase_configured():
        return

    try:
        with get_db_connection() as conn:
            cursor = conn.execute("PRAGMA table_info(transaksi_donasi)")
            columns = [row["name"] for row in cursor.fetchall()]
            if "synced_supabase" not in columns:
                conn.execute("ALTER TABLE transaksi_donasi ADD COLUMN synced_supabase INTEGER DEFAULT 0")
                conn.commit()

            cursor = conn.execute("SELECT * FROM transaksi_donasi WHERE synced_supabase = 0 OR synced_supabase IS NULL LIMIT 50")
            rows = cursor.fetchall()
            if not rows:
                return

            synced_ids = []
            for r in rows:
                try:
                    supabase_simpan_transaksi(
                        r["no_wa"], r["nama_donatur"], r["pekerjaan"], r["nominal"], r["kode_program"]
                    )
                    synced_ids.append(r["id"])
                except Exception as e_row:
                    print(f"[Warning Sync Row {r['id']}] {e_row}")

            if synced_ids:
                placeholders = ",".join(["?"] * len(synced_ids))
                conn.execute(f"UPDATE transaksi_donasi SET synced_supabase = 1 WHERE id IN ({placeholders})", synced_ids)
                conn.commit()
                print(f"[Auto Sync] Berhasil mengunggah {len(synced_ids)} transaksi offline SQLite -> Supabase Cloud")
    except Exception as e:
        print(f"[Warning Background Auto Sync SQLite->Supabase] {e}")


