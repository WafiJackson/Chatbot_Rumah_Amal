import os
import json
import re
import base64
import requests

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-2.5-flash")


def _detect_mime_type(image_bytes: bytes) -> str:
    """Mendeteksi mime-type gambar dari magic bytes (JPEG, PNG, WEBP)."""
    if not image_bytes or len(image_bytes) < 4:
        return "image/jpeg"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:20]:
        return "image/webp"
    return "image/jpeg"


def _panggil_gemini_api(prompt: str, image_bytes: bytes | None = None, is_json: bool = False) -> str:
    """Helper internal 100% Cloud-Only untuk memanggil Google Gemini 2.5 Flash API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    parts = []
    if image_bytes:
        mime_type = _detect_mime_type(image_bytes)
        b64_img = base64.b64encode(image_bytes).decode("utf-8")
        parts.append({
            "inline_data": {
                "mime_type": mime_type,
                "data": b64_img
            }
        })
        
    parts.append({"text": prompt})
    payload = {"contents": [{"parts": parts}]}
    if is_json:
        payload["generationConfig"] = {"response_mime_type": "application/json"}

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        if res.status_code == 200:
            data = res.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts_out = candidates[0].get("content", {}).get("parts", [])
                if parts_out:
                    return parts_out[0].get("text", "").strip()
        else:
            print(f"[Warning Gemini API Status {res.status_code}] {res.text[:200]}")
    except Exception as e:
        print(f"[Error Gemini API] {e}")
    return ""


def ekstrak_data_ner(pesan_user: str) -> dict:
    """
    Mengekstrak data Nama, Pekerjaan, dan Nominal dari pesan pengguna via Gemini Cloud API.
    """
    system_prompt = """Kamu adalah mesin Named Entity Recognition (NER). 
Tugasmu mengekstrak 3 entitas dari pesan pengguna: Nama, Pekerjaan, dan Nominal.
- Pekerjaan: Bisa berupa instansi, status (misal: mahasiswa), atau singkatan jabatan.
- Nominal: Wajib dibersihkan menjadi angka murni (misal: '800.000' menjadi '800000').
Jika tidak ada, isi null.
KEMBALIKAN HANYA FORMAT JSON MURNI {"nama": null, "pekerjaan": null, "nominal": null}."""

    prompt = f"{system_prompt}\n\nPesan: '{pesan_user}'\nOutput JSON:"
    raw_text = _panggil_gemini_api(prompt, is_json=True)

    try:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            raw_text = match.group(0)
        data = json.loads(raw_text) if raw_text else {}

        def _clean_val(v):
            if v is None:
                return None
            v_str = str(v).strip()
            if v_str.lower() in {"null", "none", "", "nullnull"}:
                return None
            return v_str

        return {
            "nama": _clean_val(data.get("nama")),
            "pekerjaan": _clean_val(data.get("pekerjaan")),
            "nominal": _clean_val(data.get("nominal"))
        }
    except Exception as e:
        print(f"[Error NER Parse] {e}")
        return {"nama": None, "pekerjaan": None, "nominal": None}


def panggil_llm_teks(pesan_user: str, fakta_script: str, nama_pengirim: str = "Kak") -> str:
    """
    LLM Paraphraser via Gemini 2.5 Flash Cloud API.
    """
    system_prompt = f"""Kamu adalah 'Mimin', asisten virtual resmi Rumah Amal Masjid Jamik USK.
Gaya bahasamu: Ramah, empatik, sopan, islami, dan luwes seperti manusia. Sapa pengirim dengan nama '{nama_pengirim}'.
Tugasmu: Menyusun fakta lembaga menjadi balasan WhatsApp yang natural.

ATURAN MUTLAK:
1. DILARANG mengubah, mengarang, atau menghilangkan NOMOR REKENING, ANGKA, NOMOR TELEPON, atau NAMA PROGRAM dari fakta.
2. Jangan menambahkan syarat atau aturan yang tidak tertulis.
3. Langsung berikan jawaban, jangan gunakan format JSON."""

    prompt = f"{system_prompt}\n\n[PESAN PENGGUNA]: '{pesan_user}'\n[FAKTA LEMBAGA]: '{fakta_script}'\n\nJAWABAN MIMIN:"
    return _panggil_gemini_api(prompt)


def verifikasi_halusinasi(intent: str, jawaban_llm: str, fakta_script: str = "") -> bool:
    """
    Post-Validator Guardrail: Memastikan tidak ada angka/URL yang hilang atau dikarang LLM.
    """
    if not jawaban_llm or len(jawaban_llm.strip()) < 10:
        return False

    jawaban_low = jawaban_llm.lower()
    fakta_low = (fakta_script or "").lower()

    # Pengecekan Angka Krusial
    angka_fakta = re.findall(r'\b\d[\d\.\-]{2,}\d\b', fakta_low)
    for angka in angka_fakta:
        angka_bersih = angka.replace("-", "")
        if angka not in jawaban_low and angka_bersih not in jawaban_low.replace("-", ""):
            print(f"[Guardrail Fail] Angka krusial '{angka}' dihilangkan oleh LLM!")
            return False

    # Pengecekan Angka Palsu
    angka_llm = re.findall(r'\b\d[\d\.\-]{4,}\d\b', jawaban_low)
    for angka in angka_llm:
        angka_bersih = angka.replace("-", "")
        if angka not in fakta_low and angka_bersih not in fakta_low.replace("-", ""):
            print(f"[Guardrail Fail] LLM mengarang angka/rekening palsu: '{angka}'!")
            return False

    return True


def get_intent(pesan: str) -> str:
    """Menggunakan Gemini 2.5 Flash untuk mengklasifikasikan intent dari pesan pengguna."""
    system_prompt = """Anda adalah mesin pengklasifikasi niat untuk customer service Rumah Amal Masjid Jamik USK.
