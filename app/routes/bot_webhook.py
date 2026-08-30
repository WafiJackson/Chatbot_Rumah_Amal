from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import requests
import os
import re
import secrets

from admin_scripts import ambil_balasan, susun_balasan
from services.llm_agent import (
    ekstrak_data_ner,
    ekstrak_konfirmasi_donasi,
    ekstrak_resi_vision,
)
from services import state_manager
from services.form_parser import ekstrak_formulir
from services.program_manager import get_program_info, format_program_response
from services.gender_detector import deteksi_sapaan_gender
from services.logger import logger
from services.media_validator import MAKS_UKURAN_RESI_BYTES, sniff_gambar_valid, unduh_dengan_batas_ukuran

router = APIRouter()
WAHA_ENDPOINT = os.getenv("WAHA_ENDPOINT", "http://waha-gateway:3000").rstrip("/")
WAHA_SEND_URL = f"{WAHA_ENDPOINT}/api/sendText"
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "")
if not WAHA_API_KEY:
    logger.warning("[Config] WAHA_API_KEY tidak diset di environment. Panggilan ke WAHA kemungkinan akan gagal otentikasi.")

# Endpoint /webhook TIDAK dilindungi otentikasi apapun sebelum ini - siapa saja
# yang tahu URL-nya (dan port 8000 sempat ter-bind ke semua interface) bisa
# mengirim payload WAHA palsu, memicu bot mengirim WA ke sembarang nomor,
# men-spam notifikasi admin, atau menghabiskan kuota Gemini. WEBHOOK_SECRET
# wajib cocok (lewat query string ?secret=...) sebelum payload diproses -
# nilainya disisipkan ke WHATSAPP_HOOK_URL di docker-compose.yml.
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
if not WEBHOOK_SECRET:
    logger.warning("[Config] WEBHOOK_SECRET tidak diset - endpoint /webhook TIDAK terlindungi otentikasi apapun.")

user_sessions = {}

# Nomor rekening resmi Rumah Amal USK (satu sumber kebenaran, jangan hardcode ulang)
BANK_REKENING_INFO = "🏦 *Bank BSI:* 7099400409\n👤 *a.n.* Rumah Amal Mesjid Unsyiah"

# Pemetaan kode program -> nama layar. Modul-level (bukan lokal di dalam
# waha_webhook) karena _dapatkan_doa_spesifik() di bawah ini juga memakainya.
PETA_NAMA = {
    "ZKT-MAL": "Zakat Mal",
    "ZKT-PENGHASILAN": "Zakat Penghasilan",
    "INF-RUTIN": "Infak Rutin",
    "DONASI": "Donasi (Bantuan Kemanusiaan)",
    "PINTAS": "PINTAS (Pinjaman Tanpa Syarat)",
    "BPRA-UKT": "BPRA-UKT",
    "DON-PALESTINA": "OTA Palestina",
    "GREEN-QURBAN": "GREEN QURBAN",
    "NASI-BUNGKUS": "Bantuan Nasi Bungkus",
    "ECRA": "ECRA",
    "P2EMD": "P2EMD",
    "BEASISWA-OTA": "Beasiswa Orang Tua Asuh (OTA)",
    "BEASISWA-MUALLAF": "Beasiswa Muallaf",
    "BPMI": "BPMI"
}


def _nominal_valid(raw) -> str | None:
    """Validasi nominal sebelum disimpan sebagai transaksi.
    Nominal dari ekstraksi LLM (teks/vision) bisa berupa hasil halusinasi atau
    salah-parse pesan ambigu (mis. angka menu '2'/'3' yang nyasar ke jalur NER
    saat FSM belum ter-reset) - tanpa validasi ini, nilai sekecil '5' bisa lolos
    tersimpan ke database atas nama pengirim. Syarat sama dengan yang sudah
    dipakai di ekstrak_resi_vision(): angka murni dan >= Rp 1.000."""
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", str(raw))
    if digits and int(digits) >= 1000:
        return digits
    return None


def _sapaan_dengan_nama(sapaan: str, nama: str) -> str:
    """Gabungkan sapaan gender + nama, hindari duplikasi kata seperti 'Kak Kak'
    saat nama tidak diketahui dan kebetulan sama dengan kata sapaan itu sendiri."""
    nama_bersih = (nama or "").strip()
    if not nama_bersih or nama_bersih.lower() == sapaan.strip().lower():
        return sapaan
    return f"{sapaan} {nama_bersih}"


LAST_HEALTH_ALERT_TIME = 0


def check_waha_session_health():
    """
    Memeriksa kesehatan sesi WAHA (Health Check) dan mengirim notifikasi alert ke Admin WA
    jika status sesi WhatsApp terputus (DISCONNECTED / PAUSED / STOPPED).
    """
    global LAST_HEALTH_ALERT_TIME
    import time
    now = time.time()
    if now - LAST_HEALTH_ALERT_TIME < 300:
        return

    try:
        url = f"{WAHA_ENDPOINT}/api/sessions"
        res = requests.get(url, headers={"X-Api-Key": WAHA_API_KEY}, timeout=3)
        if res.status_code == 200:
            sessions = res.json()
            is_working = any(s.get("status") == "WORKING" for s in sessions)
            if not is_working:
                LAST_HEALTH_ALERT_TIME = now
                notify_admin(
                    "⚠️ [ALERT SYSTEM] Sesi WhatsApp WAHA terdeteksi TIDAK AKTIF (PAUSED/DISCONNECTED). Mohon lakukan scan QR ulang via Dashboard WAHA."
                )
    except Exception as e:
        print(f"[Warning Health Check WAHA] {e}")


def _get_active_waha_session() -> str:
    """Mengambil nama sesi WAHA yang sedang aktif (WORKING)."""
    try:
        url = f"{WAHA_ENDPOINT}/api/sessions"
        res = requests.get(url, headers={"X-Api-Key": WAHA_API_KEY}, timeout=2)
        if res.status_code == 200:
            sessions = res.json()
            for s in sessions:
                if s.get("status") == "WORKING":
                    return s.get("name", "default")
    except Exception as e:
        print(f"[Warning WAHA Sessions Fetch] {e}")
    return "default"


def _resolve_waha_chat_id(chat_id: str, session_name: str) -> str:
    """Menerjemahkan nomor HP / chatId (misal 6281234567890) ke chatId/LID resmi dari WhatsApp WAHA."""
    if not chat_id:
        return chat_id
    if "@lid" in chat_id:
        return chat_id

    digits = re.sub(r"[^\d]", "", chat_id)
    if digits:
        try:
            url = f"{WAHA_ENDPOINT}/api/contacts/check-exists?phone={digits}&session={session_name}"
            res = requests.get(url, headers={"X-Api-Key": WAHA_API_KEY}, timeout=3)
            if res.status_code == 200:
                data = res.json()
                if data.get("numberExists") and data.get("chatId"):
                    resolved = data.get("chatId")
                    print(f"[Debug WAHA ChatId Resolve] {chat_id} -> {resolved}")
                    return resolved
        except Exception as e:
            print(f"[Warning WAHA Resolve ChatId] {e}")
    return chat_id


_CONTACT_CACHE = {}


def _dapatkan_nomor_hp_asli(chat_id_asli: str, payload_waha: dict = None, session_name: str = "default") -> tuple[str, str]:
    """
    Menerjemahkan chat_id_asli (termasuk jika berupa @lid seperti 39303296057346@lid)
    menjadi (nomor_hp_cantik, nama_pengirim). Contoh: ('081269666776', 'Yafi Hidayatullah').
    """
    if not chat_id_asli:
        return ("0000000000", "Pengguna")

    clean_id = chat_id_asli.split("@")[0]

    # 1. Cek jika sudah format nomor 62/08 biasa
    if clean_id.startswith("62") and len(clean_id) >= 10:
        formatted = f"0{clean_id[2:]}"
        nama = (payload_waha or {}).get("pushname") or (payload_waha or {}).get("notifyName") or "Donatur"
        return (formatted, nama)

    if clean_id in _CONTACT_CACHE:
        return _CONTACT_CACHE[clean_id]

    if not session_name or session_name == "default":
        session_name = _get_active_waha_session()

    try:
        url = f"{WAHA_ENDPOINT}/api/contacts/all?session={session_name}"
        res = requests.get(url, headers={"X-Api-Key": WAHA_API_KEY}, timeout=3)
        if res.status_code == 200:
            contacts = res.json()
            for c in contacts:
                cid = c.get("id", "")
                num = c.get("number", "")
                if (clean_id in cid or clean_id in num) and "@c.us" in cid:
                    phone_digits = re.sub(r"[^\d]", "", cid.split("@")[0])
                    formatted_phone = f"0{phone_digits[2:]}" if phone_digits.startswith("62") else phone_digits
                    nama = c.get("pushname") or c.get("name") or "Donatur"
                    _CONTACT_CACHE[clean_id] = (formatted_phone, nama)
                    return (formatted_phone, nama)
    except Exception as e:
        print(f"[Warning Resolve LID Contact] {e}")

    # Fallback to ADMIN_WA_NUMBER if matching admin LID
    admin_wa = os.getenv("ADMIN_WA_NUMBER", "")
    admin_digits = re.sub(r"[^\d]", "", admin_wa)
    if clean_id in [admin_digits, "39303296057346"]:
        formatted_phone = f"0{admin_digits[2:]}" if admin_digits.startswith("62") else admin_digits
        nama = (payload_waha or {}).get("pushname") or "Yafi Hidayatullah"
        return (formatted_phone, nama)

    return (clean_id, (payload_waha or {}).get("pushname") or "Donatur")



def send_message_to_waha(chat_id: str, text: str, session_name: str = "default", catat_log: bool = True):
    # Catat balasan bot ke log_percakapan (untuk halaman admin Log Bot) -
    # kecuali kalau tujuannya nomor admin sendiri (notifikasi internal,
    # bukan percakapan dengan donatur). catat_log=False dipakai pengirim OTP
    # supaya kode verifikasi TIDAK PERNAH tersimpan apa adanya ke database -
    # kredensial semacam itu tidak seharusnya pernah masuk log permanen,
    # meski masa berlakunya cuma 5 menit.
    digits_tujuan = re.sub(r"[^\d]", "", chat_id or "")
    digits_admin = re.sub(r"[^\d]", "", ADMIN_WA_NUMBER)
    if digits_tujuan and digits_tujuan != digits_admin:
        try:
            teks_log = text if catat_log else "Kode OTP dikirim"
            dari_log = "bot" if catat_log else "sistem"
            state_manager.catat_pesan("whatsapp", state_manager.normalisasi_no_wa(digits_tujuan), dari_log, teks_log)
        except Exception as e:
            print(f"[Warning Log Percakapan] {e}")

    # 1. Jika session_name bawaan 'default', cari sesi aktif di WAHA
    if not session_name or session_name == "default":
        session_name = _get_active_waha_session()

    # 2. Resolusi chatId ke LID resmi WhatsApp jika tersedia
    real_chat_id = _resolve_waha_chat_id(chat_id, session_name)

    payload = {
        "chatId": real_chat_id,
        "text": text,
        "session": session_name
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Api-Key": WAHA_API_KEY
    }
    try:
        res = requests.post(WAHA_SEND_URL, json=payload, headers=headers)
        if res.status_code in [200, 201]:
            msg_log = f"[Sukses] Pesan telah dikirim ke WA: {real_chat_id} (Session: {session_name})"
            print(msg_log)
            logger.info(msg_log)
        else:
            msg_log = f"[Warning WAHA Send] HTTP {res.status_code}: {res.text}"
            print(msg_log)
            logger.warning(msg_log)
    except Exception as e:
        msg_log = f"[Error Mengirim ke WAHA] {e}"
        print(msg_log)
        logger.error(msg_log)




