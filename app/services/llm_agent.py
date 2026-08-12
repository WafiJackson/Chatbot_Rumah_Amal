import os
import json
import re
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-2.5-flash").strip()


def _detect_mime_type(image_bytes: bytes) -> str:
    if not image_bytes:
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:16]:
        return "image/webp"
    return "image/jpeg"


def _panggil_gemini_api(prompt: str, image_bytes: bytes = None, is_json: bool = False, timeout: int = 8) -> str:
    """
    Helper utama untuk memanggil Google Gemini Cloud API (gemini-2.5-flash).
    Mendukung pengiriman teks prompt dan gambar (multimodal OCR Vision JPEG/PNG/WEBP).
    """
    api_key = os.getenv("GEMINI_API_KEY", GEMINI_API_KEY).strip()
    model = os.getenv("MODEL_NAME", MODEL_NAME).strip()
    if not api_key:
        print("[Warning Gemini API] GEMINI_API_KEY belum terkonfigurasi!")
        return ""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    parts = []
    if image_bytes and len(image_bytes) > 500:
        try:
            mime = _detect_mime_type(image_bytes)
            img_b64 = base64.b64encode(image_bytes).decode("utf-8")
            parts.append({
                "inline_data": {
                    "mime_type": mime,
                    "data": img_b64
                }
            })
        except Exception as e_img:
            print(f"[Warning Gemini Image Encode] {e_img}")

    parts.append({"text": prompt})

    payload = {
        "contents": [{"parts": parts}]
    }

    if is_json:
        payload["generationConfig"] = {"responseMimeType": "application/json"}

    try:
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts_out = candidates[0].get("content", {}).get("parts", [])
                if parts_out:
                    return parts_out[0].get("text", "").strip()
        else:
            print(f"[Warning Gemini API Status {response.status_code}] {response.text}")
    except Exception as e:
        print(f"[Error Gemini API] {e}")
    return ""


def ekstrak_data_ner(pesan_user: str) -> dict:
    """
    Mengekstrak data Nama, Pekerjaan, dan Nominal dari pesan bebas pengguna
    menggunakan Google Gemini Cloud API dan mengembalikan JSON.
    """
    system_prompt = """Kamu adalah mesin Named Entity Recognition (NER). 
Tugasmu mengekstrak 3 entitas dari pesan pengguna: Nama, Pekerjaan, dan Nominal.
- Pekerjaan: Bisa berupa instansi, status (misal: mahasiswa), atau singkatan jabatan (misal: CEO, CTO, Direktur, Staff).
- Nominal: Wajib dibersihkan menjadi angka murni (misal: '8 ratus ribu' atau '800.000' menjadi '800000').
Jika ada entitas yang benar-benar tidak disebutkan, isi dengan null.
KEMBALIKAN HANYA FORMAT JSON MURNI TANPA TEKS PENJELASAN LAIN.

CONTOH:
Pesan: "Nama saya Budi, pegawai negeri, mau infak 50 ribu"
Output JSON: {"nama": "Budi", "pekerjaan": "pegawai negeri", "nominal": "50000"}"""

    prompt = f"{system_prompt}\n\nPesan: '{pesan_user}'\nOutput JSON:"

    raw_text = _panggil_gemini_api(prompt, is_json=True, timeout=7)
    if not raw_text:
        return {"nama": None, "pekerjaan": None, "nominal": None}

    try:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            raw_text = match.group(0)

        data = json.loads(raw_text)

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
        print(f"[Error NER Parse] {e} | Raw Text: {raw_text}")
        return {"nama": None, "pekerjaan": None, "nominal": None}


