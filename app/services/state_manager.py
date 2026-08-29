import os
import re
import sqlite3
from datetime import datetime, timezone, timedelta

WIB = timezone(timedelta(hours=7))
# DB_PATH bisa di-override lewat env var (dipakai docker-compose.yml untuk
# mengarahkan ke volume persisten /code/app_db/donatur.db) - tanpa ini,
# data SQLite ditulis ke path yang tidak ter-mount ke volume dan hilang
# saat container di-rebuild.
DB_PATH = os.getenv("DB_PATH") or os.path.join(os.path.dirname(__file__), "..", "donatur.db")

# Foto resi disimpan sebagai file di sebelah donatur.db (bukan blob di DB) -
# otomatis ikut volume persisten yang sama tanpa perlu env var/volume baru.
RESI_DIR = os.path.join(os.path.dirname(DB_PATH), "resi")


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

        # Migration check: status_verifikasi & sumber untuk alur validasi resi
        # dari web (identitas belum terverifikasi saat upload, admin yang
        # memvalidasi manual lewat dashboard). Transaksi lama/dari WhatsApp
        # otomatis 'validated' (WA sudah terverifikasi lewat sesi HP-nya).
        cursor = conn.execute("PRAGMA table_info(transaksi_donasi)")
        tx_columns = [row["name"] for row in cursor.fetchall()]
        if "status_verifikasi" not in tx_columns:
            conn.execute("ALTER TABLE transaksi_donasi ADD COLUMN status_verifikasi TEXT DEFAULT 'validated'")
        if "sumber" not in tx_columns:
            conn.execute("ALTER TABLE transaksi_donasi ADD COLUMN sumber TEXT DEFAULT 'whatsapp'")
        if "resi_path" not in tx_columns:
            conn.execute("ALTER TABLE transaksi_donasi ADD COLUMN resi_path TEXT")

        # 4. TABEL log_percakapan - satu baris per pesan (masuk/keluar/sistem),
        # dipakai halaman admin "Log Bot" untuk menampilkan transkrip
        # percakapan Mimin AI dari WhatsApp maupun Web Chat.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS log_percakapan (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sumber TEXT NOT NULL,
                kontak TEXT NOT NULL,
                dari TEXT NOT NULL,
                teks TEXT,
                waktu DATETIME NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_log_percakapan_kontak ON log_percakapan (sumber, kontak, waktu)")

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


def normalisasi_no_wa(no_wa: str) -> str:
    """Ubah nomor WA berawalan 628 (format WAHA/chatId) jadi 08 (format
    tampilan/penyimpanan seragam) - dipakai di transaksi maupun log_percakapan
    supaya keduanya bisa dicocokkan dengan kontak yang sama."""
    no_wa_clean = str(no_wa or "").strip()
    if no_wa_clean.startswith("628"):
        no_wa_clean = "0" + no_wa_clean[2:]
    return no_wa_clean


def _simpan_file_resi(transaksi_id: int, gambar_bytes: bytes) -> str:
    os.makedirs(RESI_DIR, exist_ok=True)
    nama_file = f"{transaksi_id}.jpg"
    with open(os.path.join(RESI_DIR, nama_file), "wb") as f:
        f.write(gambar_bytes)
    return nama_file


