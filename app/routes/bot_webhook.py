from fastapi import APIRouter, Request
import requests
import os
import re

from admin_scripts import ambil_balasan, susun_balasan
from services.llm_agent import (
    panggil_llm_teks,
    verifikasi_halusinasi,
    ekstrak_data_ner,
    ekstrak_konfirmasi_donasi,
    ekstrak_resi_vision,
    get_intent,
)
from services import state_manager
from services.form_parser import ekstrak_formulir
from services.program_manager import get_program_info, format_program_response
from services.gender_detector import deteksi_sapaan_gender
from services.logger import logger

router = APIRouter()
WAHA_ENDPOINT = os.getenv("WAHA_ENDPOINT", "http://waha-gateway:3000").rstrip("/")
WAHA_SEND_URL = f"{WAHA_ENDPOINT}/api/sendText"
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "amalmaximal123")
user_sessions = {}


def _get_active_waha_session() -> str:
    """Mengambil nama sesi WAHA yang sedang aktif (WORKING)."""
    try:
        res = requests.get(f"{WAHA_ENDPOINT}/api/sessions", headers={"X-Api-Key": WAHA_API_KEY}, timeout=2)
        if res.status_code == 200:
            sessions = res.json()
            for s in sessions:
                if s.get("status") == "WORKING":
                    return s.get("name", "default")
    except Exception as e:
        print(f"[Warning WAHA Sessions Fetch] {e}")
    return "default"


def _resolve_waha_chat_id(chat_id: str, session_name: str) -> str:
    """Menerjemahkan nomor HP / chatId (misal 6281269666776) ke chatId/LID resmi dari WhatsApp WAHA."""
    if not chat_id:
        return chat_id
    if "@lid" in chat_id:
        return chat_id

    digits = re.sub(r"[^\d]", "", chat_id)
    if digits:
        try:
            url = f"http://waha-gateway:3000/api/contacts/check-exists?phone={digits}&session={session_name}"
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

    # Fallback jika nomor adalah LID Admin
    admin_wa = os.getenv("ADMIN_WA_NUMBER", "6281269666776@c.us")
    admin_digits = re.sub(r"[^\d]", "", admin_wa)
    if clean_id == admin_digits:
        formatted_phone = f"0{admin_digits[2:]}" if admin_digits.startswith("62") else admin_digits
        nama = (payload_waha or {}).get("pushname") or "Admin"
        return (formatted_phone, nama)

    return (clean_id, (payload_waha or {}).get("pushname") or "Donatur")



def send_message_to_waha(chat_id: str, text: str, session_name: str = "default"):
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


ADMIN_WA_NUMBER = os.getenv("ADMIN_WA_NUMBER", "6281269666776@c.us")


def notify_admin(pesan_peringatan: str, session_name: str = "default"):
    """Mengirim pesan notifikasi (ping) ke nomor WhatsApp Admin."""
    send_message_to_waha(ADMIN_WA_NUMBER, pesan_peringatan, session_name)



def _dapatkan_doa_spesifik(program_code: str) -> str:
    """Mengambil template doa spesifik dari admin_scripts sesuai jenis program."""
    code_up = (program_code or "").upper()
    if "ZKT-PENGHASILAN" in code_up:
        return ambil_balasan("doa_zakat_penghasilan")
    elif "ZKT" in code_up or "ZAKAT" in code_up:
        return ambil_balasan("doa_zakat_mal")
    return ambil_balasan("doa_infak")


PROCESSED_MSG_IDS = set()


