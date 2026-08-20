import re
import secrets
import time

from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from admin_scripts import susun_balasan
from services import state_manager
from services.llm_agent import ekstrak_resi_vision
from services.gender_detector import deteksi_sapaan_gender
from routes.bot_webhook import send_message_to_waha, notify_admin, PETA_NAMA

router = APIRouter(tags=["public-web"])
templates = Jinja2Templates(directory="templates/public")

SESSION_COOKIE = "web_chat_session"

# Konteks percakapan per-pengunjung web (pola sama dengan user_sessions di
# bot_webhook.py) - hanya menyimpan last_program_key & nomor WA yang sudah
# terverifikasi OTP di sesi ini, tidak menyimpan riwayat pesan.
WEB_SESSIONS: dict[str, dict] = {}

# Kode OTP aktif: {no_wa_bersih: {"code": "123456", "expires_at": ts, "attempts": 0}}
OTP_STORE: dict[str, dict] = {}
OTP_TTL_DETIK = 5 * 60
OTP_MAKS_PERCOBAAN = 5
OTP_COOLDOWN_DETIK = 60  # jeda minimal sebelum boleh kirim OTP baru ke nomor yang sama

# Rate limiter (pola sama dengan _check_rate_limit di bot_webhook.py, dikunci
# per IP pengunjung karena web chat belum tentu identitasnya terverifikasi).
_RATE_BUCKETS: dict[str, list] = {}


def _check_rate_limit(bucket: str, key: str, max_calls: int, window_detik: int) -> bool:
    now = time.time()
    store_key = f"{bucket}:{key}"
    timestamps = [t for t in _RATE_BUCKETS.get(store_key, []) if now - t < window_detik]
    if len(timestamps) >= max_calls:
        _RATE_BUCKETS[store_key] = timestamps
        return False
    timestamps.append(now)
    _RATE_BUCKETS[store_key] = timestamps
    return True


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limited_response(pesan: str) -> JSONResponse:
    return JSONResponse({"status": "gagal", "reply": pesan, "pesan": pesan, "requires_otp": False}, status_code=429)


MAKS_UKURAN_RESI_BYTES = 5 * 1024 * 1024  # 5 MB


def _sniff_gambar_valid(data: bytes) -> bool:
    """Validasi longgar berbasis magic bytes - menolak file yang jelas bukan
    gambar, walau tidak seketat validasi format penuh."""
    if not data:
        return False
    if data.startswith(b"\xff\xd8\xff"):
        return True
    if data.startswith(b"\x89PNG"):
        return True
    if data.startswith(b"RIFF") and b"WEBP" in data[:20]:
        return True
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return True
    return False


def _get_session(request: Request) -> tuple[str, dict, bool]:
    """Kembalikan (token, session_dict, perlu_set_cookie_baru)."""
    token = request.cookies.get(SESSION_COOKIE)
    if token and token in WEB_SESSIONS:
        return token, WEB_SESSIONS[token], False

    token = secrets.token_urlsafe(16)
    WEB_SESSIONS[token] = {"last_program_key": None}
    return token, WEB_SESSIONS[token], True


def _json_with_session(request: Request, data: dict, status_code: int = 200) -> JSONResponse:
    token, _session, is_new = _get_session(request)
    response = JSONResponse(data, status_code=status_code)
    if is_new:
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
    return response


def _normalisasi_wa(nomor: str) -> str:
    digits = re.sub(r"[^\d]", "", nomor or "")
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    return digits


def _is_cek_riwayat(pesan_clean: str) -> bool:
    """Sama persis dengan deteksi 'cek riwayat' di bot_webhook.py, supaya
    perilaku web chat konsisten dengan bot WhatsApp."""
    return (
        pesan_clean in ["4", "4.", "cek riwayat", "riwayat donasi", "histori donasi", "riwayat transaksi", "cek transaksi", "donasi saya", "riwayat saya", "histori saya"]
    ) or bool(re.search(r"(cek|lihat|tampilkan|minta|riwayat|histori|history)\s*(riwayat|histori|history|transaksi|donasi)", pesan_clean))


