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
from services.media_validator import MAKS_UKURAN_RESI_BYTES, sniff_gambar_valid as _sniff_gambar_valid

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


def _get_session(request: Request) -> tuple[str, dict, bool]:
    """Kembalikan (token, session_dict, perlu_set_cookie_baru).

    Di-cache di request.state supaya dipanggil berkali-kali dalam 1 request
    (mis. sekali untuk logika balasan, sekali lagi di _json_with_session)
    tetap mengembalikan token yang SAMA - request.cookies tidak berubah
    walau response.set_cookie() sudah dipanggil, jadi tanpa cache ini token
    baru bisa ke-generate dua kali dalam satu request yang sama dan diam-diam
    menciptakan 2 sesi berbeda dari 1 kunjungan (last_program_key yang
    di-set lewat token pertama jadi tidak pernah kepakai lagi)."""
    cached = getattr(request.state, "web_session", None)
    if cached:
        return cached

    token = request.cookies.get(SESSION_COOKIE)
    if token and token in WEB_SESSIONS:
        result = (token, WEB_SESSIONS[token], False)
    else:
        token = secrets.token_urlsafe(16)
        WEB_SESSIONS[token] = {"last_program_key": None, "last_donation_category": None}
        result = (token, WEB_SESSIONS[token], True)

    request.state.web_session = result
    return result


def _json_with_session(request: Request, data: dict, status_code: int = 200) -> JSONResponse:
    token, _session, is_new = _get_session(request)
    response = JSONResponse(data, status_code=status_code)
    if is_new:
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=request.url.scheme == "https")
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


# Fallback "tidak_diketahui" milik QA_SCRIPT dirancang untuk WhatsApp - isinya
# minta user "Ketik 1/2/0" yang tidak berlaku sama sekali di web (tidak ada
# FSM/navigasi angka di kanal ini). Web pakai fallback sendiri yang mengarah
# ke pintasan panel kiri, bukan instruksi ketik angka yang menyesatkan.
_WEB_FALLBACK_REPLY = (
    "Wah, Mimin kurang paham nih kalau mengenai hal itu 🙏\n\n"
    "Mimin fokus membantu seputar *Zakat, Infak, Sedekah,* serta *Program Beasiswa USK* ya Bapak/Ibu. "
    "Coba klik salah satu pintasan di panel kiri, atau tanyakan dengan kalimat lain ya 😊"
)

# get_program_list()/format_program_response() (program_manager.py) diakhiri
# footer "Ketik angka 1 s.d. N" / "Ketik 0" - instruksi navigasi FSM khusus
# WhatsApp yang tidak berlaku di web (susun_balasan() hanya mengenali follow-up
# berbasis kalimat seperti "syarat"/"detail", bukan angka). Potong footer itu
# lalu ganti dengan ajakan yang benar-benar berfungsi di kanal ini.
#
# Pola dibatasi HANYA ke baris-baris berawalan "• " setelah header-nya (bukan
# ".*" rakus sampai akhir string) - beberapa balasan (mis. candaan warna Green
# Qurban di admin_scripts.py) menambahkan catatan tambahan SETELAH footer ini;
# pola rakus sebelumnya ikut memakan catatan itu juga, bukan cuma footernya.
_NAV_FOOTER_PATTERN = re.compile(r"\n-{5,}\n📌 \*Pilihan Navigasi:\*(?:\n• [^\n]*)*")
_WEB_PROGRAM_HINT = "\n\n💬 Tanya bebas soal syarat, proses, atau detail programnya ya, Bapak/Ibu!"