@router.post("/webhook")
async def waha_webhook(request: Request):
    try:
        data = await request.json()
        event_name = data.get("event", "")
        payload_waha = data.get("payload", {})
        chat_id_asli = payload_waha.get("from", "")
        nama_sesi = data.get("session", "default")

        # KASUS 2: Filter event Panggilan Suara / Video (call)
        if "call" in event_name or payload_waha.get("type") in ["call", "call_log", "voice_call"]:
            send_whatsapp_reply(
                chat_id_asli,
                "Mohon maaf, bot Rumah Amal USK tidak dapat menerima panggilan suara/video. Silakan kirimkan pertanyaan atau permohonan Anda melalui pesan teks WhatsApp. Terima kasih! 🙏",
                nama_sesi
            )
            return {"status": "sukses", "intent": "panggilan_suara_diabaikan"}

        # Filter event type WAHA (hanya proses pesan teks / media utama, abaikan ack / reaction / update)
        ALLOWED_EVENTS = {"message", "message.upsert", "message.create"}
        if event_name not in ALLOWED_EVENTS and "message" not in event_name:
            return {"status": "diabaikan"}

        if payload_waha.get("fromMe") is True:
            return {"status": "diabaikan"}

        # Filter khusus Stiker WhatsApp (Abaikan stiker agar tidak memicu doa/error)
        mimetype_raw = str(payload_waha.get("media", {}).get("mimetype") or payload_waha.get("mimetype") or "").lower()
        if payload_waha.get("type") in ["sticker", "ptt", "audio"] or "webp" in mimetype_raw:
            return {"status": "diabaikan_stiker"}

        # KASUS 1 & Deduplikasi: Mencegah race condition dari webhook ganda / replay
        msg_id = payload_waha.get("id") or payload_waha.get("_data", {}).get("id", {}).get("_serialized")
        if msg_id:
            if msg_id in PROCESSED_MSG_IDS:
                print(f"[Deduplikasi] Pesan ID {msg_id} telah diproses sebelumnya. Mengabaikan event duplikat.")
                return {"status": "duplikasi_diabaikan"}
            PROCESSED_MSG_IDS.add(msg_id)
            if len(PROCESSED_MSG_IDS) > 2000:
                PROCESSED_MSG_IDS.clear()

        pesan = payload_waha.get("body", "")
        raw_no_wa = payload_waha.get("author") or chat_id_asli
        nomor_wa = raw_no_wa.split('@')[0] if raw_no_wa else "0000000000"
        has_media = payload_waha.get("hasMedia", False) or bool(payload_waha.get("media")) or bool(payload_waha.get("mediaUrl"))

        nama_pengirim = (
            payload_waha.get("pushname") or
            payload_waha.get("notifyName") or
            payload_waha.get("_data", {}).get("notifyName") or
            "Kak"
        )

        print(f"[Teks Diterima] Dari: {nama_pengirim} ({nomor_wa}) | Media: {has_media} | Pesan: '{pesan}'")

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

                # Fix URL WAHA API jika menggunakan localhost:3000 atau path relatif /api/files/...
                if media_url:
                    media_url = media_url.replace("http://localhost:3000", WAHA_ENDPOINT).replace("http://127.0.0.1:3000", WAHA_ENDPOINT)
                    if media_url.startswith("/"):
                        media_url = f"{WAHA_ENDPOINT}{media_url}"

                if media_url and media_url.startswith("http"):
                    try:
                        headers_img = {"X-Api-Key": WAHA_API_KEY, "Accept": "*/*"}
                        res_img = requests.get(media_url, headers=headers_img, timeout=5)
                        if res_img.status_code == 200 and len(res_img.content) > 1000:
                            image_bytes = res_img.content
                            print(f"[Debug Media] Berhasil unduh gambar penuh dari URL ({len(image_bytes)} bytes)")
                        else:
                            print(f"[Warning Media Download] HTTP Status {res_img.status_code} ({len(res_img.content)} bytes)")
                    except Exception as e_img:
                        print(f"[Warning Webhook Image Download Error] {e_img}")

            # 3. Fallback: Unduh via WAHA Message Media API jika pesan memiliki ID
            msg_id = payload_waha.get("id") or payload_waha.get("_data", {}).get("id", {}).get("_serialized")
            if (not image_bytes or len(image_bytes) < 5000) and msg_id:
                try:
                    waha_media_endpoint = f"{WAHA_ENDPOINT}/api/{nama_sesi}/messages/{msg_id}/media"
                    res_msg_media = requests.get(waha_media_endpoint, headers={"X-Api-Key": WAHA_API_KEY}, timeout=5)
                    if res_msg_media.status_code == 200 and len(res_msg_media.content) > 1000:
                        image_bytes = res_msg_media.content
                        print(f"[Debug Media] Berhasil unduh dari WAHA Message API ({len(image_bytes)} bytes)")
                except Exception as e_msg_media:
                    print(f"[Warning WAHA Message Media API Error] {e_msg_media}")




        status_fsm = state_manager.get_status(nomor_wa)
        pesan_clean = (pesan or "").lower().strip()

        # Pemetaan nama program layar & detail penjelasan
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

        DETAIL_PROGRAM = {
            "1": "*PINTAS (Pinjaman Tanpa Syarat)*\nProgram pinjaman tanpa riba dan tanpa agunan dari Rumah Amal USK untuk membantu civitas akademika dan masyarakat yang membutuhkan dana darurat.",
            "pintas": "*PINTAS (Pinjaman Tanpa Syarat)*\nProgram pinjaman tanpa riba dan tanpa agunan dari Rumah Amal USK untuk membantu civitas akademika dan masyarakat yang membutuhkan dana darurat.",
            "2": "*BPRA-UKT*\nProgram Bantuan Penyelenggaraan Residensi & Akademik / Bantuan Pembayaran UKT bagi mahasiswa Universitas Syiah Kuala yang mengalami kesulitan finansial.",
            "bpra": "*BPRA-UKT*\nProgram Bantuan Penyelenggaraan Residensi & Akademik / Bantuan Pembayaran UKT bagi mahasiswa Universitas Syiah Kuala yang mengalami kesulitan finansial.",
            "bpra-ukt": "*BPRA-UKT*\nProgram Bantuan Penyelenggaraan Residensi & Akademik / Bantuan Pembayaran UKT bagi mahasiswa Universitas Syiah Kuala yang mengalami kesulitan finansial.",
            "3": "*OTA Palestina (Orang Tua Asuh Mahasiswa Palestina)*\nProgram bantuan beasiswa pendidikan dan biaya hidup bagi mahasiswa asal Palestina yang sedang menempuh studi di USK.",
            "ota palestina": "*OTA Palestina (Orang Tua Asuh Mahasiswa Palestina)*\nProgram bantuan beasiswa pendidikan dan biaya hidup bagi mahasiswa asal Palestina yang sedang menempuh studi di USK.",
            "palestina": "*OTA Palestina (Orang Tua Asuh Mahasiswa Palestina)*\nProgram bantuan beasiswa pendidikan dan biaya hidup bagi mahasiswa asal Palestina yang sedang menempuh studi di USK.",
            "4": "*GREEN QURBAN*\nProgram ibadah qurban ramah lingkungan yang dikelola Rumah Amal USK dengan kemasan tanpa plastik dan pembagian daging qurban yang tepat sasaran.",
            "green qurban": "*GREEN QURBAN*\nProgram ibadah qurban ramah lingkungan yang dikelola Rumah Amal USK dengan kemasan tanpa plastik dan pembagian daging qurban yang tepat sasaran.",
            "qurban": "*GREEN QURBAN*\nProgram ibadah qurban ramah lingkungan yang dikelola Rumah Amal USK dengan kemasan tanpa plastik dan pembagian daging qurban yang tepat sasaran.",
            "5": "*Bantuan Nasi Bungkus*\nProgram penyaluran bantuan makanan/nasi bungkus secara rutin bagi mahasiswa dhuafa dan warga yang membutuhkan di sekitar lingkungan kampus USK.",
            "nasi bungkus": "*Bantuan Nasi Bungkus*\nProgram penyaluran bantuan makanan/nasi bungkus secara rutin bagi mahasiswa dhuafa dan warga yang membutuhkan di sekitar lingkungan kampus USK.",
            "6": "*ECRA (Entrepreneurship Club Rumah Amal)*\nProgram pembinaan kewirausahaan, pendampingan usaha, dan penyaluran dana hibah modal usaha bagi mahasiswa USK.",
            "ecra": "*ECRA (Entrepreneurship Club Rumah Amal)*\nProgram pembinaan kewirausahaan, pendampingan usaha, dan penyaluran dana hibah modal usaha bagi mahasiswa USK.",
            "7": "*P2EMD*\nProgram Pemberdayaan Ekonomi Masyarakat Desa / Dhuafa berbasis potensi lokal berbasis usaha produktif dari Rumah Amal USK.",
            "p2emd": "*P2EMD*\nProgram Pemberdayaan Ekonomi Masyarakat Desa / Dhuafa berbasis potensi lokal berbasis usaha produktif dari Rumah Amal USK.",
            "8": "*Beasiswa Orang Tua Asuh (OTA)*\nProgram bantuan beasiswa rutin dari para donatur (Orang Tua Asuh) untuk mendukung keberlangsungan studi mahasiswa dhuafa berprestasi di USK.",
            "ota": "*Beasiswa Orang Tua Asuh (OTA)*\nProgram bantuan beasiswa rutin dari para donatur (Orang Tua Asuh) untuk mendukung keberlangsungan studi mahasiswa dhuafa berprestasi di USK.",
            "beasiswa ota": "*Beasiswa Orang Tua Asuh (OTA)*\nProgram bantuan beasiswa rutin dari para donatur (Orang Tua Asuh) untuk mendukung keberlangsungan studi mahasiswa dhuafa berprestasi di USK.",
            "9": "*Beasiswa Muallaf*\nProgram beasiswa khusus dan pendampingan pembinaan keagamaan bagi mahasiswa atau pelajar muallaf di USK.",
            "muallaf": "*Beasiswa Muallaf*\nProgram beasiswa khusus dan pendampingan pembinaan keagamaan bagi mahasiswa atau pelajar muallaf di USK.",
            "beasiswa muallaf": "*Beasiswa Muallaf*\nProgram beasiswa khusus dan pendampingan pembinaan keagamaan bagi mahasiswa atau pelajar muallaf di USK.",
            "10": "*BPMI*\nProgram Bantuan Pembinaan Masjid & Musholla serta kesejahteraan marbot/pengurus masjid di lingkungan Universitas Syiah Kuala.",
            "bpmi": "*BPMI*\nProgram Bantuan Pembinaan Masjid & Musholla serta kesejahteraan marbot/pengurus masjid di lingkungan Universitas Syiah Kuala."
        }

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
                "Baik Kak, permintaan Kakak sedang kami teruskan ke Admin untuk penanganan lebih lanjut. Mohon ditunggu ya.",
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

        sapaan_donatur = deteksi_sapaan_gender(nama_pengirim)

        # =====================================================================
        # FAST-PATH 0A: SAPAAN AWAL PADA STATE IDLE ("halo", "p", "assalamualaikum")
        # =====================================================================
        from admin_scripts import _is_sapaan
        if status_fsm == "IDLE" and not has_media:
            if _is_sapaan(pesan_clean) or pesan_clean in {"p", "ping", "p!", "ping!", "halo", "hai", "hi", "assalamualaikum"}:
                balasan = ambil_balasan("sapaan", nama_pengirim=nama_pengirim)
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "sapaan"}
        # Fast-Path Unlocking: Jika user sedang di status FSM aktif tetapi mengajukan pertanyaan baru spesifik, reset status ke IDLE
        KATA_KUNCI_OVERRIDE = ["pinjam", "pintas", "ukt", "bpra", "beasiswa", "alamat", "rekening", "admin", "batal", "cancel", "bantuan ukt", "kurang dana", "lokasi", "jam kerja", "riwayat"]
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
            balasan = (
                "Berikut pilihan program penyaluran yang tersedia di Rumah Amal USK:\n\n"
                "1. PINTAS (Pinjaman Tanpa Syarat)\n"
                "2. BPRA-UKT\n"
                "3. OTA Palestina (Orang Tua Asuh Mahasiswa Palestina)\n"
                "4. GREEN QURBAN\n"
                "5. Bantuan Nasi Bungkus\n"
                "6. ECRA (Entrepreneurship Club Rumah Amal)\n"
                "7. P2EMD\n"
                "8. Beasiswa Orang Tua Asuh (OTA)\n"
                "9. Beasiswa Muallaf\n"
                "10. BPMI\n\n"
                "----------------------------------------\n"
                "📌 *Pilihan Navigasi:*\n"
                f"• Ketik angka *1 s.d. 10* untuk melihat detail program di atas\n"
                "• Ketik *0* untuk Kembali ke Menu Utama"
            )
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
                "3": "ota_palestina",
                "4": "green_qurban",
                "5": "nasi_bungkus",
                "6": "ecra",
                "7": "p2emd",
                "8": "ota_beasiswa",
                "9": "muallaf",
                "10": "bpmi"
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
                    "3. OTA Palestina (Orang Tua Asuh Mahasiswa Palestina)\n"
                    "4. GREEN QURBAN\n"
                    "5. Bantuan Nasi Bungkus\n"
                    "6. ECRA (Entrepreneurship Club Rumah Amal)\n"
                    "7. P2EMD\n"
                    "8. Beasiswa Orang Tua Asuh (OTA)\n"
                    "9. Beasiswa Muallaf\n"
                    "10. BPMI\n\n"
                    "----------------------------------------\n"
                    "📌 *Pilihan Navigasi:*\n"
                    f"• Ketik angka *1 s.d. 10* untuk melihat detail program di atas\n"
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
            if any(k in pesan_clean for k in ["ya", "iya", "sambungkan", "ok", "oke", "setuju"]):
                state_manager.reset_status(nomor_wa)
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

            if any(k in pesan_clean for k in ["batal", "cancel", "tidak", "ga", "gak"]):
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
        # FAST-PATH 1A-2: DETEKSI CEK RIWAYAT TRANSAKSI DONASI (TYPO TOLERANT)
        # =====================================================================
        is_cek_riwayat = (pesan_clean in ["4", "4.", "cek riwayat", "riwayat donasi", "histori donasi", "riwayat transaksi", "cek transaksi", "donasi saya", "riwayat saya", "histori saya", "lihat riawayat", "lihat riwayat", "liat riwayat"]) or bool(re.search(r"(cek|lihat|liat|tampilkan|minta|info|riwayat|riawayat|riwayt|history)\s*(riwayat|riawayat|riwayt|histori|history|transaksi|donasi|pembayaran)", pesan_clean)) or ("riwayat" in pesan_clean or "riawayat" in pesan_clean or "histori" in pesan_clean)
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
        # FAST-PATH 1B: DETEKSI NIAT DONASI / ZAKAT (MENU UTAMA DONASI 1-4)
        # =====================================================================
        is_niat_donasi = bool(re.search(
            r"(donasi|berdonasi|sedekah|zakat|penyalurkan|penyaluran|berdonas|inginberdonasi|mauberdonasi|mauzakat|inginzakat|bayar zakat|ingin donasi)",
            pesan_clean
        )) or (pesan_clean in ["2", "2.", "ingin berdonasi", "ingin berdonasi?"])

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

        # Fast-Path Unlocking: Jika user sedang di status FSM aktif tetapi mengajukan pertanyaan baru spesifik, reset status ke IDLE
        KATA_KUNCI_OVERRIDE = ["pinjam", "pintas", "ukt", "bpra", "beasiswa", "alamat", "rekening", "admin", "batal", "cancel", "bantuan ukt", "kurang dana", "lokasi", "jam kerja", "riwayat"]
        if status_fsm in {"PILIH_PROGRAM", "NUNGGU_BUKTI_TRANSFER", "NUNGGU_DATA_KONFIRMASI", "NUNGGU_DATA_INFAK", "TANYA_PROGRAM"} and not has_media:
            if any(k in pesan_clean for k in KATA_KUNCI_OVERRIDE):
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
            balasan = (
                "Berikut program beasiswa resmi yang tersedia di Rumah Amal USK:\n\n"
                "1. BPRA-UKT (Bantuan Biaya UKT Mahasiswa)\n"
                "2. OTA PALESTINA (Beasiswa & Biaya Hidup Mahasiswa Palestina)\n"
                "3. BEASISWA ORANG TUA ASUH (OTA) (Mahasiswa Dhuafa Berprestasi)\n"
                "4. BEASISWA MUALLAF (Khusus Mahasiswa/Masyarakat Muallaf)\n\n"
                "----------------------------------------\n"
                "📌 *Pilihan Navigasi:*\n"
                f"• Ketik *1* atau *Program apa saja* untuk melihat katalog 10 program lengkap\n"
                "• Ketik *0* untuk Kembali ke Menu Utama"
            )
            user_sessions[nomor_wa] = session_data
            send_message_to_waha(chat_id_asli, balasan, nama_sesi)
            return {"status": "sukses", "intent": "info_beasiswa"}

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
                "🏦 *Bank BSI:* 7099400409\n"
                "👤 *a.n.* Rumah Amal Mesjid Unsyiah"
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
                    f"🏦 *Bank BSI:* 7099400409\n"
                    f"👤 *a.n.* Rumah Amal Mesjid Unsyiah\n\n"
                    f"Setelah melakukan transfer, silakan kirimkan foto/gambar bukti transfer (resi BSI Mobile / BYOND) ke sini ya {sapaan_donatur} agar dapat kami proses dan catatkan. Terima kasih! 🙏"
                )
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "lanjut_sesi"}

            # 3. Pengecekan Kata Sapaan
            if any(s in pesan_clean for s in ["halo", "assalamualaikum", "selamat", "pagi", "siang", "sore", "malam", "ping", "p", "hi", "hai"]) and status_fsm != "PILIH_PROGRAM":
                session_info = state_manager.get_session(nomor_wa)
                target_prog_session = session_info.get("target_program") or "Infak / Zakat"
                nama_prog = PETA_NAMA.get(target_prog_session, target_prog_session)

                balasan = (
                    f"Halo {sapaan_donatur} {nama_pengirim}! 🙏\n"
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
        if status_fsm == "PILIH_PROGRAM":
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

            kode_target, nama_target = "INF-RUTIN", "Infak Rutin"
            if pesan_clean in PETA_PILIHAN:
                kode_target, nama_target = PETA_PILIHAN[pesan_clean]
            else:
                for k, (kode, nama_p) in PETA_PILIHAN.items():
                    if k in pesan_clean:
                        kode_target, nama_target = kode, nama_p
                        break

            state_manager.update_status(nomor_wa, "NUNGGU_BUKTI_TRANSFER", target_program=kode_target)
            balasan = (
                f"Baik Kak, untuk penyaluran *{nama_target}* silakan melakukan transfer ke rekening resmi kami:\n\n"
                f"🏦 *Bank BSI:* 7099400409\n"
                f"👤 *a.n.* Rumah Amal Mesjid Unsyiah\n\n"
                f"Setelah melakukan transfer, silakan kirimkan foto/gambar bukti transfer (resi BSI Mobile / BYOND) ke sini ya Kak agar dapat kami proses dan catatkan. Terima kasih! 🙏"
            )
            user_sessions[nomor_wa] = session_data
            send_message_to_waha(chat_id_asli, balasan, nama_sesi)
            return {"status": "sukses", "intent": "pilih_program_selesai"}



        # =====================================================================
        # FAST-PATH 4: STATE NUNGGU_BUKTI_TRANSFER / KONFIRMASI / MEDIA RESI
        # (LOCAL PYTHON REGEX FIRST - 0.001s ANTI TIMEOUT)
        # =====================================================================
        if status_fsm == "NUNGGU_BUKTI_TRANSFER" or status_fsm == "NUNGGU_DATA_KONFIRMASI" or (has_media and status_fsm != "IDLE"):
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
            nominal = data_diekstrak.get("nominal") or nominal_local
            program_kode = data_diekstrak.get("program")
            if not program_kode or program_kode == "UMUM":
                program_kode = target_prog_session

            nama_program_layar = PETA_NAMA.get(program_kode, "Infak / Sedekah")

            if nominal:
                nomor_hp_real, _ = _dapatkan_nomor_hp_asli(chat_id_asli, payload_waha, nama_sesi)
                state_manager.simpan_transaksi_final(nomor_hp_real, nama, f"Donasi {nama_program_layar}", nominal, kode_program=program_kode)
                state_manager.reset_status(nomor_wa)

                sapaan_donatur = deteksi_sapaan_gender(nama)
                doa_teks = _dapatkan_doa_spesifik(program_kode)
                balasan = f"Alhamdulillah, donasi sebesar Rp{nominal} dari {sapaan_donatur} {nama} untuk program *{nama_program_layar}* telah kami terima.\n\n{doa_teks}"
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "konfirmasi_sukses"}
            else:
                state_manager.update_status(nomor_wa, "NUNGGU_BUKTI_TRANSFER", target_program=target_prog_session)
                sapaan_donatur = deteksi_sapaan_gender(nama_pengirim)
                if has_media:
                    balasan = f"Mohon maaf, gambar resi kurang terbaca. Boleh {sapaan_donatur} ketikkan secara manual Nama dan Nominalnya?"
                else:
                    balasan = f"Mohon maaf {sapaan_donatur} {nama_pengirim}, Mimin kurang menangkap nominal transfernya. Boleh diulangi dengan menyebutkan *Nama Lengkap*, *Nominal Transfer*, dan *Program Donasinya*? Atau {sapaan_donatur} bisa langsung melampirkan foto resi transfer BSI Mobile / BYOND ke sini."

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
            pekerjaan = data_diekstrak.get("pekerjaan") or "-"
            nominal = data_diekstrak.get("nominal")

            if nama and nominal:
                nomor_hp_real, _ = _dapatkan_nomor_hp_asli(chat_id_asli, payload_waha, nama_sesi)
                state_manager.simpan_transaksi_final(nomor_hp_real, nama, pekerjaan, nominal)
                state_manager.reset_status(nomor_wa)

                sapaan_donatur = deteksi_sapaan_gender(nama)
                balasan = f"MasyaAllah, pendaftaran/pencatatan atas nama {sapaan_donatur} {nama} (profesi: {pekerjaan}) untuk nominal Rp{nominal} berhasil dicatat! Semoga berkah."
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "one_shot_ner_infak"}
            else:
                balasan = "Maaf Kak, Mimin kurang menangkap datanya. Boleh diulangi dengan menyebutkan Nama, Pekerjaan, dan Nominalnya?"
                user_sessions[nomor_wa] = session_data
                send_message_to_waha(chat_id_asli, balasan, nama_sesi)
                return {"status": "sukses", "intent": "one_shot_ner_retry"}

        # =====================================================================
        # FAST-PATH: STATE MENUNGGU_ADMIN (PENANGANAN KONFIRMASI 'YA' / 'BATAL')
        # =====================================================================
        if status_fsm == "MENUNGGU_ADMIN":
            pesan_normal = (pesan or "").strip().lower()
            if any(k in pesan_normal for k in ["ya", "iya", "sambungkan", "ok", "oke", "setuju", "boleh", "lanjut"]):
                session_info = state_manager.get_session(nomor_wa)
                nama_prog_admin = session_info.get("target_program") or "PINTAS"
                state_manager.reset_status(nomor_wa)
                session_data["state"] = "IDLE"

                # 1. Beri tahu user
                balasan_user = "Baik Kak, permintaan Kakak sedang kami teruskan ke Admin untuk penanganan lebih lanjut. Mohon ditunggu ya."
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

            elif any(k in pesan_normal for k in ["batal", "cancel", "tidak", "ga", "gak"]):
                state_manager.reset_status(nomor_wa)
                session_data["state"] = "IDLE"
                balasan_user = "Baik Kak, pengajuan sambung ke Admin telah dibatalkan. Ada lagi hal lain yang bisa Mimin bantu?"
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

        # Filter Bypass LLM (Termasuk sapaan & menu agar tidak dihalusinasi LLM)
        should_bypass_llm = (
            hasil.get("should_wait_admin") or
            any(i in {"handoff_admin", "handoff_admin_prompt", "doa_zakat_mal", "doa_infak", "sapaan", "info_program"} for i in hasil.get("intents", [])) or
            "sapaan" in intent
        )

        if hasil.get("should_wait_admin"):
            session_data["state"] = "MENUNGGU_ADMIN"
        else:
            session_data["state"] = "IDLE"

        if should_bypass_llm:
            balasan = fakta_script
        else:
            jawaban_llm = panggil_llm_teks(pesan, fakta_script, nama_pengirim=nama_pengirim)

            if jawaban_llm and verifikasi_halusinasi(intent, jawaban_llm, fakta_script):
                print("[Guardrail Pass] Jawaban LLM luwes dan terverifikasi 100% akurat!")
                balasan = jawaban_llm
            else:
                print("[Guardrail Fallback] LLM berhalusinasi/offline. Menggunakan fakta_script statis.")
                balasan = fakta_script

        user_sessions[nomor_wa] = session_data

        print(f"[Balasan Akhir Dikirim]\n{balasan}")
        send_message_to_waha(chat_id_asli, balasan, nama_sesi)

        return {"status": "sukses", "intent": intent}

    except Exception as e:
        print(f"[Error Webhook] {e}")
        return {"status": "error", "detail": str(e)}

