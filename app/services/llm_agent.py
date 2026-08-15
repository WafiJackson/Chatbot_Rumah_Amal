import os
import json
import re
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

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
            "inlineData": {
                "mimeType": mime_type,
                "data": b64_img
            }
        })
        
    parts.append({"text": prompt})
    payload = {"contents": [{"parts": parts}]}
    if is_json:
        payload["generationConfig"] = {"response_mime_type": "application/json"}

    timeout_val = 35 if image_bytes else 15
    percobaan_maks = 2  # percobaan awal + 1x retry khusus timeout (hiccup jaringan sesaat cukup sering pada OCR resi)
    for percobaan in range(percobaan_maks):
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=timeout_val)
            if res.status_code == 200:
                data = res.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts_out = candidates[0].get("content", {}).get("parts", [])
                    if parts_out:
                        return parts_out[0].get("text", "").strip()
                return ""
            print(f"[Warning Gemini API Status {res.status_code}] {res.text[:200]}")
            return ""
        except requests.exceptions.Timeout as e:
            is_percobaan_terakhir = percobaan + 1 >= percobaan_maks
            print(f"[Error Gemini API Timeout, percobaan {percobaan + 1}/{percobaan_maks}] {e}")
            if is_percobaan_terakhir:
                return ""
        except Exception as e:
            print(f"[Error Gemini API] {e}")
            return ""
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


def get_intent(pesan: str) -> str:
    """Menggunakan Gemini 2.5 Flash untuk mengklasifikasikan intent dari pesan pengguna ke salah satu dari 47 intent resmi."""
    system_prompt = """Anda adalah mesin pengklasifikasi niat untuk customer service Rumah Amal Masjid Jamik USK.
Tugas Anda HANYA membalas dengan SATU KATA KUNCI dari daftar di bawah ini yang paling sesuai dengan pesan pengguna. JANGAN TULIS HAL LAIN SAMA SEKALI.

DAFTAR KATA KUNCI INTENT RESMI:
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
- tidak_diketahui (di luar konteks atau pertanyaan tidak relevan)"""

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