Tugas Anda HANYA membalas dengan SATU KATA KUNCI dari daftar intent resmi. JANGAN TULIS HAL LAIN SAMA SEKALI.

DAFTAR KATA KUNCI INTENT UTAMA:
- info_jam_kerja, info_alamat, info_kontak, visi_lembaga, misi_lembaga, motto_lembaga, sasaran_mustahik
- cara_donasi, info_rekening, info_qris, laporan_penyaluran, info_infak_rutin, daftar_infak_rutin, jenis_zakat
- info_program, info_bpra_ukt, syarat_beasiswa_umum, double_funding, peduli_sigra, bantuan_bencana_mahasiswa
- modal_usaha, pembinaan_umkm, mitra_eksternal
- sapaan, ingin_donasi, minta_bantuan_pintas, konfirmasi_donasi, tidak_diketahui"""

    prompt = f"{system_prompt}\n\nPesan Pengguna: '{pesan}'\nBalasan:"
    res_intent = _panggil_gemini_api(prompt)
    if res_intent:
        first_word = res_intent.split()[0].lower().strip(" .,\"'\n")
        return first_word
    return "tidak_diketahui"


def ekstrak_resi_vision(image_bytes: bytes, caption: str = "") -> dict:
    """
    Multimodal Vision OCR via Gemini 2.5 Flash Cloud API:
    Membaca foto resi transfer bank (BSI Mobile, BYOND, QRIS) secara langsung tanpa Ollama/EasyOCR!
    """
    nama_local = None
    nominal_local = None

    prompt = f"""Kamu adalah mesin Vision OCR khusus membaca foto resi transfer bank (BSI Mobile, BYOND, QRIS).
Tugasmu mengekstrak data berikut dari foto resi ini:
- nama: Nama Pengirim / Donatur (pada resi BSI Mobile cari 'Pengirim'/'Dari Rekening', pada BYOND cari nama pemilik rekening sumber di bawah nominal). Jika tidak ada, isi null.
- nominal: Angka nominal murni tanpa titik/koma/rupiah (misal 'Rp 50.000' -> '50000', '100.000' -> '100000'). Jika tidak ada, isi null.
- program: Kode program ('ZKT-MAL', 'ZKT-PENGHASILAN', 'INF-RUTIN', 'DON-PALESTINA', atau 'UMUM').

Caption Pengguna: '{caption}'

KEMBALIKAN HANYA FORMAT JSON MURNI:
{{"nama": "NAMA_DONATUR", "nominal": "NOMINAL_ANGKA", "program": "KODE_PROGRAM"}}"""

    raw_json = _panggil_gemini_api(prompt, image_bytes=image_bytes, is_json=True)

    try:
        match = re.search(r"\{.*\}", raw_json, re.DOTALL)
        if match:
            raw_json = match.group(0)
        data = json.loads(raw_json) if raw_json else {}

        def _clean(val):
            if not val or str(val).lower() in {"null", "none", ""}:
                return None
            return str(val).strip()

        nama_res = _clean(data.get("nama"))
        nominal_raw = _clean(data.get("nominal"))
        nominal_clean = None
        if nominal_raw:
            digits = re.sub(r"[^\d]", "", nominal_raw)
            if digits and int(digits) >= 1000:
                nominal_clean = digits

        return {
            "nama": nama_res,
            "nominal": nominal_clean,
            "program": _clean(data.get("program")) or "UMUM"
        }
    except Exception as e:
        print(f"[Error Gemini Vision Resi] {e}")
        return {"nama": None, "nominal": None, "program": "UMUM"}


def ekstrak_konfirmasi_donasi(pesan_user: str) -> dict:
    """Mengekstrak data konfirmasi transfer dari pesan teks pengguna via Gemini API."""
    system_prompt = """Kamu adalah mesin Named Entity Recognition (NER). 
Tugasmu mengekstrak 3 entitas konfirmasi dari pesan pengguna:
- nama: Nama donatur.
- nominal: Wajib angka murni (misal: '500rb' -> '500000').
- program: Kode program (INF-RUTIN, ZKT-MAL, ZKT-PENGHASILAN, DON-PALESTINA, LAINNYA).
KEMBALIKAN HANYA FORMAT JSON MURNI: {"nama": "Budi", "nominal": "500000", "program": "ZKT-MAL"}"""

    prompt = f"{system_prompt}\n\nPesan: '{pesan_user}'\nOutput JSON:"
    raw_text = _panggil_gemini_api(prompt, is_json=True)
    
    try:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            raw_text = match.group(0)
            
        data = json.loads(raw_text) if raw_text else {}
        return {
            "nama": data.get("nama"), 
            "nominal": data.get("nominal"), 
            "program": data.get("program")
        }
    except Exception as e:
        print(f"[Error NER Konfirmasi] {e}")
        return {"nama": None, "nominal": None, "program": None}