def _format_riwayat(no_wa: str, sapaan: str) -> str:
    riwayat_items = state_manager.ambil_riwayat_donasi(no_wa)
    if not riwayat_items:
        return (
            f"Mohon maaf {sapaan}, Mimin belum menemukan riwayat transaksi donasi yang tercatat untuk nomor WhatsApp ini.\n\n"
            f"Yuk tunaikan donasi/zakat pertama {sapaan}! 🙏"
        )

    total_donasi = 0
    baris = []
    for idx, item in enumerate(riwayat_items, 1):
        nom = int(item.get("nominal") or 0)
        total_donasi += nom
        tgl_raw = item.get("waktu_transaksi") or ""
        tgl_fmt = tgl_raw.split("T")[0] if "T" in str(tgl_raw) else str(tgl_raw)[:10]
        prog_name = PETA_NAMA.get(item.get("kode_program"), item.get("kode_program") or "Donasi")
        baris.append(f"{idx}. {tgl_fmt} | Rp {nom:,} | {prog_name}")

    return (
        f"📜 Berikut riwayat transaksi donasi {sapaan} yang tercatat:\n\n"
        + "\n".join(baris)
        + f"\n\n💰 Total Penyaluran: Rp {total_donasi:,} ({len(riwayat_items)} transaksi)\n\n"
        f"Jazakallahu Khairan atas kepercayaannya! 🙏"
    )


# =====================================================================
# HALAMAN
# =====================================================================

@router.get("/")
def chat_page(request: Request):
    return templates.TemplateResponse(request, "chat.html", {})


# =====================================================================
# API CHAT
# =====================================================================

@router.post("/api/web-chat")
async def web_chat(request: Request, payload: dict):
    if not _check_rate_limit("web-chat", _client_ip(request), max_calls=20, window_detik=60):
        return _rate_limited_response("Terlalu banyak pesan dalam waktu singkat, coba lagi sebentar ya 🙏")

    pesan = (payload.get("message") or "").strip()
    if not pesan:
        return _json_with_session(request, {"reply": "Boleh diketik dulu pesannya, Kak 🙏", "requires_otp": False})

    pesan_clean = pesan.lower().strip()

    if _is_cek_riwayat(pesan_clean):
        reply = "Untuk melihat riwayat transaksi, Mimin perlu verifikasi nomor WhatsApp Kakak dulu ya - demi menjaga data donasi tetap aman 🙏"
        return _json_with_session(request, {"reply": reply, "requires_otp": True})

    _token, session, _is_new = _get_session(request)
    hasil = susun_balasan(
        pesan,
        context={"last_program_key": session.get("last_program_key")},
        nama_pengirim="Kak",
    )
    session["last_program_key"] = hasil.get("last_program_key")

    return _json_with_session(request, {"reply": hasil["reply"], "requires_otp": False})


@router.post("/api/web-otp/request")
async def request_otp(request: Request, payload: dict):
    if not _check_rate_limit("otp-request-ip", _client_ip(request), max_calls=5, window_detik=60):
        return JSONResponse({"status": "gagal", "pesan": "Terlalu banyak permintaan kode, coba lagi sebentar ya."}, status_code=429)

    no_wa_raw = (payload.get("wa_number") or "").strip()
    no_wa = _normalisasi_wa(no_wa_raw)
    if len(no_wa) < 10:
        return JSONResponse({"status": "gagal", "pesan": "Nomor WhatsApp tidak valid."}, status_code=400)

    # Jeda per-nomor (bukan per-IP) - ini yang mencegah nomor orang lain
    # dibanjiri pesan "kode OTP" walau permintaannya datang dari IP berbeda-beda.
    existing = OTP_STORE.get(no_wa)
    if existing and (time.time() - existing.get("requested_at", 0)) < OTP_COOLDOWN_DETIK:
        return JSONResponse({"status": "gagal", "pesan": "Kode OTP untuk nomor ini baru saja dikirim. Tunggu sebentar sebelum minta lagi."}, status_code=429)

    code = f"{secrets.randbelow(1_000_000):06d}"
    OTP_STORE[no_wa] = {"code": code, "expires_at": time.time() + OTP_TTL_DETIK, "attempts": 0, "requested_at": time.time()}

    chat_id = f"{no_wa}@c.us"
    pesan_otp = f"Kode verifikasi Rumah Amal USK Anda: *{code}*\nBerlaku 5 menit. Jangan berikan kode ini kepada siapa pun."
    try:
        send_message_to_waha(chat_id, pesan_otp)
    except Exception as e:
        return JSONResponse({"status": "gagal", "pesan": f"Gagal mengirim kode OTP: {e}"}, status_code=502)

    return JSONResponse({"status": "sukses", "pesan": "Kode OTP telah dikirim via WhatsApp."})