def _bersihkan_navigasi_wa(reply: str) -> str:
    hasil, jumlah_potong = _NAV_FOOTER_PATTERN.subn("", reply)
    if jumlah_potong:
        hasil = hasil.rstrip() + _WEB_PROGRAM_HINT
    return hasil


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
        return _json_with_session(request, {"reply": "Boleh diketik dulu pesannya, Bapak/Ibu 🙏", "requires_otp": False})

    token, session, _is_new = _get_session(request)
    state_manager.catat_pesan("web", token, "user", pesan)

    pesan_clean = pesan.lower().strip()

    if _is_cek_riwayat(pesan_clean):
        reply = "Untuk melihat riwayat transaksi, Mimin perlu verifikasi nomor WhatsApp Bapak/Ibu dulu ya - demi menjaga data donasi tetap aman 🙏"
        state_manager.catat_pesan("web", token, "bot", reply)
        return _json_with_session(request, {"reply": reply, "requires_otp": True})

    hasil = susun_balasan(
        pesan,
        context={
            "last_program_key": session.get("last_program_key"),
            "last_donation_category": session.get("last_donation_category"),
        },
        nama_pengirim="",
    )
    session["last_program_key"] = hasil.get("last_program_key")
    # Kategori ZIS (Zakat Mal/Penghasilan/Infak Rutin/dst) yang baru saja
    # disebutkan user secara eksplisit - dipakai upload_resi() di bawah
    # sebagai sinyal kategori utama saat resi diunggah, MENGGANTIKAN tebakan
    # AI baca gambar yang jarang benar-benar menyebut kategori zakat/infak
    # apa pun di kwitansi transfer bank (lihat catatan panjang di
    # admin_scripts.py klasifikasi_pesan() untuk kronologi bug ini).
    session["last_donation_category"] = hasil.get("kode_program_donasi")

    if "tidak_diketahui" in hasil.get("intents", []):
        reply = _WEB_FALLBACK_REPLY
    else:
        reply = _bersihkan_navigasi_wa(hasil["reply"])
    state_manager.catat_pesan("web", token, "bot", reply)
    return _json_with_session(request, {"reply": reply, "requires_otp": False})


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
        send_message_to_waha(chat_id, pesan_otp, catat_log=False)
    except Exception as e:
        return JSONResponse({"status": "gagal", "pesan": f"Gagal mengirim kode OTP: {e}"}, status_code=502)

    token, _session, _is_new = _get_session(request)
    state_manager.catat_pesan("web", token, "sistem", f"Kode OTP dikirim ke {no_wa}")

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

    token, _session, _is_new = _get_session(request)
    state_manager.catat_pesan("web", token, "sistem", f"Verifikasi OTP berhasil untuk {no_wa}")
    state_manager.catat_pesan("web", token, "bot", reply)

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
        return _json_with_session(request, {"status": "gagal", "reply": "Nomor WhatsApp belum valid, coba isi ulang ya Bapak/Ibu."})

    image_bytes = await file.read()

    if len(image_bytes) > MAKS_UKURAN_RESI_BYTES:
        return _json_with_session(request, {"status": "gagal", "reply": "Ukuran file terlalu besar (maks 5MB). Coba unggah foto dengan ukuran lebih kecil ya."})

    if not _sniff_gambar_valid(image_bytes):
        return _json_with_session(request, {"status": "gagal", "reply": "Berkas yang diunggah bukan format gambar yang didukung. Coba unggah foto JPG/PNG resi transfernya ya."})

    data = ekstrak_resi_vision(image_bytes, caption=caption)
    nama_terbaca = data.get("nama") or "(nama tidak terbaca)"
    nominal_terbaca = data.get("nominal")  # sudah divalidasi >= Rp 1.000 di ekstrak_resi_vision

    token, session, _is_new = _get_session(request)
    # Kategori yang sudah disebutkan eksplisit di chat sebelumnya (mis. "saya
    # ingin berdonasi zakat mal") lebih dipercaya daripada tebakan AI baca
    # gambar resi - kwitansi transfer bank jarang benar-benar mencantumkan
    # kategori zakat/infak apa pun, jadi ekstrak_resi_vision() hampir selalu
    # cuma menebak/default ke "UMUM" walau user sudah menyatakan niatnya
    # dengan jelas. Dipakai sekali lalu dibersihkan supaya tidak "bocor" ke
    # donasi lain yang tidak terkait di sesi web yang sama.
    program_dari_sesi = session.get("last_donation_category")
    session["last_donation_category"] = None
    program_terbaca = program_dari_sesi or data.get("program") or "UMUM"

    state_manager.catat_pesan("web", token, "user", (caption or "") + "\n📷 (kiriman bukti transfer)")

    # Tersimpan sebagai 'pending' - identitas pengunjung web belum terverifikasi
    # OTP saat upload, jadi admin yang memvalidasi manual lewat dashboard
    # sebelum dianggap donasi sah (beda dari WhatsApp yang auto-'validated'
    # karena identitasnya sudah pasti dari sesi WA).
    #
    # SELALU disimpan walau nominal gagal terbaca (nominal_terbaca falsy) -
    # sebelumnya baris ini ada di dalam `if nominal_terbaca:` saja, jadi kalau
    # OCR gagal baca nominal, TIDAK ADA transaksi tersimpan sama sekali walau
    # pesan notifikasi ke admin di bawah tetap bilang "Cek & validasi di Admin
    # Dashboard" - resi & gambarnya lenyap begitu saja, admin tidak punya apa
    # pun untuk dicek/dikoreksi manual. Nominal 0 di sini murni placeholder
    # yang wajib dikoreksi admin sebelum divalidasi (bukan klaim "0 rupiah").
    state_manager.simpan_transaksi_final(
        no_wa, nama_terbaca, nominal_terbaca or 0, kode_program=program_terbaca,
        status_verifikasi="pending", sumber="web", resi_bytes=image_bytes,
    )
    status_teks = "menunggu validasi admin di dashboard" if nominal_terbaca else "nominal tidak terbaca otomatis, mohon dicek & isi manual di dashboard"

    pesan_admin = (
        f"🌐 [RESI DARI WEB CHAT] Ada bukti transfer diunggah lewat website:\n"
        f"👤 *Nama (hasil baca AI):* {nama_terbaca}\n"
        f"📞 *No. WA:* {no_wa}\n"
        f"💰 *Nominal (hasil baca AI):* {('Rp ' + format(int(nominal_terbaca), ',')) if nominal_terbaca else 'Tidak terbaca'}\n"
        f"📌 *Program:* {PETA_NAMA.get(program_terbaca, program_terbaca)}\n"
        f"Status: {status_teks}. Cek & validasi di Admin Dashboard > Data Transaksi."
    )
    try:
        notify_admin(pesan_admin)
    except Exception as e:
        print(f"[Warning Web Resi Notify Admin] {e}")

    reply = (
        "Alhamdulillah! 🙏 Bukti transfer Bapak/Ibu sudah Mimin terima dan tercatat untuk diverifikasi admin. "
        "Setelah divalidasi, donasinya akan resmi tercatat. Jazakallahu Khairan atas kepercayaannya kepada Rumah Amal USK! ✨"
    )
    state_manager.catat_pesan("web", token, "bot", reply)
    return _json_with_session(request, {"status": "sukses", "reply": reply})
