import os
import secrets
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services import state_manager
from services.supabase_client import is_supabase_configured
from routes.bot_webhook import PETA_NAMA

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates/admin")

WIB = timezone(timedelta(hours=7))

ADMIN_USERNAME = os.getenv("ADMIN_DASHBOARD_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_DASHBOARD_PASSWORD", "")
SESSION_COOKIE = "admin_session"

# Sesi login disimpan in-memory (pola yang sama dengan user_sessions di bot_webhook.py) -
# cukup untuk single-instance deployment, sesuai kebutuhan "session sederhana" di blueprint.
ADMIN_SESSIONS: set[str] = set()


def _format_rupiah(value) -> str:
    try:
        return f"Rp {int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "Rp 0"


templates.env.filters["rupiah"] = _format_rupiah


def _is_authenticated(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    return bool(token) and token in ADMIN_SESSIONS


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
            "nominal": r.get("nominal") or 0,
            "waktu_transaksi": waktu_raw,
            "status": r.get("status_verifikasi") or "validated",
            "status_label": _STATUS_LABEL.get(r.get("status_verifikasi") or "validated", "Tervalidasi"),
            "sumber": r.get("sumber") or "whatsapp",
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
def login_submit(username: str = Form(...), password: str = Form(...)):
    if not ADMIN_PASSWORD:
        return RedirectResponse(url="/admin/login?error=belum_dikonfigurasi", status_code=303)

    if username == ADMIN_USERNAME and secrets.compare_digest(password, ADMIN_PASSWORD):
        token = secrets.token_urlsafe(32)
        ADMIN_SESSIONS.add(token)
        response = RedirectResponse(url="/admin/dashboard", status_code=303)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
        return response

    return RedirectResponse(url="/admin/login?error=salah", status_code=303)


@router.get("/logout")
def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    ADMIN_SESSIONS.discard(token)
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


@router.post("/transactions/{transaksi_id}/status")
def update_transaksi_status(transaksi_id: int, request: Request, status: str = Form(...)):
    if not _is_authenticated(request):
        return JSONResponse({"status": "gagal", "pesan": "Sesi login sudah berakhir."}, status_code=401)

    ok = state_manager.update_status_verifikasi(transaksi_id, status)
    if not ok:
        return JSONResponse({"status": "gagal", "pesan": "Transaksi tidak ditemukan atau status tidak valid."}, status_code=400)

    return JSONResponse({"status": "sukses"})