def send_whatsapp_reply(chat_id: str, text: str, session_name: str = "default"):
    """Alias helper untuk mengirim balasan pesan ke pengguna WhatsApp."""
    send_message_to_waha(chat_id, text, session_name)


ADMIN_WA_NUMBER = os.getenv("ADMIN_WA_NUMBER", "")
if not ADMIN_WA_NUMBER:
    logger.warning("[Config] ADMIN_WA_NUMBER tidak diset di environment. Notifikasi & handoff ke admin tidak akan terkirim.")


def notify_admin(pesan_peringatan: str, session_name: str = "default"):
    """Mengirim pesan notifikasi (ping) ke nomor WhatsApp Admin."""
    send_message_to_waha(ADMIN_WA_NUMBER, pesan_peringatan, session_name)



USER_RATE_LIMIT = {}  # {nomor_wa: [timestamps]}
_LAST_RATE_LIMIT_WARNING: dict[str, float] = {}  # cegah spam balasan "mohon tunggu" kalau user terus melewati batas


def _check_rate_limit(nomor_wa: str) -> bool:
    import time
    now = time.time()
    timestamps = USER_RATE_LIMIT.get(nomor_wa, [])
    timestamps = [t for t in timestamps if now - t < 60]
    if len(timestamps) >= 20:
        return False
    timestamps.append(now)
    USER_RATE_LIMIT[nomor_wa] = timestamps
    return True


def _dapatkan_doa_spesifik(program_code: str, nama_donatur: str = "Bapak/Ibu", nominal_fmt: str = "", program_diketahui: bool = True) -> str:
    """Mengambil variasi Doa Syar'i acak dari admin_scripts.

    program_diketahui=False dipakai saat user cuma kirim resi/konfirmasi
    mentah tanpa pernah menyebut program donasinya (mis. langsung diarahkan
    dari web tanpa basa-basi) - balasan tidak akan mengarang nama program."""
    try:
        from admin_scripts import _dapatkan_doa_spesifik as gen_doa
        prog_name = PETA_NAMA.get(program_code, program_code or "Donasi")
        return gen_doa(prog_name, nama_donatur, nominal_fmt, program_diketahui=program_diketahui)
    except Exception as e:
        print(f"[Warning Doa Gen] {e}")
        nom_teks = f" sebesar *Rp {nominal_fmt}*" if nominal_fmt else ""
        label = "Donasi/Penyaluran" if program_diketahui else "Bukti pembayaran"
        return (
            f"Alhamdulillah, terima kasih {nama_donatur}! 🙏\n"
            f"{label}{nom_teks} sudah kami terima dan InsyaAllah akan segera disalurkan kepada penerima yang berhak."
        )


PROCESSED_MSG_IDS = set()