@router.post("/api/web-otp/verify")
async def verify_otp(request: Request, payload: dict):
    no_wa_raw = (payload.get("wa_number") or "").strip()
    kode_input = (payload.get("otp_code") or "").strip()
    no_wa = _normalisasi_wa(no_wa_raw)

    entry = OTP_STORE.get(no_wa)
    if not entry:
        return JSONResponse({"status": "gagal", "pesan": "Belum ada kode OTP untuk nomor ini. Minta kode baru ya."}, status_code=400)

    if time.time() > entry["expires_at"]:
        OTP_STORE.pop(no_wa, None)
        return JSONResponse({"status": "gagal", "pesan": "Kode OTP sudah kedaluwarsa. Minta kode baru ya."}, status_code=400)

    entry["attempts"] += 1
    if entry["attempts"] > OTP_MAKS_PERCOBAAN:
        OTP_STORE.pop(no_wa, None)
        return JSONResponse({"status": "gagal", "pesan": "Terlalu banyak percobaan salah. Minta kode baru ya."}, status_code=429)

    if not secrets.compare_digest(kode_input, entry["code"]):
        return JSONResponse({"status": "gagal", "pesan": "Kode OTP salah. Coba lagi."}, status_code=400)

    OTP_STORE.pop(no_wa, None)

    sapaan = deteksi_sapaan_gender(None)
    reply = _format_riwayat(no_wa, sapaan)

    return _json_with_session(request, {"status": "sukses", "reply": reply})


@router.post("/api/web-chat/upload-resi")
async def upload_resi(
    request: Request,
    file: UploadFile = File(...),
    wa_number: str = Form(...),
    caption: str = Form(""),
):
    if not _check_rate_limit("upload-resi", _client_ip(request), max_calls=10, window_detik=60):
        return _json_with_session(request, {"status": "gagal", "reply": "Terlalu banyak unggahan dalam waktu singkat, coba lagi sebentar ya 🙏"}, status_code=429)

    no_wa = _normalisasi_wa(wa_number)
    if len(no_wa) < 10:
        return _json_with_session(request, {"status": "gagal", "reply": "Nomor WhatsApp belum valid, coba isi ulang ya Kak."})

    image_bytes = await file.read()

    if len(image_bytes) > MAKS_UKURAN_RESI_BYTES:
        return _json_with_session(request, {"status": "gagal", "reply": "Ukuran file terlalu besar (maks 5MB). Coba unggah foto dengan ukuran lebih kecil ya."})

    if not _sniff_gambar_valid(image_bytes):
        return _json_with_session(request, {"status": "gagal", "reply": "Berkas yang diunggah bukan format gambar yang didukung. Coba unggah foto JPG/PNG resi transfernya ya."})

    data = ekstrak_resi_vision(image_bytes, caption=caption)
    nama_terbaca = data.get("nama") or "(nama tidak terbaca)"
    nominal_terbaca = data.get("nominal")
    program_terbaca = data.get("program") or "UMUM"

    pesan_admin = (
        f"🌐 [RESI DARI WEB CHAT] Ada bukti transfer diunggah lewat website:\n"
        f"👤 *Nama (hasil baca AI):* {nama_terbaca}\n"
        f"📞 *No. WA:* {no_wa}\n"
        f"💰 *Nominal (hasil baca AI):* {('Rp ' + format(int(nominal_terbaca), ',')) if nominal_terbaca else 'Tidak terbaca'}\n"
        f"📌 *Program:* {PETA_NAMA.get(program_terbaca, program_terbaca)}\n"
        f"Mohon diverifikasi & dicatat manual ya - unggahan dari web belum otomatis tersimpan ke database."
    )
    try:
        notify_admin(pesan_admin)
    except Exception as e:
        print(f"[Warning Web Resi Notify Admin] {e}")

    reply = (
        "Alhamdulillah! 🙏 Bukti transfer Kakak sudah Mimin terima dan teruskan ke admin untuk diverifikasi manual. "
        "Admin akan segera mencatat donasinya. Jazakallahu Khairan atas kepercayaannya kepada Rumah Amal USK! ✨"
    )
    return _json_with_session(request, {"status": "sukses", "reply": reply})
