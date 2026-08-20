import os
import secrets
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from services import state_manager
from services.supabase_client import is_supabase_configured

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
# DATA DASHBOARD & TRANSAKSI
#
# Catatan: masih data contoh (mock), TAPI bentuk/nama variabelnya sengaja
# disamakan dengan skema tabel asli (transaksi_donasi & master_program di
# state_manager.py / supabase_client.py) supaya nanti tinggal ganti isi
# fungsi ini dengan query Supabase asli tanpa mengubah template sama sekali.
# =====================================================================

def _ambil_data_kpi() -> dict:
    # TODO ganti dengan query Supabase asli, misal:
    # supabase_client.table("transaksi_donasi").select("kode_program, nominal").execute()
    return {
        "total_donasi": 45230000,
        "total_zakat": 28150000,
        "total_infak": 9480000,
        "pengguna_aktif": 312,
    }


def _ambil_tren_7_hari() -> list[dict]:
    # TODO ganti dengan agregasi harian dari Supabase (GROUP BY tanggal)
    return [
        {"hari": "Sen", "nominal": 4200000},
        {"hari": "Sel", "nominal": 6800000},
        {"hari": "Rab", "nominal": 5100000},
        {"hari": "Kam", "nominal": 9600000},
        {"hari": "Jum", "nominal": 12400000},
        {"hari": "Sab", "nominal": 4300000},
        {"hari": "Min", "nominal": 2830000},
    ]


def _ambil_daftar_transaksi() -> list[dict]:
    # TODO ganti dengan:
    # supabase_client.table("transaksi_donasi").select("*").order("waktu_transaksi", desc=True).execute()
    return [
        {"id": "TRX-0231", "no_wa": "0812-xxxx-8891", "nama_donatur": "Siti Aisyah", "kode_program": "Zakat Mal", "nominal": 2500000, "waktu_transaksi": "15 Ags 2026", "status": "berhasil"},
        {"id": "TRX-0230", "no_wa": "0813-xxxx-2210", "nama_donatur": "Budi Santoso", "kode_program": "Infak Rutin", "nominal": 150000, "waktu_transaksi": "15 Ags 2026", "status": "berhasil"},
        {"id": "TRX-0229", "no_wa": "0821-xxxx-7745", "nama_donatur": "Rina Wulandari", "kode_program": "Zakat Penghasilan", "nominal": 900000, "waktu_transaksi": "14 Ags 2026", "status": "menunggu"},
        {"id": "TRX-0228", "no_wa": "0852-xxxx-1180", "nama_donatur": "Ahmad Fauzi", "kode_program": "BPRA-UKT", "nominal": 3000000, "waktu_transaksi": "14 Ags 2026", "status": "berhasil"},
        {"id": "TRX-0227", "no_wa": "0878-xxxx-3392", "nama_donatur": "Dewi Lestari", "kode_program": "Green Qurban", "nominal": 2200000, "waktu_transaksi": "13 Ags 2026", "status": "gagal"},
        {"id": "TRX-0226", "no_wa": "0819-xxxx-6604", "nama_donatur": "Yafi Hidayatullah", "kode_program": "Infak Rutin", "nominal": 100000, "waktu_transaksi": "13 Ags 2026", "status": "berhasil"},
        {"id": "TRX-0225", "no_wa": "0817-xxxx-4423", "nama_donatur": "Cut Dara", "kode_program": "OTA Palestina", "nominal": 500000, "waktu_transaksi": "12 Ags 2026", "status": "menunggu"},
    ]


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

    return templates.TemplateResponse(request, "dashboard.html", {
        "active_page": "dashboard",
        "kpi": _ambil_data_kpi(),
        "tren": _ambil_tren_7_hari(),
        "sumber_data": "Supabase" if is_supabase_configured() else "SQLite Lokal (Supabase belum dikonfigurasi)",
    })


@router.get("/transactions")
def transactions_page(request: Request):
    redirect = _require_login(request)
    if redirect:
        return redirect

    return templates.TemplateResponse(request, "transactions.html", {
        "active_page": "transaksi",
        "transaksi": _ambil_daftar_transaksi(),
    })