@router.post("/webhook")
@router.post("/api/webhook")
async def waha_webhook(request: Request):
    # Verifikasi secret SEBELUM apapun lain diproses (termasuk parsing body) -
    # menolak lebih awal supaya request tak terotentikasi tidak sempat memicu
    # efek samping (kirim WA, panggil Gemini, tulis DB) sama sekali.
    secret_diterima = request.query_params.get("secret", "")
    if not WEBHOOK_SECRET or not secrets.compare_digest(secret_diterima, WEBHOOK_SECRET):
        logger.warning(f"[Keamanan] Percobaan akses /webhook tanpa secret yang valid dari {request.client.host if request.client else 'unknown'}.")
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    try:
        data = await request.json()
        if not isinstance(data, dict):
            data = {}

        event_name = data.get("event") or ""
        payload_waha = data.get("payload")
        if not isinstance(payload_waha, dict):
            payload_waha = {}

        media_obj = payload_waha.get("media")
        if not isinstance(media_obj, dict):
            media_obj = {}

        data_obj = payload_waha.get("_data")
        if not isinstance(data_obj, dict):
            data_obj = {}

        chat_id_asli = payload_waha.get("from") or ""
        nama_sesi = data.get("session") or "default"

        # KASUS 2: Filter event Panggilan Suara / Video (call)
        if "call" in event_name or payload_waha.get("type") in ["call", "call_log", "voice_call"]:
            send_whatsapp_reply(
                chat_id_asli,
                "Mohon maaf, bot Rumah Amal USK tidak dapat menerima panggilan suara/video. Silakan kirimkan pertanyaan atau permohonan Anda melalui pesan teks WhatsApp. Terima kasih! 🙏",
                nama_sesi
            )
            return {"status": "sukses", "intent": "panggilan_suara_diabaikan"}

        # Filter event type WAHA (hanya proses pesan teks / media utama, abaikan ack / reaction / update)
        # Catatan: WAHA mengirim event "message.ack" untuk SETIAP status pengiriman
        # (sent/delivered/read) dari pesan yang KITA kirim sendiri. Payload-nya tidak
        # selalu punya field "fromMe", jadi kalau lolos di sini ia bisa diproses seolah
        # pesan masuk baru dan berakhir jadi balasan "tidak_diketahui" duplikat -
        # makanya event semacam ini harus ditolak eksplisit, bukan hanya diserahkan ke
        # cocokan substring "message" yang longgar.
        ALLOWED_EVENTS = {"message", "message.upsert", "message.create"}
        EVENT_BUKAN_PESAN_BARU = ("ack", "reaction", "revoked", "edited", "status", "seen", "read", "typing", "presence", "poll")
        if event_name not in ALLOWED_EVENTS:
            if "message" not in event_name or any(kata in event_name for kata in EVENT_BUKAN_PESAN_BARU):
                return {"status": "diabaikan"}

        if payload_waha.get("fromMe") is True:
            return {"status": "diabaikan"}

        # Filter khusus Stiker WhatsApp (Abaikan stiker agar tidak memicu doa/error)
        mimetype_raw = str(media_obj.get("mimetype") or payload_waha.get("mimetype") or "").lower()
        if payload_waha.get("type") in ["sticker", "ptt", "audio"] or "webp" in mimetype_raw:
            return {"status": "diabaikan_stiker"}

        # KASUS 1 & Deduplikasi: Mencegah race condition dari webhook ganda / replay
        msg_id = payload_waha.get("id") or (data_obj.get("id", {}).get("_serialized") if isinstance(data_obj.get("id"), dict) else None)
        if msg_id:
            if msg_id in PROCESSED_MSG_IDS:
                print(f"[Deduplikasi] Pesan ID {msg_id} telah diproses sebelumnya. Mengabaikan event duplikat.")
                return {"status": "duplikasi_diabaikan"}
            PROCESSED_MSG_IDS.add(msg_id)
            if len(PROCESSED_MSG_IDS) > 2000:
                PROCESSED_MSG_IDS.clear()

        pesan = payload_waha.get("body") or ""
        raw_no_wa = payload_waha.get("author") or chat_id_asli
        nomor_wa = raw_no_wa.split('@')[0] if raw_no_wa else "0000000000"

        # Rate Limiter Anti-Spam (Maksimal 20 pesan per menit per nomor WA)
        if not _check_rate_limit(nomor_wa):
            print(f"[Rate Limit Exceeded] Nomor {nomor_wa} melampaui batas 20 pesan/menit.")
            # Sebelumnya pesan yang kena limit lenyap TANPA JEJAK sama sekali -
            # tidak dicatat ke Log Bot, tidak ada balasan apapun ke user
            # (ditemukan 29 Agustus - pesan asli user hilang dari Log Bot admin
            # tanpa penjelasan). Sekarang tetap dicatat, dan user diberi tahu
            # jujur untuk KIRIM ULANG nanti - server 1-worker tidak bisa
            # "menunggu lalu otomatis membalas" tanpa membekukan semua user
            # lain, jadi tidak dijanjikan balasan otomatis susulan.
            try:
                state_manager.catat_pesan(
                    "whatsapp", state_manager.normalisasi_no_wa(nomor_wa), "user",
                    (payload_waha.get("body") or "") or "📷 (kiriman gambar)",
                )
            except Exception as e:
                print(f"[Warning Log Percakapan - Rate Limited] {e}")

            import time
            now_rl = time.time()
            peringatan_terakhir = _LAST_RATE_LIMIT_WARNING.get(nomor_wa, 0)
            if now_rl - peringatan_terakhir > 20:
                _LAST_RATE_LIMIT_WARNING[nomor_wa] = now_rl
                send_message_to_waha(
                    chat_id_asli,
                    "Mohon maaf, terlalu banyak pesan dalam waktu singkat 🙏 Mohon tunggu sekitar 1 menit, lalu kirim ulang pesan terakhir Anda ya.",
                    nama_sesi,
                )
            return {"status": "rate_limit_exceeded"}
        has_media = payload_waha.get("hasMedia", False) or bool(payload_waha.get("media")) or bool(payload_waha.get("mediaUrl"))

        # Jaring pengaman kedua: event tanpa teks DAN tanpa media bukan pesan
        # sungguhan dari user (biasanya sisa event status/ack yang lolos dari filter
        # di atas). Daripada dipaksa masuk ke susun_balasan() dan berakhir jadi
        # balasan "tidak_diketahui" yang nyasar ke user, abaikan saja di sini.
        if not pesan.strip() and not has_media:
            return {"status": "diabaikan_tanpa_konten"}

        # "" (bukan lagi "Kak") sebagai fallback saat WAHA tidak memberi nama sama
        # sekali - dibiarkan kosong supaya deteksi_sapaan_gender()/
        # _sapaan_dengan_nama() jatuh ke sapaan "Bapak/Ibu" polos, bukan
        # menggabungkannya jadi "Bapak/Ibu Kak" yang janggal.
        nama_pengirim = (
            payload_waha.get("pushname") or
            payload_waha.get("notifyName") or
            payload_waha.get("_data", {}).get("notifyName") or
            ""
        )

        print(f"[Teks Diterima] Dari: {nama_pengirim} ({nomor_wa}) | Media: {has_media} | Pesan: '{pesan}'")

        try:
            state_manager.catat_pesan(
                "whatsapp", state_manager.normalisasi_no_wa(nomor_wa), "user",
                pesan if pesan else "📷 (kiriman gambar)",
            )
        except Exception as e:
            print(f"[Warning Log Percakapan] {e}")

        session_data = user_sessions.get(nomor_wa, {"state": "IDLE", "last_program_key": None, "last_intents": []})
        if not isinstance(session_data, dict):
            session_data = {"state": session_data or "IDLE", "last_program_key": None, "last_intents": []}

        # Unduh / decode gambar jika payload mengandung media
        image_bytes = None
        if has_media:
            # 1. Decode base64 dari payload WAHA (hanya jika data penuh > 5KB)
            media_data = (
                payload_waha.get("media", {}).get("data") or
                payload_waha.get("data")
            )
            mimetype = (
                payload_waha.get("media", {}).get("mimetype") or
                payload_waha.get("mimetype") or ""
            )

            if media_data and len(media_data) > 5000:
                import base64
                try:
                    image_bytes = base64.b64decode(media_data)
                    if len(image_bytes) > MAKS_UKURAN_RESI_BYTES:
                        print(f"[Warning Media] Gambar base64 melebihi batas {MAKS_UKURAN_RESI_BYTES} bytes, diabaikan.")
                        image_bytes = None
                    else:
                        print(f"[Debug Media] Berhasil decode base64 gambar ({len(image_bytes)} bytes)")
                except Exception as e_b64:
                    print(f"[Warning Base64 Media Decode] {e_b64}")

            # 2. Jika base64 tidak ada atau hanya thumbnail kecil (<5KB), unduh gambar penuh via URL WAHA
            if not image_bytes or len(image_bytes) < 5000:
                media_url = (
                    payload_waha.get("mediaUrl") or
                    payload_waha.get("media", {}).get("url") or
                    payload_waha.get("_data", {}).get("deprecatedMms3Url") or
                    payload_waha.get("_data", {}).get("directPath")
                )

                # Fix URL WAHA API (ganti localhost:3000 dari payload WAHA menjadi WAHA_ENDPOINT internal Docker)
                if media_url:
                    if "localhost:3000" in media_url or "127.0.0.1:3000" in media_url:
                        media_url = media_url.replace("http://localhost:3000", WAHA_ENDPOINT).replace("http://127.0.0.1:3000", WAHA_ENDPOINT)
                    elif media_url.startswith("/"):
                        media_url = f"{WAHA_ENDPOINT}{media_url}"

                if media_url and media_url.startswith("http"):
                    # Diunduh via streaming dengan batas ukuran - sebelumnya
                    # tidak ada batas sama sekali, jadi gambar sebesar apapun
                    # akan dimuat penuh ke memori sebelum ada kesempatan
                    # ditolak (celah ditemukan lewat audit keamanan 28 Agustus).
                    headers_img = {"X-Api-Key": WAHA_API_KEY, "Accept": "*/*"}
                    hasil_unduh = unduh_dengan_batas_ukuran(media_url, headers_img, timeout=5)
                    if hasil_unduh and len(hasil_unduh) > 1000:
                        image_bytes = hasil_unduh
                        print(f"[Debug Media] Berhasil unduh gambar penuh dari URL ({len(image_bytes)} bytes)")
                    else:
                        print("[Warning Media Download] Gagal unduh atau melebihi batas ukuran.")

            # 3. Fallback: Unduh via WAHA Message Media API jika pesan memiliki ID
            msg_id = payload_waha.get("id") or payload_waha.get("_data", {}).get("id", {}).get("_serialized")
            if (not image_bytes or len(image_bytes) < 5000) and msg_id:
                waha_media_endpoint = f"{WAHA_ENDPOINT}/api/{nama_sesi}/messages/{msg_id}/media"
                hasil_unduh_msg = unduh_dengan_batas_ukuran(waha_media_endpoint, {"X-Api-Key": WAHA_API_KEY}, timeout=5)
                if hasil_unduh_msg and len(hasil_unduh_msg) > 1000:
                    image_bytes = hasil_unduh_msg
                    print(f"[Debug Media] Berhasil unduh dari WAHA Message API ({len(image_bytes)} bytes)")

            # Validasi akhir: pastikan hasil unduhan benar-benar gambar (sniff
            # magic bytes), bukan sekadar percaya mimetype/ekstensi dari
            # payload - sama seperti pengaman yang sudah ada di Web Chat.
            if image_bytes and not sniff_gambar_valid(image_bytes):
                print("[Warning Media] Berkas yang diunduh bukan format gambar yang dikenali, diabaikan.")
                image_bytes = None




        status_fsm = state_manager.get_status(nomor_wa)
        pesan_clean = (pesan or "").lower().strip()

        sapaan_donatur = deteksi_sapaan_gender(nama_pengirim)

        # =====================================================================
        # FAST-PATH 0: PERMOHONAN BANTUAN PINTAS (INTENT: minta_bantuan_pintas)
        # =====================================================================
        is_minta_pintas = bool(re.search(
            r"(minta|butuh|ajukan|mohon|permohonan|pinjam|pinjaman).*?\b(pintas|bantuan pintas|dana pintas)\b",
            pesan_clean
        )) or (pesan_clean in ["minta bantuan pintas", "butuh bantuan pintas", "ajukan pintas"])

        if is_minta_pintas:
            # 1. Beri tahu user
            send_whatsapp_reply(
                chat_id_asli,
                f"Baik {sapaan_donatur}, permintaan {sapaan_donatur} sedang kami teruskan ke Admin untuk penanganan lebih lanjut. Mohon ditunggu ya.",
                nama_sesi
            )

            # 2. Kirim notifikasi (ping) ke Admin dengan Nomor HP Asli & Nama Pemohon
            nomor_hp_pemohon, nama_pemohon = _dapatkan_nomor_hp_asli(chat_id_asli, payload_waha, nama_sesi)
            pesan_peringatan = (
                f"🆘 [PINTAS/ADMIN] Ada permohonan bantuan dana:\n"
                f"👤 *Nama:* {nama_pemohon}\n"
                f"📞 *No. WA:* {nomor_hp_pemohon}\n"
                f"Mohon segera di-follow up."
            )
            notify_admin(pesan_peringatan, nama_sesi)

            user_sessions[nomor_wa] = session_data
            return {"status": "sukses", "intent": "minta_bantuan_pintas"}

        # =====================================================================
        # FAST-PATH: JENDELA PEMBATALAN SEGERA SETELAH HANDOFF ADMIN BERHASIL
        # =====================================================================
        # Kalau user bilang "ya" mau disambungkan admin, notifikasi SUDAH
        # terlanjur terkirim ke admin ("mohon segera di-follow up"). Kalau
        # pesan BERIKUTNYA langsung berupa niat batal ("eh tidak jadi deh"),
        # tanpa ini admin tidak akan pernah tahu permintaannya sudah tidak
        # relevan lagi - staf berisiko buang waktu follow-up ke user yang
        # sudah berubah pikiran. Jendela ini cuma berlaku utk 1 pesan
        # berikutnya - kalau bukan pembatalan, status dilepas diam-diam
        # (seperti pola "unlocking" lain) supaya pesan itu diproses normal.
        if status_fsm == "ADMIN_BARU_DIHUBUNGI" and not has_media:
            is_retraksi_admin = any(k in pesan_clean for k in ["batal", "cancel", "tidak jadi", "gak jadi", "ga jadi", "enggak jadi", "nggak jadi"])
            session_info_retraksi = state_manager.get_session(nomor_wa)
            nama_prog_retraksi = session_info_retraksi.get("target_program") or "ADMIN"
            state_manager.reset_status(nomor_wa)
            status_fsm = "IDLE"
            if is_retraksi_admin:
                balasan = f"Baik {sapaan_donatur}, sudah kami sampaikan pembatalannya ke Admin. Ada lagi hal lain yang bisa Mimin bantu?"
                nomor_hp_batal, nama_batal = _dapatkan_nomor_hp_asli(chat_id_asli, payload_waha, nama_sesi)
                notify_admin(
                    f"↩️ [PEMBATALAN] Permintaan sebelumnya dari {nama_batal} ({nomor_hp_batal}) untuk *{nama_prog_retraksi}* "
                    f"SUDAH DIBATALKAN oleh user - tidak perlu di-follow up lagi.",
                    nama_sesi,
                )
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "handoff_admin_retraksi"}

        # =====================================================================
        # FAST-PATH 0A: SAPAAN AWAL / MENU UTAMA PADA STATE IDLE ("halo", "0", "menu")
        # =====================================================================
        from admin_scripts import _is_sapaan, _deteksi_waktu_sapaan
        if status_fsm == "IDLE" and not has_media:
            if _is_sapaan(pesan_clean) or pesan_clean in {"p", "ping", "p!", "ping!", "halo", "hai", "hi", "assalamualaikum", "0", "0.", "menu", "menu utama", "kembali", "kembali ke menu utama"}:
                balasan = ambil_balasan("sapaan", nama_pengirim=nama_pengirim, waktu_sapaan=_deteksi_waktu_sapaan(pesan_clean))
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "sapaan"}
        # Fast-Path Unlocking: Jika user sedang di status FSM aktif tetapi mengajukan pertanyaan baru spesifik, reset status ke IDLE
        # Catatan: "batal"/"cancel" SENGAJA tidak dimasukkan - lihat komentar pada
        # KATA_KUNCI_OVERRIDE kedua di bawah (FAST-PATH 2 punya penanganan is_batal
        # sendiri dengan balasan konfirmasi yang jelas; kalau direset diam-diam di
        # sini duluan, balasan itu jadi tidak pernah kepakai).
        KATA_KUNCI_OVERRIDE = ["pinjam", "pintas", "ukt", "bpra", "beasiswa", "alamat", "rekening", "admin", "bantuan ukt", "kurang dana", "lokasi", "jam kerja", "riwayat"]
        if status_fsm in {"PILIH_PROGRAM", "NUNGGU_BUKTI_TRANSFER", "NUNGGU_DATA_KONFIRMASI", "NUNGGU_DATA_INFAK", "TANYA_PROGRAM"} and not has_media:
            if any(k in pesan_clean for k in KATA_KUNCI_OVERRIDE):
                state_manager.reset_status(nomor_wa)
                status_fsm = "IDLE"

        # 1. Pertanyaan Spesifik UKT (Bantuan Biaya UKT) -> Prioritas Utama
        is_tanya_ukt = bool(re.search(r"\b(ukt|bpra|bpra-ukt|bantuan ukt|bayar ukt|kurang dana ukt|biaya ukt)\b", pesan_clean)) or ("ukt" in pesan_clean and any(k in pesan_clean for k in ["bayar", "kurang", "dana", "bantuan", "biaya"]))
        if is_tanya_ukt and status_fsm == "IDLE":
            prog_data = get_program_info("bpra_ukt")
            balasan = (
                f"*{prog_data['nama']}*\n\n"
                f"{prog_data['deskripsi']}\n\n"
                f"*Syarat & Ketentuan:*\n"
                + "\n".join(f"{i}. {s}" for i, s in enumerate(prog_data['syarat'], 1)) +
                f"\n\n🌐 *Website Resmi:* https://rumahamal.usk.ac.id\n\n"
                f"----------------------------------------\n"
                f"📌 *Pilihan Navigasi:*\n"
                f"• Ketik *1* atau *Admin* jika {sapaan_donatur} ingin berkonsultasi / mengajukan permohonan UKT ke Admin\n"
                f"• Ketik *11* untuk Kembali ke Daftar Program\n"
                f"• Ketik *0* untuk Kembali ke Menu Utama"
            )
            state_manager.update_status(nomor_wa, "TANYA_PROGRAM_DETAIL", target_program="bpra_ukt")
            user_sessions[nomor_wa] = session_data
            send_message_to_waha(chat_id_asli, balasan, nama_sesi)
            return {"status": "sukses", "intent": "info_bpra_ukt"}

        # 2. Pertanyaan Spesifik PINTAS (Pinjam / Meminjam Uang) -> Prioritas Utama
        is_tanya_pintas = bool(re.search(r"\b(pintas|pinjam|pinjaman|meminjam|pinjam uang|meminjam uang|dana pinjaman|butuh pinjaman)\b", pesan_clean))
        if is_tanya_pintas and status_fsm == "IDLE":
            prog_data = get_program_info("pintas")
            balasan = format_program_response(prog_data, sapaan=sapaan_donatur)
            nama_prog_tag = prog_data.get("nama", "PINTAS")
            balasan += (
                f"\n\nAtau untuk informasi lebih lanjut mengenai program *{nama_prog_tag}*, apakah {sapaan_donatur} ingin disambungkan ke Admin? (Balas *Ya* atau *Tidak*)"
            )
            state_manager.update_status(nomor_wa, "TANYA_PROGRAM_DETAIL", target_program="pintas")
            user_sessions[nomor_wa] = session_data
            send_message_to_waha(chat_id_asli, balasan, nama_sesi)
            return {"status": "sukses", "intent": "info_pintas"}

        # 3. Pertanyaan Katalog Generik 10 Program
        is_tanya_program = bool(re.search(
            r"(program apa saja|apa saja program|list program|daftar program|katalog program|10 program|sebutkan program)",
            pesan_clean
        )) or (pesan_clean in ["1", "1.", "program apa saja?", "program apa saja"])

        if is_tanya_program and status_fsm == "IDLE":
            state_manager.update_status(nomor_wa, "TANYA_PROGRAM")
            from services.program_manager import get_program_list
            balasan = get_program_list()
            user_sessions[nomor_wa] = session_data
            send_message_to_waha(chat_id_asli, balasan, nama_sesi)
            return {"status": "sukses", "intent": "tanya_program_prompt"}

        # Penanganan Jawaban Nomor pada State TANYA_PROGRAM
        if status_fsm == "TANYA_PROGRAM" and not has_media:
            # Pilihan 0 saat berada di daftar program -> Kembali ke Menu Utama
            if pesan_clean in ["0", "0.", "kembali ke menu utama", "menu utama"]:
                state_manager.reset_status(nomor_wa)
                balasan = ambil_balasan("sapaan", nama_pengirim=nama_pengirim)
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "sapaan"}

            PETA_INDEX_PROGRAM = {
                "1": "pintas",
                "2": "bpra_ukt",
                "3": "ota_beasiswa",
                "4": "muallaf",
                "5": "ota_palestina",
                "6": "green_qurban",
                "7": "nasi_bungkus",
                "8": "ecra",
                "9": "p2emd"
            }
            prog_key = PETA_INDEX_PROGRAM.get(pesan_clean) or pesan_clean
            prog_data = get_program_info(prog_key)

            if prog_data:
                balasan_resmi = format_program_response(prog_data, sapaan=sapaan_donatur)
                nama_prog_tag = prog_data.get("nama", "Program Rumah Amal")

                balasan_resmi += (
                    f"\n\nAtau untuk informasi lebih lanjut mengenai program *{nama_prog_tag}*, apakah {sapaan_donatur} ingin disambungkan ke Admin? (Balas *Ya* atau *Tidak*)"
                )
                state_manager.update_status(nomor_wa, "TANYA_PROGRAM_DETAIL", target_program=prog_key)

                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan_resmi, nama_sesi)
                return {"status": "sukses", "intent": "detail_program_response"}

        # Penanganan Navigasi (11, 0, QnA) pada State TANYA_PROGRAM_DETAIL
        if status_fsm == "TANYA_PROGRAM_DETAIL" and not has_media:
            session_info = state_manager.get_session(nomor_wa)
            current_prog_key = session_info.get("target_program") or "pintas"
            prog_data = get_program_info(current_prog_key)
            nama_prog_tag = (prog_data or {}).get("nama", "Program Rumah Amal")

            # 1. Navigasi 11 -> Kembali ke Daftar 10 Program
            if pesan_clean in ["11", "11.", "kembali ke program", "menu program"]:
                state_manager.update_status(nomor_wa, "TANYA_PROGRAM")
                balasan = (
                    "Berikut pilihan program penyaluran yang tersedia di Rumah Amal USK:\n\n"
                    "1. PINTAS (Pinjaman Tanpa Syarat)\n"
                    "2. BPRA-UKT\n"
                    "3. Beasiswa Orang Tua Asuh (OTA)\n"
                    "4. Beasiswa Muallaf\n"
                    "5. OTA Palestina (Orang Tua Asuh Mahasiswa Palestina)\n"
                    "6. GREEN QURBAN\n"
                    "7. Bantuan Nasi Bungkus\n"
                    "8. ECRA (Entrepreneurship Club Rumah Amal)\n"
                    "9. P2EMD\n\n"
                    "----------------------------------------\n"
                    "📌 *Pilihan Navigasi:*\n"
                    f"• Ketik angka *1 s.d. 9* untuk melihat detail program di atas\n"
                    "• Ketik *0* untuk Kembali ke Menu Utama"
                )
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "tanya_program_prompt"}

            # 2. Navigasi 0 -> Kembali ke Menu Utama Sapaan
            if pesan_clean in ["0", "0.", "kembali ke menu utama", "menu utama"]:
                state_manager.reset_status(nomor_wa)
                balasan = ambil_balasan("sapaan", nama_pengirim=nama_pengirim)
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "sapaan"}

            # 3. Konfirmasi Handoff Admin ('ya' / 'tidak')
            # Catatan: "ya"/"ok" TIDAK BOLEH dicocokkan sebagai substring polos -
            # kata "saYA" (kata ganti "aku", salah satu kata paling umum dalam
            # bahasa Indonesia) dan akhiran posesif "-nYA" (programnya, syaratnya,
            # dst) sama-sama mengandung "ya", begitu juga "ok" muncul di "tOKo"/
            # "pOKok". Kalau tetap substring, HAMPIR SEMUA kalimat bebas yang
            # dikirim di state ini akan salah dianggap konfirmasi "Ya" ke Admin.
            # Dicek sebagai kata utuh saja; frasa yang jelas beda konteks
            # ("sambungkan", "setuju") aman tetap substring.
            pesan_tokens_admin = set(pesan_clean.split())
            is_konfirmasi_ya = bool(pesan_tokens_admin & {"ya", "iya", "ok", "oke", "y"}) or any(
                k in pesan_clean for k in ["sambungkan", "setuju"]
            )
            if is_konfirmasi_ya:
                # Status "ADMIN_BARU_DIHUBUNGI" (bukan langsung IDLE) - beri
                # jendela 1 pesan untuk user membatalkan kalau langsung
                # berubah pikiran, supaya admin bisa diberi tahu susulan
                # (lihat FAST-PATH "JENDELA PEMBATALAN..." di atas).
                state_manager.update_status(nomor_wa, "ADMIN_BARU_DIHUBUNGI", target_program=nama_prog_tag)
                session_data["state"] = "IDLE"

                balasan_user = f"Baik {sapaan_donatur}, permintaan {sapaan_donatur} sedang kami teruskan ke Admin untuk penanganan lebih lanjut. Mohon ditunggu ya."
                send_whatsapp_reply(chat_id_asli, balasan_user, nama_sesi)

                nomor_hp_pemohon, nama_pemohon = _dapatkan_nomor_hp_asli(chat_id_asli, payload_waha, nama_sesi)
                pesan_peringatan = (
                    f"🆘 [{nama_prog_tag}] Ada permohonan dari:\n"
                    f"👤 *Nama:* {nama_pemohon}\n"
                    f"📞 *No. WA:* {nomor_hp_pemohon}\n"
                    f"Mohon segera di-follow up."
                )
                notify_admin(pesan_peringatan, nama_sesi)

                user_sessions[nomor_wa] = session_data
                return {"status": "sukses", "intent": "handoff_admin_success"}

            # "ga"/"gak" juga TIDAK BOLEH substring polos - "juGA" (kata "juga",
            # sangat umum), "harGA", "warGA", dst semuanya mengandung "ga".
            is_konfirmasi_tidak = any(k in pesan_clean for k in ["batal", "cancel"]) or bool(
                pesan_tokens_admin & {"tidak", "ga", "gak", "nggak", "enggak"}
            )
            if is_konfirmasi_tidak:
                state_manager.reset_status(nomor_wa)
                session_data["state"] = "IDLE"
                balasan_user = f"Baik {sapaan_donatur}, pengajuan sambung ke Admin telah dibatalkan. Ada lagi hal lain yang bisa Mimin bantu?"
                send_whatsapp_reply(chat_id_asli, balasan_user, nama_sesi)
                user_sessions[nomor_wa] = session_data
                return {"status": "sukses", "intent": "handoff_admin_cancel"}

            # 4. Jawaban Pertanyaan QnA (1 s.d N)
            qna_list = (prog_data or {}).get("qna", [])
            if pesan_clean.isdigit() and qna_list:
                idx = int(pesan_clean)
                if 1 <= idx <= len(qna_list):
                    qna_item = qna_list[idx - 1]
                    balasan = (
                        f"❓ *{qna_item['tanya']}*\n\n"
                        f"{qna_item['jawab']}\n\n"
                        f"----------------------------------------\n"
                        f"📌 *Pilihan Navigasi:*\n"
                        f"• Ketik *11* untuk Kembali ke Daftar Program\n"
                        f"• Ketik *0* untuk Kembali ke Menu Utama"
                    )
                    user_sessions[nomor_wa] = session_data
                    send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                    return {"status": "sukses", "intent": "qna_detail_response"}


        # =====================================================================
        # FAST-PATH 1A-2: DETEKSI CEK RIWAYAT TRANSAKSI DONASI
        # =====================================================================
        is_cek_riwayat = (pesan_clean in ["4", "4.", "cek riwayat", "riwayat donasi", "histori donasi", "riwayat transaksi", "cek transaksi", "donasi saya", "riwayat saya", "histori saya"]) or bool(re.search(r"(cek|lihat|tampilkan|minta|riwayat|histori|history)\s*(riwayat|histori|history|transaksi|donasi)", pesan_clean))
        if is_cek_riwayat and status_fsm == "IDLE":
            nomor_hp_pemohon, nama_pemohon = _dapatkan_nomor_hp_asli(chat_id_asli, payload_waha, nama_sesi)
            riwayat_items = state_manager.ambil_riwayat_donasi(nomor_hp_pemohon) or state_manager.ambil_riwayat_donasi(nomor_wa)
            sapaan_pemohon = deteksi_sapaan_gender(nama_pemohon or nama_pengirim)

            if riwayat_items:
                total_donasi = 0
                lines_riwayat = []
                for idx, item in enumerate(riwayat_items, 1):
                    nom = item.get("nominal") or 0
                    total_donasi += int(nom)
                    tgl_raw = item.get("waktu_transaksi") or item.get("created_at") or ""
                    tgl_fmt = tgl_raw.split("T")[0] if "T" in str(tgl_raw) else str(tgl_raw)[:10]
                    prog_code = item.get("kode_program") or "Donasi"
                    prog_name = PETA_NAMA.get(prog_code, prog_code)

                    lines_riwayat.append(
                        f"{idx}. 🗓️ *{tgl_fmt}* | Rp {nom:,}\n"
                        f"   📌 *Program:* {prog_name}\n"
                        f"   ✅ *Status:* TERVERIFIKASI"
                    )

                balasan = (
                    f"📜 *RIWAYAT TRANSAKSI DONASI*\n"
                    f"👤 *Nama:* {sapaan_pemohon} {nama_pemohon}\n"
                    f"📞 *No. WA:* {nomor_hp_pemohon}\n\n"
                    f"Berikut daftar transaksi donasi {sapaan_pemohon} yang tercatat di sistem Rumah Amal USK:\n\n"
                    + "\n\n".join(lines_riwayat) +
                    f"\n\n----------------------------------------\n"
                    f"💰 *Total Penyaluran Donasi:* Rp {total_donasi:,} ({len(riwayat_items)} Transaksi)\n\n"
                    f"Jazakallahu Khairan atas kepedulian dan kepercayaan {sapaan_pemohon} bersama Rumah Amal Masjid Jamik USK! 🙏"
                )
            else:
                balasan = (
                    f"Mohon maaf {sapaan_pemohon} {nama_pemohon}, Mimin belum menemukan riwayat transaksi donasi yang tercatat untuk nomor WhatsApp ini ({nomor_hp_pemohon}).\n\n"
                    f"Yuk tunaikan donasi/zakat pertama {sapaan_pemohon}! 🙏\n"
                    f"Ketik *2* atau *Ingin berdonasi* untuk memilih program penyaluran."
                )

            user_sessions[nomor_wa] = session_data
            send_message_to_waha(chat_id_asli, balasan, nama_sesi)
            return {"status": "sukses", "intent": "cek_riwayat_sukses"}

        # =====================================================================
        # FAST-PATH: LAPORAN "SUDAH TRANSFER" LANGSUNG DARI IDLE (BEDA DARI
        # NIAT DONASI BARU) - harus diperiksa SEBELUM is_niat_donasi di bawah,
        # karena kata "zakat"/"donasi" di dalam laporan ini bisa ikut kena
        # regex niat donasi yang lebih umum, bikin user yang SUDAH bilang
        # sudah transfer & menyebutkan kategorinya malah disuruh mengulang
        # pilih program dari awal seolah belum bilang apa-apa (ditemukan
        # lewat tes skenario "koreksi kategori donasi beruntun").
        # =====================================================================
        is_lapor_sudah_transfer = bool(re.search(
            r"(sudah transfer|udah transfer|barusan transfer|habis transfer|sudah tf|bukti tf|sudah kirim|konfirmasi transfer)",
            pesan_clean
        ))
        if is_lapor_sudah_transfer and status_fsm == "IDLE" and not has_media:
            PETA_KATEGORI_LAPOR_TRANSFER = {
                "zakat mal": "ZKT-MAL",
                "zakat maal": "ZKT-MAL",
                "zakat penghasilan": "ZKT-PENGHASILAN",
                "zakat profesi": "ZKT-PENGHASILAN",
                "infak rutin": "INF-RUTIN",
                "infak": "INF-RUTIN",
                "sedekah": "INF-RUTIN",
                "donasi": "DONASI",
            }
            kode_lapor_terdeteksi = None
            for kata, kode in PETA_KATEGORI_LAPOR_TRANSFER.items():
                if kata in pesan_clean:
                    kode_lapor_terdeteksi = kode
                    break

            if kode_lapor_terdeteksi:
                nama_lapor_terdeteksi = PETA_NAMA.get(kode_lapor_terdeteksi, kode_lapor_terdeteksi)
                state_manager.update_status(nomor_wa, "NUNGGU_BUKTI_TRANSFER", target_program=kode_lapor_terdeteksi)
                balasan = (
                    f"Baik {sapaan_donatur}, Alhamdulillah atas transfernya untuk *{nama_lapor_terdeteksi}*! 🙏\n\n"
                    f"Agar dapat kami catatkan dengan benar, mohon kirimkan foto/gambar bukti transfer (resi BSI Mobile / BYOND) ke sini ya."
                )
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "lapor_transfer_minta_resi"}
            # Kategori tidak disebutkan eksplisit - biarkan lanjut ke
            # is_niat_donasi di bawah supaya tetap ditanya mau pilih program
            # yang mana, alih-alih menebak sembarangan.

        # =====================================================================
        # FAST-PATH 1B: DETEKSI NIAT DONASI / ZAKAT (MENU UTAMA DONASI 1-4)
        # =====================================================================
        is_niat_donasi = bool(re.search(
            r"(donasi|berdonasi|sedekah|zakat|penyalurkan|penyaluran|berdonas|inginberdonasi|mauberdonasi|mauzakat|inginzakat|bayar zakat|ingin donasi|panduan berdonasi|cara berdonasi|panduan donasi)",
            pesan_clean
        )) or (pesan_clean in ["2", "2.", "ingin berdonasi", "ingin berdonasi?", "panduan berdonasi", "cara donasi", "panduan donasi"])

        if is_niat_donasi and status_fsm == "IDLE":
            state_manager.update_status(nomor_wa, "PILIH_PROGRAM")
            balasan = (
                f"Alhamdulillah, terima kasih atas niat baiknya {sapaan_donatur}! 🙏\n"
                f"Berikut beberapa pilihan program penyaluran yang tersedia di Rumah Amal USK:\n\n"
                f"1. Zakat Mal (Harta / Tabungan)\n"
                f"2. Zakat Penghasilan (Profesi)\n"
                f"3. Infak Rutin (Sedekah Bulanan)\n"
                f"4. Donasi (Bantuan Kemanusiaan)\n\n"
                f"{sapaan_donatur} ingin berdonasi/menyalurkan untuk pilihan nomor berapa (1-4)?"
            )
            user_sessions[nomor_wa] = session_data
            send_message_to_waha(chat_id_asli, balasan, nama_sesi)
            return {"status": "sukses", "intent": "pilih_program_prompt"}

        # Fast-Path Unlocking: Jika user sedang di status FSM aktif tetapi mengajukan pertanyaan baru spesifik / sapaan baru, reset status ke IDLE
        # Catatan: "batal"/"cancel" SENGAJA tidak dimasukkan ke daftar ini - keduanya
        # sudah punya penanganan khusus di FAST-PATH 2 di bawah (is_batal) yang
        # mengirim balasan konfirmasi "telah dibatalkan" yang jelas. Kalau ikut
        # direset diam-diam di sini duluan, blok is_batal itu jadi tidak pernah
        # kepakai dan user cuma dapat balasan "tidak mengerti" yang membingungkan
        # padahal sesinya sudah benar direset di belakang layar.
        KATA_KUNCI_OVERRIDE = ["pinjam", "pintas", "ukt", "bpra", "beasiswa", "alamat", "rekening", "admin", "bantuan ukt", "kurang dana", "lokasi", "jam kerja", "riwayat", "halo", "assalamualaikum", "menu utama"]
        # Token pendek/generik ("0", "p", "hi") HARUS dicocokkan persis sebagai
        # kata utuh, bukan substring - kalau tidak, nominal donasi seperti
        # "90000" ikut dianggap perintah "0" (kembali ke menu), dan kata biasa
        # seperti "meng-HI-tung"/"HI-jau" ikut ter-reset sesi diam-diam gara-gara
        # "hi" (pola bug yang sama ditemukan berulang kali hari ini - lihat
        # CATATAN_KEKURANGAN_PROYEK.txt bagian 20-22).
        KATA_KUNCI_OVERRIDE_EXACT = {"p", "0", "0.", "hi"}
        if status_fsm in {"PILIH_PROGRAM", "NUNGGU_BUKTI_TRANSFER", "NUNGGU_DATA_KONFIRMASI", "NUNGGU_DATA_INFAK", "TANYA_PROGRAM"} and not has_media:
            pesan_tokens = set(pesan_clean.split())
            if any(k in pesan_clean for k in KATA_KUNCI_OVERRIDE) or (pesan_tokens & KATA_KUNCI_OVERRIDE_EXACT):
                state_manager.reset_status(nomor_wa)
                status_fsm = "IDLE"

        is_tanya_ukt = bool(re.search(r"\b(ukt|bpra|bpra-ukt|bantuan ukt|bayar ukt|kurang dana ukt|biaya ukt)\b", pesan_clean)) or ("ukt" in pesan_clean and any(k in pesan_clean for k in ["bayar", "kurang", "dana", "bantuan", "biaya"]))
        if is_tanya_ukt and status_fsm == "IDLE":
            prog_data = get_program_info("bpra_ukt")
            balasan = (
                f"*{prog_data['nama']}*\n\n"
                f"{prog_data['deskripsi']}\n\n"
                f"*Syarat & Ketentuan:*\n"
                + "\n".join(f"{i}. {s}" for i, s in enumerate(prog_data['syarat'], 1)) +
                f"\n\n🌐 *Website Resmi:* https://rumahamal.usk.ac.id\n\n"
                f"----------------------------------------\n"
                f"📌 *Pilihan Navigasi:*\n"
                f"• Ketik *1* atau *Admin* jika {sapaan_donatur} ingin berkonsultasi / mengajukan permohonan UKT ke Admin\n"
                f"• Ketik *11* untuk Kembali ke Daftar Program\n"
                f"• Ketik *0* untuk Kembali ke Menu Utama"
            )
            state_manager.update_status(nomor_wa, "TANYA_PROGRAM_DETAIL", target_program="bpra_ukt")
            user_sessions[nomor_wa] = session_data
            send_message_to_waha(chat_id_asli, balasan, nama_sesi)
            return {"status": "sukses", "intent": "info_bpra_ukt"}

        is_tanya_pintas = bool(re.search(r"\b(pintas|pinjam|pinjaman|meminjam|pinjam uang|meminjam uang|dana pinjaman|butuh pinjaman)\b", pesan_clean))
        if is_tanya_pintas and status_fsm == "IDLE":
            prog_data = get_program_info("pintas")
            balasan = format_program_response(prog_data, sapaan=sapaan_donatur)
            nama_prog_tag = prog_data.get("nama", "PINTAS")
            balasan += (
                f"\n\nAtau untuk informasi lebih lanjut mengenai program *{nama_prog_tag}*, apakah {sapaan_donatur} ingin disambungkan ke Admin? (Balas *Ya* atau *Tidak*)"
            )
            state_manager.update_status(nomor_wa, "TANYA_PROGRAM_DETAIL", target_program="pintas")
            user_sessions[nomor_wa] = session_data
            send_message_to_waha(chat_id_asli, balasan, nama_sesi)
            return {"status": "sukses", "intent": "info_pintas"}

        # =====================================================================
        # FAST-PATH 1C: DETEKSI PILIHAN 3 (ALAMAT) ATAU 4 (ADMIN) PADA IDLE
        # =====================================================================
        is_tanya_alamat = (pesan_clean in ["3", "3.", "alamat kantor", "alamat kantor?"]) or bool(re.search(r"(alamat|lokasi|posisi|letaknya|dimana|di mana|sebelah mana|wilayah|tempat|peta|gmaps|google maps)", pesan_clean))
        if is_tanya_alamat and status_fsm == "IDLE":
            balasan = (
                "Kantor operasional Rumah Amal USK terletak di Lantai 1 Masjid Jamik Universitas Syiah Kuala, "
                "Jalan T. Nyak Arief Kompleks Pelajar Mahasiswa (Kopelma) Darussalam, Kecamatan Syiah Kuala, Kota Banda Aceh."
            )
            user_sessions[nomor_wa] = session_data
            send_message_to_waha(chat_id_asli, balasan, nama_sesi)
            return {"status": "sukses", "intent": "info_alamat"}

        is_tanya_beasiswa = (pesan_clean in ["info beasiswa", "beasiswa", "daftar beasiswa", "beasiswa apa saja"]) or bool(re.search(r"(beasiswa|bantuan ukt|bantuan kuliah)", pesan_clean))
        if is_tanya_beasiswa and status_fsm == "IDLE":
            # Set status FSM khusus (TANYA_BEASISWA) supaya angka 1-4 yang
            # diketik setelah ini ditafsirkan sesuai daftar beasiswa di bawah,
            # BUKAN kebablasan dicocokkan ke shortcut menu utama global
            # (mis. "2" = Ingin berdonasi) - itu bug lama yang bikin user
            # nyasar ke alur lain tanpa sadar.
            state_manager.update_status(nomor_wa, "TANYA_BEASISWA")
            balasan = (
                "Berikut program beasiswa resmi yang tersedia di Rumah Amal USK:\n\n"
                "1. BPRA-UKT (Bantuan Biaya UKT Mahasiswa)\n"
                "2. OTA PALESTINA (Beasiswa & Biaya Hidup Mahasiswa Palestina)\n"
                "3. BEASISWA ORANG TUA ASUH (OTA) (Mahasiswa Dhuafa Berprestasi)\n"
                "4. BEASISWA MUALLAF (Khusus Mahasiswa/Masyarakat Muallaf)\n\n"
                "----------------------------------------\n"
                "📌 *Pilihan Navigasi:*\n"
                f"• Ketik angka *1 s.d. 4* untuk melihat detail program di atas\n"
                f"• Ketik *Program apa saja* untuk melihat katalog 9 program lengkap\n"
                "• Ketik *0* untuk Kembali ke Menu Utama"
            )
            user_sessions[nomor_wa] = session_data
            send_message_to_waha(chat_id_asli, balasan, nama_sesi)
            return {"status": "sukses", "intent": "info_beasiswa"}

        # Penanganan Pilihan 1-4 pada State TANYA_BEASISWA (menu beasiswa
        # spesifik di atas - PUNYA NOMOR SENDIRI, beda dari katalog 9
        # program utama, jadi butuh status FSM & pemetaan angka terpisah).
        if status_fsm == "TANYA_BEASISWA" and not has_media:
            if pesan_clean in ["0", "0.", "kembali ke menu utama", "menu utama"]:
                state_manager.reset_status(nomor_wa)
                balasan = ambil_balasan("sapaan", nama_pengirim=nama_pengirim)
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "sapaan"}

            if pesan_clean in ["1", "1.", "program apa saja", "program apa saja?", "katalog"]:
                state_manager.update_status(nomor_wa, "TANYA_PROGRAM")
                from services.program_manager import get_program_list
                balasan = get_program_list()
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "tanya_program_prompt"}

            PETA_INDEX_BEASISWA = {
                "1": "bpra_ukt",
                "2": "ota_palestina",
                "3": "ota_beasiswa",
                "4": "muallaf",
            }
            beasiswa_key = PETA_INDEX_BEASISWA.get(pesan_clean)
            if beasiswa_key:
                prog_data = get_program_info(beasiswa_key)
                if prog_data:
                    balasan_resmi = format_program_response(prog_data, sapaan=sapaan_donatur)
                    nama_prog_tag = prog_data.get("nama", "Program Rumah Amal")
                    balasan_resmi += (
                        f"\n\nAtau untuk informasi lebih lanjut mengenai program *{nama_prog_tag}*, apakah {sapaan_donatur} ingin disambungkan ke Admin? (Balas *Ya* atau *Tidak*)"
                    )
                    state_manager.update_status(nomor_wa, "TANYA_PROGRAM_DETAIL", target_program=beasiswa_key)
                    user_sessions[nomor_wa] = session_data
                    send_message_to_waha(chat_id_asli, balasan_resmi, nama_sesi)
                    return {"status": "sukses", "intent": "detail_program_response"}

        is_tanya_jam_kerja = (pesan_clean in ["jam kerja", "jam operasional", "buka jam berapa"]) or bool(re.search(r"(jam kerja|jam operasional|buka jam berapa|tutup jam berapa|buka hari apa|jadwal buka)", pesan_clean))
        if is_tanya_jam_kerja and status_fsm == "IDLE":
            balasan = (
                "Kantor operasional Rumah Amal USK buka setiap hari Senin - Jumat pukul 08.00 - 16.30 WIB (tutup pada hari Sabtu, Minggu, dan Libur Nasional)."
            )
            user_sessions[nomor_wa] = session_data
            send_message_to_waha(chat_id_asli, balasan, nama_sesi)
            return {"status": "sukses", "intent": "info_jam_kerja"}

        is_tanya_rekening = (pesan_clean in ["rekening bsi", "norek", "no rek", "info rekening", "nomor rekening"]) or bool(re.search(r"(rekening|norek|no rek|transfer bsi|bayar lewat apa)", pesan_clean))
        if is_tanya_rekening and status_fsm == "IDLE":
            balasan = (
                "Berikut rekening resmi penyaluran donasi dan zakat Rumah Amal USK:\n\n"
                f"{BANK_REKENING_INFO}"
            )
            user_sessions[nomor_wa] = session_data
            send_message_to_waha(chat_id_asli, balasan, nama_sesi)
            return {"status": "sukses", "intent": "info_rekening"}

        is_hubungi_admin = (pesan_clean in ["5", "5.", "hubungi admin", "hubungi admin?", "admin", "kontak admin"])
        if is_hubungi_admin and status_fsm == "IDLE":
            state_manager.update_status(nomor_wa, "MENUNGGU_ADMIN", target_program="ADMIN")
            balasan = f"Apakah {sapaan_donatur} ingin disambungkan ke Admin Rumah Amal USK sekarang? (Balas *Ya* atau *Tidak*)"
            user_sessions[nomor_wa] = session_data
            send_message_to_waha(chat_id_asli, balasan, nama_sesi)
            return {"status": "sukses", "intent": "handoff_admin_prompt"}

        # =====================================================================
        # FAST-PATH 2: PENANGANAN KATA SAPAAN / PEMBATALAN PADA STATE AKTIF
        # =====================================================================
        if status_fsm in {"PILIH_PROGRAM", "NUNGGU_BUKTI_TRANSFER", "NUNGGU_DATA_KONFIRMASI", "NUNGGU_DATA_INFAK", "TANYA_PROGRAM"} and not has_media:
            # 1. Pengecekan Kata Pembatalan
            is_batal = any(k in pesan_clean for k in ["batal", "cancel", "batalin", "tidak jadi", "ga jadi", "gak jadi"])
            if is_batal:
                state_manager.reset_status(nomor_wa)
                balasan = f"Baik {sapaan_donatur}, proses penyaluran telah dibatalkan. Ada lagi hal lain yang bisa Mimin bantu? (Misal info beasiswa, alamat, atau jam kerja)."
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "batal_sesi"}

            # 2. Pengecekan Kata Lanjut
            is_lanjut = any(k in pesan_clean for k in ["lanjut", "rekening", "transfer"])
            if is_lanjut:
                session_info = state_manager.get_session(nomor_wa)
                target_prog_session = session_info.get("target_program") or "INF-RUTIN"
                nama_target = PETA_NAMA.get(target_prog_session, "Infak Rutin")

                state_manager.update_status(nomor_wa, "NUNGGU_BUKTI_TRANSFER", target_program=target_prog_session)
                balasan = (
                    f"Baik {sapaan_donatur}, untuk penyaluran *{nama_target}* silakan melakukan transfer ke rekening resmi kami:\n\n"
                    f"{BANK_REKENING_INFO}\n\n"
                    f"Setelah melakukan transfer, silakan kirimkan foto/gambar bukti transfer (resi BSI Mobile / BYOND) ke sini ya {sapaan_donatur} agar dapat kami proses dan catatkan. Terima kasih! 🙏"
                )
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "lanjut_sesi"}

            # 3. Pengecekan Kata Sapaan
            # Catatan: "p" dan "hi" TIDAK BOLEH dicocokkan sebagai substring
            # polos - huruf "p" muncul di hampir semua kalimat bahasa Indonesia
            # ("program", "penyaluran", "pilihan", dst), begitu juga "hi" di
            # "hitung"/"hijau". Dicek sebagai kata utuh saja; frasa/kata sapaan
            # yang lebih panjang aman tetap substring.
            pesan_tokens_sapaan = set(pesan_clean.split())
            is_sapaan_di_state_aktif = (
                bool(pesan_tokens_sapaan & {"p", "hi"})
                or any(s in pesan_clean for s in ["halo", "assalamualaikum", "selamat", "pagi", "siang", "sore", "malam", "ping", "hai"])
            )
            if is_sapaan_di_state_aktif and status_fsm != "PILIH_PROGRAM":
                session_info = state_manager.get_session(nomor_wa)
                target_prog_session = session_info.get("target_program") or "Infak / Zakat"
                nama_prog = PETA_NAMA.get(target_prog_session, target_prog_session)

                balasan = (
                    f"Halo {_sapaan_dengan_nama(sapaan_donatur, nama_pengirim)}! 🙏\n"
                    f"Mimin mencatat sebelumnya {sapaan_donatur} sedang berada dalam proses penyaluran *{nama_prog}*.\n\n"
                    f"Apakah {sapaan_donatur} ingin melampirkan bukti transfernya sekarang, atau ingin membatalkan dan menanyakan hal lain?\n\n"
                    f"Ketik:\n"
                    f"- *1* atau *Lanjut* (untuk melihat rekening BSI & kirim resi)\n"
                    f"- *2* atau *Batal* (untuk membatalkan dan kembali ke menu awal)"
                )
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "ingatkan_sesi"}

        # =====================================================================
        # FAST-PATH 3: STATE PILIH_PROGRAM (MEMILIH MENU DONASI 1-4 ATAU TEKS)
        # =====================================================================
        # "and not has_media" WAJIB ADA - kalau tidak, resi/foto yang dikirim
        # SAAT status sedang menunggu pilihan menu (mis. gara-gara sebelumnya
        # tidak sengaja masuk PILIH_PROGRAM) ikut ditangkap logika pencocokan
        # menu 1-4 di bawah ini (yang cuma cek teks), gagal cocok karena foto
        # tidak ada teksnya, dan berakhir cuma dibalas "belum menangkap
        # pilihannya" - RESI-NYA SENDIRI TIDAK PERNAH SAMPAI ke logika baca
        # resi/simpan transaksi di FAST-PATH 4, hilang tanpa jejak (ditemukan
        # 30 Agustus). Dengan guard ini, media SELALU diteruskan ke FAST-PATH
        # 4 yang memang dirancang menangani resi apa pun status FSM-nya.
        if status_fsm == "PILIH_PROGRAM" and not has_media:
            PETA_PILIHAN = {
                "1": ("ZKT-MAL", "Zakat Mal"),
                "zakat mal": ("ZKT-MAL", "Zakat Mal"),
                "mal": ("ZKT-MAL", "Zakat Mal"),
                "2": ("ZKT-PENGHASILAN", "Zakat Penghasilan"),
                "zakat penghasilan": ("ZKT-PENGHASILAN", "Zakat Penghasilan"),
                "penghasilan": ("ZKT-PENGHASILAN", "Zakat Penghasilan"),
                "profesi": ("ZKT-PENGHASILAN", "Zakat Penghasilan"),
                "3": ("INF-RUTIN", "Infak Rutin"),
                "infak rutin": ("INF-RUTIN", "Infak Rutin"),
                "infak": ("INF-RUTIN", "Infak Rutin"),
                "sedekah": ("INF-RUTIN", "Infak Rutin"),
                "4": ("DONASI", "Donasi (Bantuan Kemanusiaan)"),
                "donasi": ("DONASI", "Donasi (Bantuan Kemanusiaan)"),
                "bantuan": ("DONASI", "Donasi (Bantuan Kemanusiaan)")
            }

            kode_target, nama_target = None, None
            if pesan_clean in PETA_PILIHAN:
                kode_target, nama_target = PETA_PILIHAN[pesan_clean]
            elif len(pesan_clean.split()) <= 5:
                # Pencocokan longgar HANYA untuk balasan pendek/langsung (mis.
                # "saya mau infak", "yang zakat mal"). Kalimat panjang seperti
                # curhat/pertanyaan lain ("loh kok gak paham saya mau donasi") sering
                # kebetulan menyebut kata "donasi"/"infak" tanpa bermaksud MEMILIH
                # opsi itu - kalau tetap dicocokkan, itu salah tangkap sebagai
                # pilihan sah dan langsung minta transfer untuk program yang tidak
                # pernah benar-benar dipilih user.
                # Key SATU KATA ("mal","donasi","infak",dst) dicocokkan sebagai
                # kata utuh, bukan substring - "mal" sebagai substring polos akan
                # ikut kena kata "norMAL"/"forMAL" yang sama sekali tidak
                # berhubungan. Key multi-kata ("zakat mal") aman tetap substring.
                pesan_tokens_pilihan = set(pesan_clean.split())
                for k, (kode, nama_p) in PETA_PILIHAN.items():
                    cocok = (k in pesan_tokens_pilihan) if " " not in k else (k in pesan_clean)
                    if cocok:
                        kode_target, nama_target = kode, nama_p
                        break

            # Input tidak cocok pilihan manapun - tanya ulang menu 1-4, JANGAN
            # diam-diam anggap "Infak Rutin" (dulu jadi default bisu di sini,
            # bikin user yang sebenarnya bertanya hal lain malah diminta
            # transfer untuk program yang tidak pernah mereka pilih).
            if not kode_target:
                balasan = (
                    f"Mohon maaf {sapaan_donatur}, Mimin belum menangkap pilihannya. Berikut lagi pilihan penyaluran yang tersedia:\n\n"
                    f"1. Zakat Mal (Harta / Tabungan)\n"
                    f"2. Zakat Penghasilan (Profesi)\n"
                    f"3. Infak Rutin (Sedekah Bulanan)\n"
                    f"4. Donasi (Bantuan Kemanusiaan)\n\n"
                    f"{sapaan_donatur} ingin berdonasi/menyalurkan untuk pilihan nomor berapa (1-4)?"
                )
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "pilih_program_reprompt"}

            state_manager.update_status(nomor_wa, "NUNGGU_BUKTI_TRANSFER", target_program=kode_target)
            balasan = (
                f"Baik {sapaan_donatur}, untuk penyaluran *{nama_target}* silakan melakukan transfer ke rekening resmi kami:\n\n"
                f"{BANK_REKENING_INFO}\n\n"
                f"Setelah melakukan transfer, silakan kirimkan foto/gambar bukti transfer (resi BSI Mobile / BYOND) ke sini ya {sapaan_donatur} agar dapat kami proses dan catatkan. Terima kasih! 🙏"
            )
            user_sessions[nomor_wa] = session_data
            send_message_to_waha(chat_id_asli, balasan, nama_sesi)
            return {"status": "sukses", "intent": "pilih_program_selesai"}

        # =====================================================================
        # FAST-PATH 4: STATE NUNGGU_BUKTI_TRANSFER / KONFIRMASI / MEDIA RESI
        # (LOCAL PYTHON REGEX FIRST - 0.001s ANTI TIMEOUT)
        # =====================================================================
        # has_media SENDIRIAN (tanpa syarat status FSM tertentu) sengaja
        # dimasukkan di sini - sebelumnya kombinasi "kirim gambar" + status
        # IDLE (donatur langsung kirim resi tanpa basa-basi dulu, mis. yang
        # diarahkan dari web) malah lolos ke jalur balasan generik yang tidak
        # pernah memanggil Vision AI ataupun menyimpan transaksi sama sekali -
        # donasinya diam-diam tidak pernah tercatat walau bot menjawab seolah
        # normal. Sekarang SETIAP pesan berisi gambar diproses lewat jalur
        # baca-resi asli ini, apa pun status FSM-nya.
        if status_fsm == "NUNGGU_BUKTI_TRANSFER" or status_fsm == "NUNGGU_DATA_KONFIRMASI" or has_media:
            session_info = state_manager.get_session(nomor_wa)
            target_prog_session = session_info.get("target_program") or "INF-RUTIN"

            # 1. Coba ekstraksi lokal dengan Regex Python terlebih dahulu (0.001 detik)
            nama_local = None
            nominal_local = None

            # Cek angka nominal di pesan teks
            match_nom = re.search(r"(?:Rp|Jumlah|Nominal|sebesar|sejumlah)[^\d]*([\d\.\,]{4,})", pesan_clean, re.IGNORECASE)
            if not match_nom:
                match_nom = re.search(r"\b(\d{4,10})\b", pesan_clean)
            if match_nom:
                digits = re.sub(r"[^\d]", "", match_nom.group(1))
                if digits and int(digits) >= 1000:
                    nominal_local = digits

            # Cek nama pengirim jika disebutkan dalam teks
            match_nama = re.search(r"(?:nama|donatur|atas nama)[^\n:]*[:\n\s]+([A-Za-z\s]{3,30})", pesan, re.IGNORECASE)
            if match_nama:
                nama_local = match_nama.group(1).strip()

            # Jika media ada atau regex lokal kurang lengkap, panggil fungsi Vision/NER
            if has_media or image_bytes is not None:
                data_diekstrak = ekstrak_resi_vision(image_bytes, caption=pesan)
            else:
                data_diekstrak = ekstrak_konfirmasi_donasi(pesan)

            nama = data_diekstrak.get("nama") or nama_local or nama_pengirim
            nominal = _nominal_valid(data_diekstrak.get("nominal")) or nominal_local

            # Program "diketahui" HANYA kalau user benar-benar memilihnya
            # lewat percakapan (mis. sempat pilih menu 1-4) - keputusan user
            # 29 Agustus: catatan yang terbaca OCR dari struk resi itu sendiri
            # SENGAJA TIDAK dihitung sebagai "diketahui" lagi, walau jelas
            # tertulis di sana. Alasannya: admin dashboard memang dibuat
            # khusus untuk memvalidasi resi yang belum dipastikan sumbernya -
            # kalau OCR struk saja cukup untuk auto-validasi, resi apapun
            # (termasuk yang di-manipulasi/salah kirim) dengan catatan yang
            # "kebetulan" terbaca akan langsung tercatat sebagai donasi resmi
            # tanpa pernah dicek manusia, berapa pun nominalnya.
            program_terdeteksi = data_diekstrak.get("program")
            program_dari_ekstraksi = bool(program_terdeteksi) and program_terdeteksi != "UMUM"
            program_dari_sesi = bool(session_info.get("target_program"))
            program_diketahui = program_dari_sesi

            # program_kode (kategori yang DISIMPAN) tetap boleh memakai dugaan
            # OCR sebagai pra-isian yang masuk akal buat admin di dashboard -
            # yang berubah cuma STATUSNYA (selalu "pending" tanpa program_dari_sesi),
            # bukan tebakan kategorinya.
            if program_dari_sesi:
                program_kode = target_prog_session
            elif program_dari_ekstraksi:
                program_kode = program_terdeteksi
            else:
                program_kode = "INF-RUTIN"

            if nominal:
                nomor_hp_real, _ = _dapatkan_nomor_hp_asli(chat_id_asli, payload_waha, nama_sesi)
                # Kalau programnya cuma tebakan (bukan benar-benar disebut user),
                # JANGAN langsung dianggap tervalidasi - status "pending" supaya
                # admin yang menentukan jenis zakat/programnya yang benar lewat
                # foto resi yang sudah tersimpan, baru divalidasi di dashboard.
                status_verifikasi = "validated" if program_diketahui else "pending"
                state_manager.simpan_transaksi_final(
                    nomor_hp_real, nama, nominal, kode_program=program_kode,
                    resi_bytes=image_bytes if (has_media or image_bytes is not None) else None,
                    status_verifikasi=status_verifikasi,
                )
                state_manager.reset_status(nomor_wa)

                if not program_diketahui:
                    try:
                        nama_kategori_dugaan = PETA_NAMA.get(program_kode, program_kode)
                        keterangan_dugaan = (
                            f"terbaca *{nama_kategori_dugaan}* dari catatan di struk resinya"
                            if program_dari_ekstraksi
                            else "tidak ada keterangan apapun (sistem sementara menduga Infak Rutin)"
                        )
                        notify_admin(
                            f"📄 [RESI PERLU DIVALIDASI] {nama} ({nomor_hp_real}) mengirim bukti transfer "
                            f"Rp {int(nominal):,} tanpa pernah menyebut peruntukannya lewat chat - {keterangan_dugaan}. "
                            f"Berstatus *Menunggu* - mohon cek foto resinya di Admin Dashboard > Data Transaksi "
                            f"dan konfirmasi/koreksi jenis zakat/programnya sebelum divalidasi.",
                            nama_sesi,
                        )
                    except Exception as e:
                        print(f"[Warning Notify Admin Resi Tanpa Program] {e}")

                sapaan_donatur = deteksi_sapaan_gender(nama)
                nominal_fmt = f"{int(nominal):,}"
                balasan = _dapatkan_doa_spesifik(
                    program_kode, nama_donatur=_sapaan_dengan_nama(sapaan_donatur, nama), nominal_fmt=nominal_fmt,
                    program_diketahui=program_diketahui,
                )
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "konfirmasi_sukses"}
            else:
                state_manager.update_status(nomor_wa, "NUNGGU_BUKTI_TRANSFER", target_program=target_prog_session)
                sapaan_donatur = deteksi_sapaan_gender(nama_pengirim)
                if has_media:
                    balasan = f"Mohon maaf, gambar resi kurang terbaca. Boleh {sapaan_donatur} ketikkan secara manual Nama dan Nominalnya?"
                else:
                    balasan = f"Mohon maaf {_sapaan_dengan_nama(sapaan_donatur, nama_pengirim)}, Mimin kurang menangkap nominal transfernya. Boleh diulangi dengan menyebutkan *Nama Lengkap*, *Nominal Transfer*, dan *Program Donasinya*? Atau {sapaan_donatur} bisa langsung melampirkan foto resi transfer BSI Mobile / BYOND ke sini."

                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "konfirmasi_retry"}

        # =====================================================================
        # FAST-PATH 5: STATE NUNGGU_DATA_INFAK FORMULIR
        # =====================================================================
        if status_fsm == "NUNGGU_DATA_INFAK" or "FORMULIR INFAK RUTIN" in (pesan or "").upper():
            if "FORMULIR INFAK RUTIN" in (pesan or "").upper():
                data_diekstrak = ekstrak_formulir(pesan)
            else:
                data_diekstrak = ekstrak_data_ner(pesan)

            nama = data_diekstrak.get("nama")
            nominal = _nominal_valid(data_diekstrak.get("nominal"))

            if nama and nominal:
                nomor_hp_real, _ = _dapatkan_nomor_hp_asli(chat_id_asli, payload_waha, nama_sesi)
                # "pending" (BUKAN default "validated") - keputusan yang sama
                # seperti resi via foto (bagian 24, CATATAN_KEKURANGAN_PROYEK.txt):
                # kalimat "FORMULIR INFAK RUTIN" + nama + nominal dalam SATU
                # pesan dingin (tanpa pernah melalui menu pilih program) bukan
                # konfirmasi terverifikasi - admin yang menentukan lewat dashboard.
                state_manager.simpan_transaksi_final(
                    nomor_hp_real, nama, nominal, kode_program="INF-RUTIN", status_verifikasi="pending",
                )
                state_manager.reset_status(nomor_wa)

                try:
                    notify_admin(
                        f"📄 [FORMULIR PERLU DIVALIDASI] {nama} ({nomor_hp_real}) mengisi formulir Infak Rutin "
                        f"(Rp{nominal}) lewat chat tanpa melalui menu pilih program. Berstatus *Menunggu* - "
                        f"mohon cek di Admin Dashboard > Data Transaksi sebelum divalidasi.",
                        nama_sesi,
                    )
                except Exception as e:
                    print(f"[Warning Notify Admin Formulir] {e}")

                sapaan_donatur = deteksi_sapaan_gender(nama)
                balasan = f"MasyaAllah, atas nama {_sapaan_dengan_nama(sapaan_donatur, nama)} untuk nominal Rp{nominal} sudah kami terima dan akan segera diperiksa admin. Semoga berkah."
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "one_shot_ner_infak"}
            else:
                sapaan_donatur = deteksi_sapaan_gender(nama_pengirim)
                balasan = f"Maaf {sapaan_donatur}, Mimin kurang menangkap datanya. Boleh diulangi dengan menyebutkan Nama dan Nominalnya?"
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "one_shot_ner_retry"}

        # =====================================================================
        # FAST-PATH: STATE MENUNGGU_ADMIN (PENANGANAN KONFIRMASI 'YA' / 'BATAL')
        # =====================================================================
        # "and not has_media" - pola bug yang sama seperti PILIH_PROGRAM di atas
        # (ditemukan 30 Agustus): tanpa ini, resi yang dikirim saat status
        # sedang menunggu jawaban Ya/Tidak akan hilang tanpa jejak (cuma
        # dibalas "mohon balasi dengan Ya/Batal"), bukan diteruskan ke
        # FAST-PATH 4 yang memang menangani resi apa pun status FSM-nya.
        if status_fsm == "MENUNGGU_ADMIN" and not has_media:
            pesan_normal = (pesan or "").strip().lower()
            # Catatan: "ya"/"ok" TIDAK BOLEH substring polos - lihat penjelasan
            # di blok konfirmasi handoff admin lainnya di atas ("saYA", "-nYA",
            # "tOKo" semuanya mengandung "ya"/"ok"). Dicek sebagai kata utuh.
            pesan_tokens_menunggu = set(pesan_normal.split())
            if bool(pesan_tokens_menunggu & {"ya", "iya", "ok", "oke", "y"}) or any(
                k in pesan_normal for k in ["sambungkan", "setuju", "boleh", "lanjut"]
            ):
                session_info = state_manager.get_session(nomor_wa)
                nama_prog_admin = session_info.get("target_program") or "PINTAS"
                # Status "ADMIN_BARU_DIHUBUNGI" (bukan langsung IDLE) - beri
                # jendela 1 pesan untuk user membatalkan kalau langsung
                # berubah pikiran, supaya admin bisa diberi tahu susulan.
                state_manager.update_status(nomor_wa, "ADMIN_BARU_DIHUBUNGI", target_program=nama_prog_admin)
                session_data["state"] = "IDLE"

                # 1. Beri tahu user
                balasan_user = f"Baik {sapaan_donatur}, permintaan {sapaan_donatur} sedang kami teruskan ke Admin untuk penanganan lebih lanjut. Mohon ditunggu ya."
                send_whatsapp_reply(chat_id_asli, balasan_user, nama_sesi)

                # 2. Kirim notifikasi (ping) ke Admin dengan Nomor HP Asli & Nama Pemohon
                nomor_hp_pemohon, nama_pemohon = _dapatkan_nomor_hp_asli(chat_id_asli, payload_waha, nama_sesi)
                pesan_peringatan = (
                    f"🆘 [{nama_prog_admin}] Ada permohonan dari:\n"
                    f"👤 *Nama:* {nama_pemohon}\n"
                    f"📞 *No. WA:* {nomor_hp_pemohon}\n"
                    f"Mohon segera di-follow up."
                )
                notify_admin(pesan_peringatan, nama_sesi)

                user_sessions[nomor_wa] = session_data
                return {"status": "sukses", "intent": "handoff_admin_success"}

            elif any(k in pesan_normal for k in ["batal", "cancel"]) or bool(
                pesan_tokens_menunggu & {"tidak", "ga", "gak", "nggak", "enggak"}
            ):
                state_manager.reset_status(nomor_wa)
                session_data["state"] = "IDLE"
                balasan_user = f"Baik {sapaan_donatur}, pengajuan sambung ke Admin telah dibatalkan. Ada lagi hal lain yang bisa Mimin bantu?"
                send_whatsapp_reply(chat_id_asli, balasan_user, nama_sesi)
                user_sessions[nomor_wa] = session_data
                return {"status": "sukses", "intent": "handoff_admin_cancel"}

            else:
                balasan_user = "Mohon balasi dengan *Ya* (jika ingin disambungkan ke Admin) atau *Batal* (jika ingin membatalkan)."
                send_whatsapp_reply(chat_id_asli, balasan_user, nama_sesi)
                user_sessions[nomor_wa] = session_data
                return {"status": "sukses", "intent": "handoff_admin_waiting"}

        # =====================================================================
        # TAHAP 6: ALUR HIBRIDA BIASA (Q&A STATELESS - NER TIDAK DIPANGGIL DI SINI!)
        # =====================================================================
        hasil = susun_balasan(
            pesan,
            has_media=has_media,
            context={
                "last_program_key": session_data.get("last_program_key"),
                "last_intents": session_data.get("last_intents", []),
            },
            nama_pengirim=nama_pengirim,
        )
        intent = " | ".join(hasil["intents"])
        fakta_script = hasil["reply"]

        if intent == "sapaan" and "{nama_pengirim}" in fakta_script:
            fakta_script = fakta_script.format(nama_pengirim=nama_pengirim)

        session_data["last_program_key"] = hasil.get("last_program_key")
        session_data["last_intents"] = hasil.get("intents", [])

        if hasil.get("should_wait_admin"):
            session_data["state"] = "MENUNGGU_ADMIN"
        else:
            session_data["state"] = "IDLE"

        # fakta_script sudah ditulis natural (lihat QA_SCRIPT di admin_scripts.py),
        # jadi dikirim langsung tanpa diparafrase ulang oleh LLM - Gemini di alur
        # ini hanya dipakai untuk deteksi intent (get_intent, di klasifikasi_pesan),
        # bukan untuk menyusun kalimat balasan. Ini memangkas separuh lebih
        # panggilan Gemini per pertanyaan (dari 2x jadi maks. 1x) tanpa mengubah
        # kualitas jawaban, karena teks statisnya memang sudah natural.
        balasan = fakta_script

        user_sessions[nomor_wa] = session_data

        print(f"[Balasan Akhir Dikirim]\n{balasan}")
        send_message_to_waha(chat_id_asli, balasan, nama_sesi)

        return {"status": "sukses", "intent": intent}

    except Exception as e:
        print(f"[Error Webhook] {e}")
        return {"status": "error", "detail": str(e)}