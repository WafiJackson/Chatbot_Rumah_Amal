import os
import json
import re
import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434/api/generate")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen2.5:7b")


def ekstrak_data_ner(pesan_user: str) -> dict:
    """
    Mengekstrak data Nama, Pekerjaan, dan Nominal dari pesan bebas pengguna
    menggunakan LLM Named Entity Recognition (NER) dan mengembalikan JSON.
    """
    # 1. FEW-SHOT PROMPTING: Menambahkan contoh agar model 3B tidak berhalusinasi
    system_prompt = """Kamu adalah mesin Named Entity Recognition (NER). 
Tugasmu mengekstrak 3 entitas dari pesan pengguna: Nama, Pekerjaan, dan Nominal.
- Pekerjaan: Bisa berupa instansi, status (misal: mahasiswa), atau singkatan jabatan (misal: CEO, CTO, Direktur, Staff).
- Nominal: Wajib dibersihkan menjadi angka murni (misal: '8 ratus ribu' atau '800.000' menjadi '800000').
Jika ada entitas yang benar-benar tidak disebutkan, isi dengan null.
KEMBALIKAN HANYA FORMAT JSON MURNI TANPA TEKS PENJELASAN LAIN.

CONTOH 1:
Pesan: "Nama saya Budi, pegawai negeri, mau infak 50 ribu"
Output JSON: {"nama": "Budi", "pekerjaan": "pegawai negeri", "nominal": "50000"}

CONTOH 2:
Pesan: "Yafi, mahasiswa, 800000"
Output JSON: {"nama": "Yafi", "pekerjaan": "mahasiswa", "nominal": "800000"}

CONTOH 3:
Pesan: "Saya mau mendaftar infak rutin"
Output JSON: {"nama": null, "pekerjaan": null, "nominal": null}"""

    prompt = f"{system_prompt}\n\nPesan: '{pesan_user}'\nOutput JSON:"

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "format": "json",
        "stream": False
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=7)
        response.raise_for_status()
        raw_text = response.json().get("response", "").strip()

        # 2. REGEX ROBUST: Tangkap kurung kurawal secara paksa, abaikan teks pembuka/penutup
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            raw_text = match.group(0)
        else:
            print(f"[Warning NER] Gagal menemukan format JSON di balasan LLM: {raw_text}")

        data = json.loads(raw_text)

        nama = data.get("nama")
        pekerjaan = data.get("pekerjaan")
        nominal = data.get("nominal")

        def _clean_val(v):
            if v is None:
                return None
            v_str = str(v).strip()
            if v_str.lower() in {"null", "none", "", "nullnull"}:
                return None
            return v_str

        return {
            "nama": _clean_val(nama),
            "pekerjaan": _clean_val(pekerjaan),
            "nominal": _clean_val(nominal)
        }
    except Exception as e:
        print(f"[Error NER Parse] Gagal memproses: {e} | Raw Text: {raw_text if 'raw_text' in locals() else 'Request Error'}")
        return {"nama": None, "pekerjaan": None, "nominal": None}