def panggil_llm_teks(pesan_user: str, fakta_script: str, nama_pengirim: str = "Kak") -> str:
    """
    LLM Paraphraser (Tahap 1 Blueprint 2):
    Mimin (Virtual Assistant) menyusun ulang seluruh fakta menjadi balasan WhatsApp
    yang ramah, empatik, sopan, islami, dan luwes menggunakan Google Gemini API.
    """
    system_prompt = f"""Kamu adalah 'Mimin', asisten virtual resmi Rumah Amal Masjid Jamik USK.
Gaya bahasamu: Ramah, empatik, sopan, islami, dan luwes seperti manusia. Sapa pengirim dengan nama '{nama_pengirim}'.
Tugasmu: Saya akan memberikan [PESAN PENGGUNA] dan [FAKTA LEMBAGA]. Tulis ulang [FAKTA LEMBAGA] tersebut untuk menjawab [PESAN PENGGUNA] dengan gaya bahasamu yang natural.

ATURAN MUTLAK:
1. DILARANG mengubah, mengarang, atau menghilangkan NOMOR REKENING, ANGKA, NOMOR TELEPON, atau NAMA PROGRAM dari [FAKTA LEMBAGA].
2. Jangan menambahkan syarat atau aturan yang tidak tertulis di [FAKTA LEMBAGA].
3. Langsung berikan jawaban, jangan gunakan format JSON atau embel-embel 'Berikut jawabannya'."""

    prompt = f"{system_prompt}\n\n[PESAN PENGGUNA]: '{pesan_user}'\n[FAKTA LEMBAGA]: '{fakta_script}'\n\nJAWABAN MIMIN:"
    return _panggil_gemini_api(prompt, is_json=False, timeout=7)


def verifikasi_halusinasi(intent: str, jawaban_llm: str, fakta_script: str = "") -> bool:
    """
    Post-Validator Guardrail (Dynamic Two-Way Verification):
    1. Omission Check: Memastikan LLM tidak membuang angka krusial/URL dari fakta.
    2. Hallucination Check: Memastikan LLM tidak menambahkan nomor rekening/kontak/URL palsu.
    """
    if not jawaban_llm or len(jawaban_llm.strip()) < 10:
        return False

    jawaban_low = jawaban_llm.lower()
    fakta_low = (fakta_script or "").lower()

    # 1. PENGECEKAN DATA HILANG (Omission Check)
    angka_fakta = re.findall(r'\b\d[\d\.\-]{2,}\d\b', fakta_low)
    for angka in angka_fakta:
        angka_bersih = angka.replace("-", "")
        if angka not in jawaban_low and angka_bersih not in jawaban_low.replace("-", ""):
            print(f"[Guardrail Fail] Angka krusial '{angka}' dihilangkan oleh LLM!")
            return False

    url_fakta = re.findall(r'\b[a-z0-9\-]+\.[a-z]{2,}(?:\.[a-z]{2,})?\b', fakta_low)
    for url in url_fakta:
        if url not in jawaban_low:
            print(f"[Guardrail Fail] Tautan '{url}' dihilangkan oleh LLM!")
            return False

    # 2. PENGECEKAN DATA PALSU (Hallucination Check)
    angka_llm = re.findall(r'\b\d[\d\.\-]{4,}\d\b', jawaban_low)
    for angka in angka_llm:
        angka_bersih = angka.replace("-", "")
        if angka not in fakta_low and angka_bersih not in fakta_low.replace("-", ""):
            print(f"[Guardrail Fail] LLM mengarang angka/rekening palsu: '{angka}'!")
            return False

    url_llm = re.findall(r'\b[a-z0-9\-]+\.[a-z]{2,}(?:\.[a-z]{2,})?\b', jawaban_low)
    for url in url_llm:
        if url not in fakta_low:
            print(f"[Guardrail Fail] LLM mengarang tautan palsu: '{url}'!")
            return False

    # 3. PENGECEKAN KATA KUNCI SPESIFIK
    if intent == "info_alamat":
        if not any(k in jawaban_low for k in ["masjid jamik", "usk", "syiah kuala"]):
            print("[Guardrail Fail] Kata kunci alamat lokasi hilang!")
            return False
            
    if intent in {"info_rekening", "cara_donasi"}:
        if "bsi" not in jawaban_low:
            print("[Guardrail Fail] Nama Bank BSI dihilangkan!")
            return False

    return True