def simpan_transaksi_final(
    no_wa: str,
    nama: str,
    nominal: str | int,
    kode_program: str | None = None,
    pekerjaan: str | None = None,
    status_verifikasi: str = "validated",
    sumber: str = "whatsapp",
    resi_bytes: bytes | None = None,
) -> int | None:
    """
    Menyimpan pendaftaran/transaksi ke tabel `transaksi_donasi`
    berdasarkan `kode_program` eksplisit atau `target_program` dari `sesi_percakapan`, lalu mereset status ke IDLE.

    status_verifikasi='pending' dipakai untuk resi yang diunggah lewat web
    (identitas pengunjung belum terverifikasi saat unggah) - baru dianggap
    sah setelah admin menekan "Tandai Tervalidasi" di dashboard.

    resi_bytes (opsional): foto bukti transfer yang sudah diproses OCR-nya -
    disimpan sebagai file di RESI_DIR supaya admin bisa melihat gambar
    aslinya di dashboard, bukan cuma hasil baca AI-nya. Mengembalikan id
    transaksi yang baru dibuat (atau None kalau no_wa kosong).
    """
    if not no_wa:
        return None

    if not kode_program or kode_program in {"UMUM", "Donasi"}:
        session = get_session(no_wa)
        kode_program = session.get("target_program") or "INF-RUTIN"

    # Bersihkan nominal menjadi integer murni
    nominal_clean = 0
    if nominal:
        digits = re.sub(r"[^\d]", "", str(nominal))
        if digits:
            nominal_clean = int(digits)

    no_wa_clean = normalisasi_no_wa(no_wa)
    waktu_sekarang = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")

    if is_supabase_configured():
        try:
            supabase_simpan_transaksi(no_wa_clean, nama, nominal_clean, kode_program, waktu_transaksi=waktu_sekarang)
        except Exception as e:
            print(f"[Supabase Fallback to SQLite - simpan_transaksi] {e}")

    transaksi_id = None
    with get_db_connection() as conn:
        # Check if table has 'pekerjaan' column for backward compatibility with existing SQLite DB
        cursor = conn.execute("PRAGMA table_info(transaksi_donasi)")
        cols = [r["name"] for r in cursor.fetchall()]
        if "pekerjaan" in cols:
            cursor = conn.execute(
                "INSERT INTO transaksi_donasi (no_wa, nama_donatur, pekerjaan, kode_program, nominal, waktu_transaksi, status_verifikasi, sumber) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (no_wa_clean, nama, "-", kode_program, nominal_clean, waktu_sekarang, status_verifikasi, sumber)
            )
        else:
            cursor = conn.execute(
                "INSERT INTO transaksi_donasi (no_wa, nama_donatur, kode_program, nominal, waktu_transaksi, status_verifikasi, sumber) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (no_wa_clean, nama, kode_program, nominal_clean, waktu_sekarang, status_verifikasi, sumber)
            )
        transaksi_id = cursor.lastrowid

        if resi_bytes and transaksi_id:
            try:
                nama_file = _simpan_file_resi(transaksi_id, resi_bytes)
                conn.execute("UPDATE transaksi_donasi SET resi_path = ? WHERE id = ?", (nama_file, transaksi_id))
            except OSError as e:
                print(f"[Warning] Gagal menyimpan file resi transaksi #{transaksi_id}: {e}")

        conn.commit()

    # Reset status sesi ke IDLE - hanya relevan untuk alur FSM WhatsApp, resi
    # web tidak punya sesi FSM jadi ini no-op aman untuknya juga.
    reset_status(no_wa)
    return transaksi_id


def simpan_pendaftaran_one_shot(no_wa: str, nama: str, nominal: str, kode_program: str = "INF-RUTIN"):
    """Alias kompatibilitas untuk menyimpan transaksi final."""
    simpan_transaksi_final(no_wa, nama, nominal, kode_program=kode_program)


def ambil_semua_transaksi(limit: int = 50) -> list[dict]:
    """Mengambil transaksi terbaru lintas donatur untuk Admin Dashboard
    (beda dari ambil_riwayat_donasi yang scoped ke 1 no_wa)."""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM transaksi_donasi ORDER BY waktu_transaksi DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cursor.fetchall()]