def panggil_llm_teks(pesan_user: str, fakta_script: str, nama_pengirim: str = "Kak") -> str:
    """
    LLM Paraphraser (Tahap 1 Blueprint 2):
    Mimin (Virtual Assistant) menyusun ulang seluruh fakta menjadi balasan WhatsApp
    yang ramah, empatik, sopan, islami, dan luwes.
    """
    system_prompt = f"""Kamu adalah 'Mimin', asisten virtual resmi Rumah Amal Masjid Jamik USK.
Gaya bahasamu: Ramah, empatik, sopan, islami, dan luwes seperti manusia. Sapa pengirim dengan nama '{nama_pengirim}'.
Tugasmu: Saya akan memberikan [PESAN PENGGUNA] dan [FAKTA LEMBAGA]. Tulis ulang [FAKTA LEMBAGA] tersebut untuk menjawab [PESAN PENGGUNA] dengan gaya bahasamu yang natural.

ATURAN MUTLAK:
1. DILARANG mengubah, mengarang, atau menghilangkan NOMOR REKENING, ANGKA, NOMOR TELEPON, atau NAMA PROGRAM dari [FAKTA LEMBAGA].
2. Jangan menambahkan syarat atau aturan yang tidak tertulis di [FAKTA LEMBAGA].
3. Langsung berikan jawaban, jangan gunakan format JSON atau embel-embel 'Berikut jawabannya'."""

    prompt = f"{system_prompt}\n\n[PESAN PENGGUNA]: '{pesan_user}'\n[FAKTA LEMBAGA]: '{fakta_script}'\n\nJAWABAN MIMIN:"

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=7)
        response.raise_for_status()
        raw_text = response.json().get("response", "").strip()
        return raw_text
    except Exception as e:
        print(f"[Error LLM Paraphraser] {e}")
        return ""


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

    # =======================================================
    # 1. PENGECEKAN DATA HILANG (Omission Check)
    # Target: Angka berdurasi >= 4 karakter (3.00, 08.00, 7099400409) dan URL
    # =======================================================
    angka_fakta = re.findall(r'\b\d[\d\.\-]{2,}\d\b', fakta_low)
    for angka in angka_fakta:
        angka_bersih = angka.replace("-", "")
        # Periksa apakah angka (atau versi tanpa strip-nya) ada di jawaban LLM
        if angka not in jawaban_low and angka_bersih not in jawaban_low.replace("-", ""):
            print(f"[Guardrail Fail] Angka krusial '{angka}' dihilangkan oleh LLM!")
            return False

    url_fakta = re.findall(r'\b[a-z0-9\-]+\.[a-z]{2,}(?:\.[a-z]{2,})?\b', fakta_low)
    for url in url_fakta:
        if url not in jawaban_low:
            print(f"[Guardrail Fail] Tautan '{url}' dihilangkan oleh LLM!")
            return False

    # =======================================================
    # 2. PENGECEKAN DATA PALSU (Hallucination Check / False Positives)
    # Target: Mencegah LLM menambahkan nomor rekening/HP palsu (>= 6 digit) atau URL palsu
    # =======================================================
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

    # =======================================================
    # 3. PENGECEKAN KATA KUNCI SPESIFIK (Aturan Konteks Khusus)
    # =======================================================
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
    """Menggunakan LLM untuk mengklasifikasikan intent dari pesan pengguna ke salah satu dari 47 intent resmi."""
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

    prompt = f"{system_prompt}\n\nPesan Pengguna: '{pesan}'\nBalasan:"

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=5)
        response.raise_for_status()
        data = response.json()
        hasil_intent = data.get("response", "").strip().lower()
        first_word = hasil_intent.split()[0] if hasil_intent else "tidak_diketahui"
        return first_word.strip(" .,\"'\n")
    except Exception as e:
        print(f"[Error Ollama get_intent] {e}")
        return "tidak_diketahui"