def get_intent(pesan: str) -> str:
    """Menggunakan Google Gemini API untuk mengklasifikasikan intent dari pesan pengguna."""
    system_prompt = """Anda adalah mesin pengklasifikasi niat untuk customer service Rumah Amal Masjid Jamik USK.
Tugas Anda HANYA membalas dengan SATU KATA KUNCI dari daftar di bawah ini yang paling sesuai dengan pesan pengguna. JANGAN TULIS HAL LAIN SAMA SEKALI.

DAFTAR KATA KUNCI INTENT:
[BAGIAN I: PROFIL & OPERASIONAL]
- info_jam_kerja (jam operasional kantor, buka/tutup)
- info_alamat (lokasi kantor, alamat masjid jamik USK)
- info_kontak (nomor WhatsApp/hotline admin)
- visi_lembaga (visi Rumah Amal USK)
- misi_lembaga (misi Rumah Amal USK)
- motto_lembaga (motto Rumah Amal USK)
- sasaran_mustahik (sasaran penerima bantuan/mustahik)
- direktur_lembaga (pimpinan/direktur lembaga)
- status_resmi_usk (status kelembagaan resmi di bawah USK)

[BAGIAN II: DONASI & ZAKAT]
- cara_donasi (tata cara penyaluran donasi non-tunai/tunai)
- info_rekening (nomor rekening bank BSI resmi)
- info_qris (kode QRIS / e-wallet)
- laporan_penyaluran (transparansi laporan penyaluran dana)
- info_infak_rutin (penjelasan program sedekah/infak rutin)
- daftar_infak_rutin (ingin mendaftar program infak rutin bulanan)
- zakat_pajak (zakat sebagai pengurang pajak penghasilan)
- jenis_zakat (jenis zakat: mal, penghasilan/profesi, fitrah)
- donatur_umum (donasi dari umum/alumni/swasta/pemerintah)
- kalkulator_zakat (fitur kalkulator zakat website)

[BAGIAN III: BEASISWA & BANTUAN MAHASISWA]
- info_program (daftar seluruh program beasiswa/bantuan)
- info_bpra_ukt (beasiswa BPRA-UKT mahasiswa USK)
- syarat_beasiswa_umum (syarat umum mendaftar beasiswa)
- alasan_aturan_akhlak (alasan syarat tidak merokok/pacaran)
- diskualifikasi_judol (diskualifikasi judi online / pelanggaran syariat)
- cara_daftar_beasiswa (tata cara pendaftaran online beasiswa)
- dokumen_beasiswa (syarat berkas/dokumen wajib beasiswa)
- semester_beasiswa (batasan semester 2-8 / maba)
- syarat_ipk (minimal IPK 3.00 beasiswa)
- double_funding (aturan tidak sedang menerima beasiswa lain/KIP-K)
- peduli_sigra (program bantuan darurat Peduli SIGRA)
- bantuan_bencana_mahasiswa (bantuan darurat musibah/kebakaran/laptop)
- seleksi_wawancara (tahap seleksi wawancara beasiswa)
- survei_rumah (survei kunjungan lapangan ke rumah)
- kewajiban_penerima (kewajiban pembinaan & sosial penerima beasiswa)
- periode_beasiswa (jadwal pendaftaran dibuka berapa kali setahun)

[BAGIAN IV: PEMBERDAYAAN & MITRA]
- modal_usaha (bantuan modal usaha P2EMD dhuafa)
- pembinaan_umkm (pembinaan UMKM & sertifikasi halal)
- mitra_eksternal (kemitraan instansi & CSR perusahaan)
- tujuan_kolaborasi_csr (tujuan kerja sama CSR)
- laporan_publik (akses unduh laporan tahunan)

[BAGIAN V: RAMADAN, QURBAN & LAINNYA]
- takjil_ramadan (takjil & paket berbuka gratis ramadan)
- apresiasi_fisabilillah (paket sembako/THR fisabilillah)
- qurban (penyaluran hewan/daging kurban)
- posko_bencana (bantuan bencana alam / solidaritas Palestina)

[BAGIAN VI: SAPAAN, NIAT DONASI, MINTA BANTUAN & KONFIRMASI]
- sapaan (pengguna menyapa: halo, assalamualaikum, selamat pagi, ping)
- ingin_donasi (pengguna menyatakan niat ingin berdonasi, menyumbang, atau sedekah tapi belum menyebut programnya)
- minta_bantuan_pintas (pengguna memohon bantuan dana, membutuhkan pinjaman, atau meminta donasi untuk diri sendiri)
- konfirmasi_donasi (pengguna menyatakan SUDAH transfer, SUDAH membayar, atau mengirim resi/bukti transfer)
- tidak_diketahui (di luar konteks atau pertanyaan tidak relevan)
"""

    prompt = f"{system_prompt}\n\nPesan Pengguna: '{pesan}'\nBalasan Intent:"
    hasil_intent = _panggil_gemini_api(prompt, is_json=False, timeout=5)
    if not hasil_intent:
        return "tidak_diketahui"
    first_word = hasil_intent.split()[0] if hasil_intent else "tidak_diketahui"
    return first_word.strip(" .,\"'\n")


