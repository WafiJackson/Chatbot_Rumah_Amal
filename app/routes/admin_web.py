import hashlib
import os
import re
import secrets
import time
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates

from services import state_manager
from services.supabase_client import is_supabase_configured
from routes.bot_webhook import PETA_NAMA

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates/admin")

WIB = timezone(timedelta(hours=7))

ADMIN_USERNAME = os.getenv("ADMIN_DASHBOARD_USERNAME", "admin")
# ADMIN_DASHBOARD_PASSWORD_HASH (format "salt_hex:hash_hex", lihat hash_password()
# di bawah) adalah cara yang DIANJURKAN - password asli tidak pernah tersimpan
# di .env sama sekali. ADMIN_DASHBOARD_PASSWORD (plaintext) tetap didukung
# sebagai fallback supaya deployment lama tidak langsung rusak, tapi kalau
# .env sampai bocor, password plaintext langsung terpakai tanpa perlu di-crack.
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_DASHBOARD_PASSWORD_HASH", "")
ADMIN_PASSWORD = os.getenv("ADMIN_DASHBOARD_PASSWORD", "")
SESSION_COOKIE = "admin_session"

# Sesi login disimpan in-memory (pola yang sama dengan user_sessions di bot_webhook.py) -
# cukup untuk single-instance deployment, sesuai kebutuhan "session sederhana" di blueprint.
# Disimpan sebagai token -> waktu_dibuat supaya sesi bisa kedaluwarsa (sebelumnya
# token yang sekali terbit valid selamanya sampai restart server/logout manual).
ADMIN_SESSIONS: dict[str, float] = {}
ADMIN_SESSION_MAKS_DETIK = 24 * 60 * 60  # 24 jam


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Hasilkan hash PBKDF2 (stdlib saja, tanpa dependency baru) dalam format
    "salt_hex:hash_hex" - dipakai untuk membuat nilai ADMIN_DASHBOARD_PASSWORD_HASH."""
    salt = salt or os.urandom(16)
    hash_bytes = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"{salt.hex()}:{hash_bytes.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, hash_hex = stored_hash.split(":")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return secrets.compare_digest(actual, expected)

# Rate limiter percobaan login (pola sama dengan _check_rate_limit di
# public_web.py) - tanpa ini, password admin bisa dicoba tanpa batas oleh
# script otomatis karena endpoint ini sebelumnya tidak punya proteksi apa pun.
_LOGIN_ATTEMPTS: dict[str, list] = {}
LOGIN_MAKS_PERCOBAAN = 5
LOGIN_JENDELA_DETIK = 300  # 5 menit


def _login_rate_limited(ip: str) -> bool:
    now = time.time()
    timestamps = [t for t in _LOGIN_ATTEMPTS.get(ip, []) if now - t < LOGIN_JENDELA_DETIK]
    if len(timestamps) >= LOGIN_MAKS_PERCOBAAN:
        _LOGIN_ATTEMPTS[ip] = timestamps
        return True
    timestamps.append(now)
    _LOGIN_ATTEMPTS[ip] = timestamps
    return False


def _format_rupiah(value) -> str:
    try:
        return f"Rp {int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "Rp 0"


templates.env.filters["rupiah"] = _format_rupiah


def _is_authenticated(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token or token not in ADMIN_SESSIONS:
        return False
    if time.time() - ADMIN_SESSIONS[token] > ADMIN_SESSION_MAKS_DETIK:
        del ADMIN_SESSIONS[token]
        return False
    return True


def _require_login(request: Request):
    """Kembalikan RedirectResponse ke halaman login jika belum masuk, None jika sudah."""
    if not _is_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    return None


# =====================================================================
# DATA DASHBOARD & TRANSAKSI - dari database asli (SQLite/Supabase lewat
# state_manager), bukan lagi contoh statis.
# =====================================================================

_STATUS_LABEL = {"validated": "Tervalidasi", "pending": "Menunggu", "rejected": "Ditolak"}

# Kategori donasi yang bisa dipilih admin saat mengoreksi transaksi pending
# (resi tanpa keterangan program apa pun - lihat _format_transaksi_tampilan).
# Sengaja cuma 5 kode ini (bukan seluruh 10+ program beasiswa) karena inilah
# satu-satunya kode yang benar-benar dipakai untuk transaksi donasi/zakat -
# baik dari menu PILIH_PROGRAM WhatsApp maupun hasil baca Vision AI.
KATEGORI_DONASI_VALID = {
    "ZKT-MAL": "Zakat Mal",
    "ZKT-PENGHASILAN": "Zakat Penghasilan",
    "INF-RUTIN": "Infak Rutin",
    "DONASI": "Donasi (Bantuan Kemanusiaan)",
    "DON-PALESTINA": "OTA Palestina",
}


def _tanggal_saja(waktu_raw: str) -> str:
    return (waktu_raw or "").split(" ")[0].split("T")[0]


def _hitung_kpi_dan_tren(transaksi: list[dict]) -> tuple[dict, list[dict]]:
    """Agregasi KPI & tren 7 hari dari daftar transaksi asli. Hanya transaksi
    'validated' yang dihitung - resi web yang masih 'pending' belum dianggap
    donasi sah sampai admin memvalidasi."""
    total_donasi = 0
    total_zakat = 0
    total_infak = 0
    pengguna = set()
    per_hari: dict[str, int] = {}

    for t in transaksi:
        if t.get("status_verifikasi", "validated") != "validated":
            continue
        nominal = int(t.get("nominal") or 0)
        kode = (t.get("kode_program") or "").upper()
        total_donasi += nominal
        if kode.startswith("ZKT"):
            total_zakat += nominal
        elif kode == "INF-RUTIN":
            total_infak += nominal
        if t.get("no_wa"):
            pengguna.add(t["no_wa"])

        tgl = _tanggal_saja(t.get("waktu_transaksi"))
        if tgl:
            per_hari[tgl] = per_hari.get(tgl, 0) + nominal

    kpi = {
        "total_donasi": total_donasi,
        "total_zakat": total_zakat,
        "total_infak": total_infak,
        "pengguna_aktif": len(pengguna),
    }

    hari_label = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
    tren = []
    hari_ini = datetime.now(WIB).date()
    for i in range(6, -1, -1):
        tgl = hari_ini - timedelta(days=i)
        tren.append({"hari": hari_label[tgl.weekday()], "nominal": per_hari.get(tgl.isoformat(), 0)})

    return kpi, tren


def _format_transaksi_tampilan(rows: list[dict]) -> list[dict]:
    hasil = []
    for r in rows:
        waktu_raw = r.get("waktu_transaksi") or ""
        hasil.append({
            "id": r.get("id"),
            "id_tampil": f"TRX-{int(r['id']):04d}" if r.get("id") is not None else "TRX-????",
            "no_wa": r.get("no_wa") or "-",
            "nama_donatur": r.get("nama_donatur") or "-",
            "kode_program": PETA_NAMA.get(r.get("kode_program"), r.get("kode_program") or "Donasi"),
            "kode_program_raw": r.get("kode_program") or "",
            "nominal": r.get("nominal") or 0,
            "waktu_transaksi": waktu_raw,
            "status": r.get("status_verifikasi") or "validated",
            "status_label": _STATUS_LABEL.get(r.get("status_verifikasi") or "validated", "Tervalidasi"),
            "sumber": r.get("sumber") or "whatsapp",
            "resi_path": r.get("resi_path"),
        })
    return hasil


_SOURCE_LABEL = {"whatsapp": "WhatsApp", "web": "Web Chat"}


def _format_percakapan_tampilan() -> list[dict]:
    """Kelompokkan log_percakapan jadi daftar percakapan lengkap dengan
    transkripnya, siap di-tojson ke log_bot.html (pola sama seperti
    `const TRANSAKSI = {{ transaksi | tojson }}` di transactions.html)."""
    grup = state_manager.ambil_daftar_percakapan(limit=200)
    hasil = []
    for g in grup:
        sumber = g["sumber"]
        kontak = g["kontak"]
        pesan_mentah = state_manager.ambil_pesan_kontak(sumber, kontak)
        if sumber == "whatsapp":
            nama = f"Donatur WhatsApp ({kontak})"
            kontak_tampil = kontak
        else:
            nama = "Pengunjung Web"
            kontak_tampil = f"sesi #{kontak[:8]}"
        hasil.append({
            "id": f"{sumber}|{kontak}",
            "sumber": sumber,
            "sumber_label": _SOURCE_LABEL.get(sumber, sumber),
            "nama": nama,
            "kontak_tampil": kontak_tampil,
            "waktu_terakhir": g["waktu_terakhir"],
            "jumlah_pesan": g["jumlah_pesan"],
            "preview": g["preview"],
            "pesan": pesan_mentah,
        })
    return hasil


# =====================================================================
# ROUTES
# =====================================================================

@router.get("/")
def admin_root(request: Request):
    redirect = _require_login(request)
    return redirect or RedirectResponse(url="/admin/dashboard", status_code=303)


@router.get("/login")
def login_page(request: Request, error: str | None = None):
    if _is_authenticated(request):
        return RedirectResponse(url="/admin/dashboard", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": error})


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    client_ip = request.client.host if request.client else "unknown"
    if _login_rate_limited(client_ip):
        return RedirectResponse(url="/admin/login?error=terlalu_banyak", status_code=303)

    if not ADMIN_PASSWORD_HASH and not ADMIN_PASSWORD:
        return RedirectResponse(url="/admin/login?error=belum_dikonfigurasi", status_code=303)

    if ADMIN_PASSWORD_HASH:
        password_cocok = _verify_password(password, ADMIN_PASSWORD_HASH)
    else:
        password_cocok = secrets.compare_digest(password, ADMIN_PASSWORD)

    if username == ADMIN_USERNAME and password_cocok:
        token = secrets.token_urlsafe(32)
        ADMIN_SESSIONS[token] = time.time()
        response = RedirectResponse(url="/admin/dashboard", status_code=303)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=request.url.scheme == "https")
        return response

    return RedirectResponse(url="/admin/login?error=salah", status_code=303)


@router.get("/logout")
def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    ADMIN_SESSIONS.pop(token, None)
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/dashboard")
def dashboard_page(request: Request):
    redirect = _require_login(request)
    if redirect:
        return redirect

    transaksi_mentah = state_manager.ambil_semua_transaksi(limit=200)
    kpi, tren = _hitung_kpi_dan_tren(transaksi_mentah)
    aktivitas_terbaru = _format_transaksi_tampilan(transaksi_mentah[:4])

    return templates.TemplateResponse(request, "dashboard.html", {
        "active_page": "dashboard",
        "admin_username": ADMIN_USERNAME,
        "kpi": kpi,
        "tren": tren,
        "aktivitas": aktivitas_terbaru,
        "sumber_data": "Supabase" if is_supabase_configured() else "SQLite Lokal (Supabase belum dikonfigurasi)",
    })


@router.get("/transactions")
def transactions_page(request: Request):
    redirect = _require_login(request)
    if redirect:
        return redirect

    transaksi_mentah = state_manager.ambil_semua_transaksi(limit=200)
    return templates.TemplateResponse(request, "transactions.html", {
        "active_page": "transaksi",
        "admin_username": ADMIN_USERNAME,
        "transaksi": _format_transaksi_tampilan(transaksi_mentah),
    })


@router.get("/log-bot")
def log_bot_page(request: Request):
    redirect = _require_login(request)
    if redirect:
        return redirect

    return templates.TemplateResponse(request, "log_bot.html", {
        "active_page": "log_bot",
        "admin_username": ADMIN_USERNAME,
        "percakapan": _format_percakapan_tampilan(),
    })


_NAMA_FILE_RESI_VALID = re.compile(r"^\d+\.jpg$")


@router.get("/resi/{filename}")
def lihat_resi(filename: str, request: Request):
    redirect = _require_login(request)
    if redirect:
        return redirect

    # Nama file yang kita buat sendiri selalu "<id_transaksi>.jpg" - tolak
    # pola lain supaya tidak bisa dipakai untuk path traversal.
    if not _NAMA_FILE_RESI_VALID.match(filename):
        return JSONResponse({"status": "gagal", "pesan": "Nama berkas tidak valid."}, status_code=400)

    path_lengkap = os.path.join(state_manager.RESI_DIR, filename)
    if not os.path.isfile(path_lengkap):
        return JSONResponse({"status": "gagal", "pesan": "Gambar resi tidak ditemukan."}, status_code=404)

    return FileResponse(path_lengkap)


@router.post("/transactions/{transaksi_id}/status")
def update_transaksi_status(transaksi_id: int, request: Request, status: str = Form(...), kode_program: str | None = Form(None)):
    if not _is_authenticated(request):
        return JSONResponse({"status": "gagal", "pesan": "Sesi login sudah berakhir."}, status_code=401)

    if kode_program and kode_program not in KATEGORI_DONASI_VALID:
        return JSONResponse({"status": "gagal", "pesan": "Kategori tidak dikenali."}, status_code=400)

    ok = state_manager.update_status_verifikasi(transaksi_id, status, kode_program_baru=kode_program)
    if not ok:
        return JSONResponse({"status": "gagal", "pesan": "Transaksi tidak ditemukan atau status tidak valid."}, status_code=400)

    return JSONResponse({"status": "sukses"})