def ekstrak_resi_vision(image_bytes: bytes, caption: str = "") -> dict:
    """
    Pipeline Vision NER untuk resi transfer bank (BSI Mobile, BYOND by BSI, QRIS, dll):
    1. Melakukan OCR pada image_bytes via pytesseract/easyocr.
    2. Auto-detect lokasi tesseract.exe jika di OS Windows.
    3. Mengirimkan teks mentah OCR + caption ke LLM Qwen2.5 untuk di-parse ke format JSON terstruktur.
    """
    raw_ocr_text = ""

    if image_bytes:
        try:
            from PIL import Image
            import io
            image = Image.open(io.BytesIO(image_bytes))

            try:
                import pytesseract
                import os
                if os.name == 'nt':
                    tess_paths = [
                        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
                        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
                        os.path.expanduser(r'~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe')
                    ]
                    for tpath in tess_paths:
                        if os.path.exists(tpath):
                            pytesseract.pytesseract.tesseract_cmd = tpath
                            break
                raw_ocr_text = pytesseract.image_to_string(image)
            except Exception as e_tess:
                try:
                    import easyocr
                    reader = easyocr.Reader(['id', 'en'], gpu=False)
                    results = reader.readtext(image_bytes, detail=0)
                    raw_ocr_text = " ".join(results)
                except Exception as e_easy:
                    print(f"[OCR Notice] OCR engine fallback to raw caption: {e_easy}")
        except Exception as e_pil:
            print(f"[Image Read Notice] {e_pil}")

    # =====================================================================
    # STEP 1: EXTRAKSI LOKAL DENGAN PYTHON REGEX FIRST (0.001 DETIK - ANTI TIMEOUT)
    # =====================================================================
    nama_local = None
    nominal_local = None

    if raw_ocr_text:
        # 1. Pengecekan angka nominal berformat rupiah (misal 50.000, 58.181, 84,000, 100,000, 50000)
        match_nom = re.search(r"(?:Rp|Jumlah|Nominal|Total|Biaya)[^\d]*?([\d\.\,]{4,})", raw_ocr_text, re.IGNORECASE | re.DOTALL)
        if match_nom:
            digits = re.sub(r"[^\d]", "", match_nom.group(1))
            if digits and int(digits) >= 1000:
                nominal_local = digits

        if not nominal_local:
            match_fmt = re.search(r"\b(\d{1,3}(?:[\.\,]\d{3})+)\b", raw_ocr_text)
            if match_fmt:
                digits = re.sub(r"[^\d]", "", match_fmt.group(1))
                if digits and int(digits) >= 1000:
                    nominal_local = digits

        # 2. Pengecekan presisi nama pengirim/donatur pada resi BSI Mobile & BYOND by BSI
        # Standard BSI Mobile: Pengirim: <Nama>
        match_bsi = re.search(r'Pengirim:\s*([A-Za-z\s]{3,35})', raw_ocr_text, re.IGNORECASE)
        if match_bsi:
            nama_local = match_bsi.group(1).split('\n')[0].strip()

        # BYOND app: Nama donatur pada Rekening Sumber (di atas BSI = #... atau Bank Syariah Indonesia)
        if not nama_local:
            blocks = re.findall(r'([A-Za-z\s]{3,35})\n(?:BSI\s*=|Bank\s+Syariah\s+Indonesia)', raw_ocr_text, re.IGNORECASE)
            if blocks:
                valid_names = []
                for b in blocks:
                    name = b.strip()
                    if name and not any(k in name.lower() for k in ['total', 'nominal', 'biaya', 'admin', 'penerima', 'merchant', 'lokasi', 'rekening', 'sumber']):
                        valid_names.append(name)
                if valid_names:
                    nama_local = valid_names[-1]

        # Fallback: Cari baris setelah 'Rekening Sumber' dalam teks OCR
        if not nama_local:
            lines = [l.strip() for l in raw_ocr_text.split('\n') if l.strip()]
            for i, line in enumerate(lines):
                if 'rekening sumber' in line.lower():
                    for j in range(i+1, min(i+10, len(lines))):
                        cand = lines[j]
                        if cand and not any(k in cand.lower() for k in ['rekening', 'sumber', 'merchant', 'lokasi', 'nominal', 'total', 'biaya', 'admin', 'status', 'berhasil', 'bsi', 'bank', 'syariah']):
                            if len(cand) >= 3 and not cand.isdigit():
                                nama_local = cand
                                break
                    if nama_local:
                        break


    teks_gabungan = f"{raw_ocr_text}\nCaption: {caption}".strip()

    # Jika Regex lokal sudah berhasil mengekstrak nominal, langsung kembalikan hasil (0.001s, tanpa panggil Ollama!)
    if nominal_local:
        return {
            "nama": nama_local,
            "nominal": nominal_local,
            "program": "UMUM"
        }

    system_prompt = """Kamu adalah mesin Named Entity Recognition (NER) khusus membaca resi transfer bank (seperti BSI Mobile dan aplikasi BYOND by BSI).
Tugasmu mengekstrak 3 data dari teks resi / caption:
- nama: Nama Pengirim / Donatur (pada resi BSI Mobile cari 'Pengirim' atau 'Dari Rekening'; pada resi BYOND cari nama donatur pengirim di bawah nominal/rekening sumber). Jika tidak ditemukan, isi null.
- nominal: Angka nominal murni tanpa titik/koma/rupiah (misal 'Rp 50.000' -> '50000', 'Rp 84,000' -> '84000', 'Rp 100,000' -> '100000'). Jika tidak ditemukan, isi null.
- program: Kode program (ZKT-MAL, ZKT-PENGHASILAN, INF-RUTIN, DON-PALESTINA, atau UMUM).

Kembalikan HANYA format JSON murni tanpa markdown.
Contoh:
{"nama": "YAFI HIDAYATULLAH", "nominal": "50000", "program": "INF-RUTIN"}"""

    prompt = f"{system_prompt}\n\nTeks Resi:\n'{teks_gabungan}'\nOutput JSON:"

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "format": "json",
        "stream": False
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=7)
        response.raise_for_status()
        raw_text = response.json().get("response", "").strip()

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
    """Mengekstrak data konfirmasi transfer dari pengguna."""
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
    
    payload = {"model": MODEL_NAME, "prompt": prompt, "format": "json", "stream": False}
    
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=7)
        response.raise_for_status()
        raw_text = response.json().get("response", "").strip()
        
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