def ekstrak_resi_vision(image_bytes: bytes, caption: str = "") -> dict:
    """
    Pipeline Vision NER Google Gemini untuk resi transfer bank (BSI Mobile, BYOND by BSI, QRIS, dll):
    1. Melakukan ekstraksi Regex lokal 0.001s terlebih dahulu.
    2. Mengirimkan gambar resi asli ke Google Gemini Multimodal Vision API untuk di-parse ke JSON terstruktur.
    """
    raw_ocr_text = ""

    # STEP 1: EXTRAKSI LOKAL DENGAN PYTHON REGEX FIRST (0.001 DETIK - ANTI TIMEOUT)
    nama_local = None
    nominal_local = None

    teks_gabungan = f"Caption: {caption}".strip()

    system_prompt = """Kamu adalah mesin Multimodal Named Entity Recognition (NER) khusus membaca resi transfer bank (BSI Mobile, BYOND by BSI, QRIS, dll).
Tugasmu membaca foto resi yang diberikan dan mengekstrak 3 data ke format JSON:
- nama: Nama Pengirim / Donatur (pada resi BSI Mobile cari 'Pengirim' atau 'Dari Rekening'; pada resi BYOND cari nama donatur pengirim di bawah nominal/rekening sumber). Jika tidak ditemukan, isi null.
- nominal: Angka nominal murni tanpa titik/koma/rupiah (misal 'Rp 50.000' -> '50000', 'Rp 84,000' -> '84000', 'Rp 100,000' -> '100000'). Jika tidak ditemukan, isi null.
- program: Kode program (ZKT-MAL, ZKT-PENGHASILAN, INF-RUTIN, DON-PALESTINA, atau UMUM).

KEMBALIKAN HANYA FORMAT JSON MURNI TANPA MARKDOWN.
Contoh:
{"nama": "YAFI HIDAYATULLAH", "nominal": "50000", "program": "INF-RUTIN"}"""

    prompt = f"{system_prompt}\n\nTeks Tambahan / Caption:\n'{teks_gabungan}'\nOutput JSON:"

    raw_text = _panggil_gemini_api(prompt, image_bytes=image_bytes, is_json=True, timeout=8)
    if not raw_text:
        return {"nama": nama_local, "nominal": nominal_local, "program": "UMUM"}

    try:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            raw_text = match.group(0)

        data = json.loads(raw_text) if raw_text else {}

        def _clean(val):
            if not val or str(val).lower() in {"null", "none", ""}:
                return None
            return str(val).strip()

        nama_res = _clean(data.get("nama")) or nama_local
        nominal_raw = _clean(data.get("nominal"))
        nominal_clean = nominal_local
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
        print(f"[Error Vision NER] {e}")
        return {"nama": nama_local, "nominal": nominal_local, "program": "UMUM"}


def ekstrak_konfirmasi_donasi(pesan_user: str) -> dict:
    """Mengekstrak data konfirmasi transfer dari pengguna menggunakan Gemini API."""
    system_prompt = """Kamu adalah mesin Named Entity Recognition (NER). 
Tugasmu mengekstrak 3 entitas konfirmasi dari pesan pengguna:
- nama: Nama donatur.
- nominal: Wajib angka murni (misal: '500 ribu' jadi '500000').
- program: Kategorikan ke salah satu ini (INF-RUTIN, ZKT-MAL, ZKT-PENGHASILAN, DON-PALESTINA, LAINNYA).
KEMBALIKAN HANYA FORMAT JSON MURNI.

CONTOH:
Pesan: "Min, saya barusan transfer 500rb untuk zakat penghasilan atas nama Budi"
Output JSON: {"nama": "Budi", "nominal": "500000", "program": "ZKT-PENGHASILAN"}"""

    prompt = f"{system_prompt}\n\nPesan: '{pesan_user}'\nOutput JSON:"
    raw_text = _panggil_gemini_api(prompt, is_json=True, timeout=7)
    if not raw_text:
        return {"nama": None, "nominal": None, "program": None}
    try:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            raw_text = match.group(0)
            
        data = json.loads(raw_text)
        return {
            "nama": data.get("nama"), 
            "nominal": data.get("nominal"), 
            "program": data.get("program")
        }
    except Exception as e:
        print(f"[Error NER Konfirmasi] {e}")
        return {"nama": None, "nominal": None, "program": None}