def update_status_verifikasi(transaksi_id: int, status_baru: str, kode_program_baru: str | None = None) -> bool:
    """Admin menandai transaksi (biasanya resi dari web/resi tanpa keterangan
    program) sebagai 'validated' atau 'rejected'. kode_program_baru opsional -
    dipakai saat kategori sebelumnya cuma tebakan sistem (mis. resi tanpa
    keterangan apa pun) dan admin mengoreksinya jadi kategori yang benar
    sekalian saat memvalidasi. Mengembalikan True kalau baris ditemukan &
    diupdate."""
    if status_baru not in {"validated", "rejected", "pending"}:
        return False
    with get_db_connection() as conn:
        if kode_program_baru:
            cursor = conn.execute(
                "UPDATE transaksi_donasi SET status_verifikasi = ?, kode_program = ? WHERE id = ?",
                (status_baru, kode_program_baru, transaksi_id),
            )
        else:
            cursor = conn.execute(
                "UPDATE transaksi_donasi SET status_verifikasi = ? WHERE id = ?",
                (status_baru, transaksi_id),
            )
        conn.commit()
        return cursor.rowcount > 0


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


def bersihkan_log_percakapan_lama(hari: int = 90) -> int:
    """Hapus baris log_percakapan yang lebih tua dari `hari` hari - sebelumnya
    tabel ini tumbuh terus tanpa batas (dicatat sebagai gap terbuka dari audit
    sebelumnya). Dipanggil sekali saat startup aplikasi (lihat main.py) -
    bukan solusi sempurna (baru "membersihkan" tiap kali container di-restart,
    bukan penjadwalan rutin sungguhan), tapi jauh lebih baik daripada tidak
    ada retensi sama sekali. Kembalikan jumlah baris yang dihapus."""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM log_percakapan WHERE waktu < datetime('now', ?)",
            (f"-{int(hari)} days",),
        )
        conn.commit()
        return cursor.rowcount


def catat_pesan(sumber: str, kontak: str, dari: str, teks: str):
    """Mencatat satu baris pesan (user/bot/sistem) ke log_percakapan untuk
    halaman admin Log Bot. `kontak` = no_wa (WhatsApp) atau token sesi
    browser (Web, sebelum/sesudah OTP - satu sesi tetap satu kontak supaya
    transkripnya nyambung)."""
    if not sumber or not kontak or not teks:
        return
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO log_percakapan (sumber, kontak, dari, teks, waktu) VALUES (?, ?, ?, ?, ?)",
            (sumber, kontak, dari, teks, datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()


def ambil_daftar_percakapan(limit: int = 100) -> list[dict]:
    """Daftar percakapan (satu baris per kontak, bukan per pesan) untuk
    panel kiri halaman Log Bot - diurutkan dari yang terbaru aktif."""
    with get_db_connection() as conn:
        grup = conn.execute("""
            SELECT sumber, kontak, MAX(waktu) AS waktu_terakhir, COUNT(*) AS jumlah_pesan
            FROM log_percakapan
            GROUP BY sumber, kontak
            ORDER BY waktu_terakhir DESC
            LIMIT ?
        """, (limit,)).fetchall()

        hasil = []
        for g in grup:
            preview_row = conn.execute(
                "SELECT teks FROM log_percakapan WHERE sumber = ? AND kontak = ? ORDER BY waktu DESC, id DESC LIMIT 1",
                (g["sumber"], g["kontak"]),
            ).fetchone()
            hasil.append({
                "sumber": g["sumber"],
                "kontak": g["kontak"],
                "waktu_terakhir": g["waktu_terakhir"],
                "jumlah_pesan": g["jumlah_pesan"],
                "preview": (preview_row["teks"] if preview_row else "") or "",
            })
        return hasil


def ambil_pesan_kontak(sumber: str, kontak: str, limit: int = 500) -> list[dict]:
    """Transkrip lengkap satu percakapan, urut kronologis."""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "SELECT dari, teks, waktu FROM log_percakapan WHERE sumber = ? AND kontak = ? ORDER BY waktu ASC, id ASC LIMIT ?",
            (sumber, kontak, limit),
        )
        return [dict(r) for r in cursor.fetchall()]


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
