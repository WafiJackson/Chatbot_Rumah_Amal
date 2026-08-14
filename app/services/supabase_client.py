import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

WIB = timezone(timedelta(hours=7))

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
if "/rest/v1" in SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.split("/rest/v1")[0].strip()
SUPABASE_URL = SUPABASE_URL.rstrip("/")

SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

supabase_client = None


if SUPABASE_URL and SUPABASE_KEY and SUPABASE_URL.startswith("http"):
    try:
        from supabase import create_client, Client
        supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("[Supabase Client] Connected to Supabase Cloud!")
    except Exception as e:
        print(f"[Supabase Client Warning] Failed to initialize Supabase: {e}")
        supabase_client = None


def is_supabase_configured() -> bool:
    return supabase_client is not None


def get_status(no_wa: str) -> str:
    if not supabase_client:
        return "IDLE"
    res = supabase_client.table("sesi_percakapan").select("status").eq("no_wa", no_wa).execute()
    if hasattr(res, "error") and res.error:
        raise RuntimeError(f"Supabase Error: {res.error}")
    if res.data and len(res.data) > 0:
        return res.data[0].get("status", "IDLE")
    return "IDLE"


def update_status(no_wa: str, status_baru: str, target_program: str | None = None):
    if not supabase_client:
        return
    now_str = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "no_wa": no_wa,
        "status": status_baru,
        "waktu_update": now_str
    }
    if target_program:
        payload["target_program"] = target_program

    res = supabase_client.table("sesi_percakapan").upsert(payload, on_conflict="no_wa").execute()
    if hasattr(res, "error") and res.error:
        raise RuntimeError(f"Supabase Error: {res.error}")


def reset_status(no_wa: str):
    update_status(no_wa, "IDLE")


def get_session(no_wa: str) -> dict:
    if not supabase_client:
        return {"no_wa": no_wa, "status": "IDLE", "target_program": None}
    res = supabase_client.table("sesi_percakapan").select("*").eq("no_wa", no_wa).execute()
    if hasattr(res, "error") and res.error:
        raise RuntimeError(f"Supabase Error: {res.error}")
    if res.data and len(res.data) > 0:
        return res.data[0]
    return {"no_wa": no_wa, "status": "IDLE", "target_program": None}


def simpan_transaksi_final(no_wa: str, nama_donatur: str, nominal: str | int, kode_program: str = "INF-RUTIN", waktu_transaksi: str | None = None):
    if not supabase_client:
        return
    now_str = waktu_transaksi or datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")
    nom_clean = int(str(nominal).replace(".", "").replace(",", "").strip()) if nominal else 0
    payload = {
        "no_wa": no_wa,
        "nama_donatur": nama_donatur,
        "kode_program": kode_program,
        "nominal": nom_clean,
        "waktu_transaksi": now_str
    }
    supabase_client.table("transaksi_donasi").insert(payload).execute()
    print(f"[Supabase] Transaksi {nama_donatur} ({nom_clean}) tersimpan ke Supabase!")


def ambil_riwayat_donasi(no_wa: str) -> list[dict]:
    if not supabase_client or not no_wa:
        return []
    digits = "".join(filter(str.isdigit, no_wa))
    if not digits:
        return []
    
    # Match by last 8 digits of WA number
    pattern = f"%{digits[-8:]}%" if len(digits) >= 8 else f"%{digits}%"
    try:
        res = supabase_client.table("transaksi_donasi").select("*").ilike("no_wa", pattern).order("waktu_transaksi", desc=True).execute()
        return res.data if res.data else []
    except Exception as e:
        print(f"[Supabase Error ambil_riwayat] {e}")
        return []
