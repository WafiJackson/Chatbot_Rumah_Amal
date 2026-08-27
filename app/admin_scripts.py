import re
import unicodedata
import random
from services.program_manager import (
    extract_program_keyword,
    format_program_response,
    get_program_info,
    get_program_list,
)
from services import llm_agent


def _normalisasi_teks(teks: str) -> str:
    teks = (teks or "").lower().strip()
    teks = unicodedata.normalize("NFKD", teks).encode("ascii", "ignore").decode("ascii")
    teks = re.sub(r"[^a-z0-9\s]", " ", teks)
    teks = re.sub(r"\s+", " ", teks).strip()
    return teks


def _ada_salah_satu(teks: str, daftar_kata: list[str]) -> bool:
    return any(kata in teks for kata in daftar_kata)


def _ada_semua(teks: str, daftar_kata: list[str]) -> bool:
    return all(kata in teks for kata in daftar_kata)

SAPAAAN_KATA = [
    "halo",
    "hai",
    "hello",
    "hi",
    "assalamualaikum",
    "assalamu alaikum",
    "pagi",
    "siang",
    "sore",
    "malam",
    "met",
    "permisi",
    "min",
    "p",
    "ping",
    "p!",
    "ping!",
    "oi",
    "woi",
    "lek",
    "oi lek",
    "bro",
    "sis",
    "cuy",
    "hei",
    "we",
    "wae",
    "bang",
    "kak",
    "admin",
]


def _is_sapaan(teks_norm: str) -> bool:
    """
    Sapaan sering datang dalam bentuk gabungan seperti:
    - "halo min"
    - "hai kak"
    - "assalamualaikum admin"
    - "oi lek" / "p" / "ping"
    Jika ada pertanyaan tambahan setelah sapaan (misal: "assalamualaikum kak, mau tanya norek"),
    maka fungsi ini mengembalikan False agar intent pertanyaan utama dapat terdeteksi.
    """
    if not teks_norm:
        return False

    tokens = set(teks_norm.split())
    if any(k in tokens for k in {"p", "ping", "p!", "ping!", "oi", "woi", "lek", "bro", "sis", "cuy", "hei"}):
        if not any(k in tokens for k in ["beasiswa", "ukt", "bpra", "pinjam", "pintas", "alamat", "rekening", "donasi", "zakat"]):
            return True

    # jika diawali salah satu kata sapaan dan sisanya hanya panggilan umum
    if any(teks_norm.startswith(k) for k in ["halo", "hai", "hello", "hi", "assalamualaikum", "assalamu alaikum", "permisi", "oi", "woi", "hei"]):
        sisa = teks_norm.replace("assalamualaikum", "").replace("assalamu alaikum", "")
        sisa = sisa.replace("halo", "").replace("hai", "").replace("hello", "").replace("hi", "").replace("permisi", "").replace("oi", "").replace("woi", "").replace("hei", "")
        sisa = sisa.strip()
        if not sisa:
            return True
        sisa_tokens = sisa.split()
        if all(k in ["min", "admin", "kak", "bang", "mba", "mbak", "buk", "bu", "pak", "lek", "bro", "sis", "cuy", "lek!"] for k in sisa_tokens):
            return True

    # sapaan pendek (<= 2 kata) yang mengandung kata sapaan (pencocokan kata utuh)
    if len(tokens) <= 2 and any(k in tokens for k in SAPAAAN_KATA):
        if not any(k in tokens for k in ["beasiswa", "ukt", "bpra", "pinjam", "pintas", "alamat", "rekening", "donasi", "zakat"]):
            return True

    return False


QA_SCRIPT = {
    # Sapaan & handoff admin
    "sapaan": (
        "Assalamu'alaikum {sapaan_panggilan}! Selamat datang di layanan informasi Rumah Amal Masjid Jamik USK.\n\n"
        "Ada yang bisa kami bantu? Contoh pertanyaan:\n"
        "1. \"Program apa saja?\"\n"
        "2. \"Ingin berdonasi?\"\n"
        "3. \"Alamat kantor?\"\n"
        "4. \"Cek riwayat transaksi\"\n"
        "5. \"Hubungi admin\""
    ),
    "handoff_admin_prompt": (
        "Untuk pengajuan bantuan dana atau program PINTAS, proses validasi harus dilakukan langsung bersama admin.\n\n"
        "Apakah Anda ingin disambungkan ke admin sekarang? (Balas *Ya* atau *Batal*)"
    ),
    "handoff_admin_waiting": "Silakan balas *Ya* jika ingin disambungkan ke admin, atau *Batal* jika tidak jadi.",
    "handoff_admin_success": "Tunggu sebentar ya, pesan Anda sedang diteruskan ke admin. Staf kami akan segera membalas chat ini.",
    "handoff_admin_cancel": "Penyambungan ke admin dibatalkan. Silakan kirim pertanyaan lain jika masih ada yang ingin ditanyakan.",

    # Bagian I: Profil dan informasi umum
    "profil_lembaga": (
        "Rumah Amal Masjid Jamik USK adalah Lembaga Amil Zakat (LAZ) resmi di lingkungan kampus Universitas Syiah Kuala (USK) "
        "yang mengelola dan mendistribusikan dana zakat, infak, sedekah (ZIS), serta dana sosial lainnya untuk membantu civitas akademika "
        "dan masyarakat dhuafa."
    ),
    "info_alamat": (
        "Kantor operasionalnya terletak di Lantai 1 Masjid Jamik Universitas Syiah Kuala, Jalan T. Nyak Arief Kompleks Pelajar Mahasiswa "
        "(Kopelma) Darussalam, Kecamatan Syiah Kuala, Kota Banda Aceh."
    ),
    "info_jam_kerja": (
        "Pelayanan dibuka setiap hari kerja, Senin sampai Jumat, mulai pukul 08.00 WIB hingga 16.30 WIB "
        "(Sabtu, Minggu, dan hari libur nasional tutup)."
    ),
    "visi_lembaga": (
        "Menjadi LembagaAmil Zakat dan pemberdayaan ekonomi umat yang inovatif, responsif, profesional dan terkemuka untuk kemaslahatan bersama yang berbasis masjid."
    ),
    "misi_lembaga": (
        "1. Menyediakan sistem dan layanan yang memudahkan para muzakki atau donatur dalam menunaikan zakat, infaq, shadaqah, maupun wakaf dengan sebaik-baiknya.\n"
        "2. Menjadikan masjid sebagai pusat pemberdayaan ekonomi umat.\n"
        "3. Mendayagunakan dana zakat, infaq shadaqah maupun wakaf melalui program-program yang terasa manfaatnya.\n"
        "4. Mengangkat martabat mustahik, dan membahagiakan muzakki dan donatur."
    ),
    "motto_lembaga": "Motto utamanya adalah \"Memberdayakan Mengangkat Martabat\".",
    "sasaran_mustahik": (
        "Sasaran utamanya meliputi mahasiswa aktif USK yang kurang mampu, tenaga kependidikan/kontrak berpenghasilan rendah, "
        "serta masyarakat dhuafa di sekitar lingkungan kampus USK."
    ),
    "direktur_lembaga": "Lembaga ini dipimpin oleh Tedy Kurniawan Bakri, M.Farm., Apt.",
    "status_resmi_usk": (
        "Ya, lembaga ini merupakan lembaga resmi di bawah supervisi Universitas Syiah Kuala yang berkolaborasi dengan "
        "Badan Kemakmuran Masjid (BKM) Jamik USK."
    ),

    # Bagian II: ZIS dan donasi
    "cara_donasi": (
        "Anda dapat menyalurkan donasi secara nontunai dengan melakukan transfer ke rekening resmi atau datang langsung "
        "ke kantor operasional untuk menyetor tunai."
    ),
    "info_rekening": (
        "Rekening BSI dengan nomor rekening 7099400409 atas nama Rumah Amal Mesjid Unsyiah dengan mencantumkan "
        "keterangan zakat/infak.donasi."
    ),
    "info_qris": (
        "Ya, Rumah Amal USK menyediakan kode QRIS resmi yang dapat dipindai menggunakan mobile banking atau dompet digital (e-wallet)."
    ),
    "laporan_penyaluran": (
        "Ya, Rumah Amal Masjid Jamik USK transparan dalam penyaluran dana dan memberikan laporan rutin secara berkala kepada para muzakki "
        "(donatur) atau mempublikasikannya melalui media resmi."
    ),
    "info_infak_rutin": (
        "Program komunitas sedekah/infak rutin untuk meningkatkan konsistensi (istiqamah) dalam bersedekah bulanan demi membantu sesama."
    ),
    "daftar_infak_rutin": (
        "Alhamdulillah, terima kasih atas niat baiknya {sapaan_panggilan}! 🙏\n"
        "Untuk mendaftar program Infak Rutin, silakan salin, isi, dan kirimkan kembali formulir di bawah ini:\n\n"
        "*FORMULIR INFAK RUTIN*\n"
        "Nama : \n"
        "Instansi/Pekerjaan : \n"
        "Nominal Komitmen : "
    ),

    "zakat_pajak": (
        "Ya, berzakat di lembaga resmi seperti Rumah Amal Masjid Jamik USK memberikan bukti setor zakat resmi yang dapat digunakan sebagai "
        "pengurang penghasilan kena pajak."
    ),
    "jenis_zakat": (
        "Rumah Amal Masjid Jamik USK melayani Zakat Penghasilan (Profesi), Zakat Maal (Harta), Zakat Perdagangan, hingga Zakat Fitrah saat bulan Ramadan."
    ),
    "donatur_umum": (
        "Sangat diperbolehkan. Rumah Amal Masjid Jamik USK menerima titipan dana ZIS dari masyarakat umum, alumni, instansi swasta, maupun instansi pemerintah."
    ),
    "kalkulator_zakat": (
        "Ya, situs resmi Rumah Amal Masjid Jamik USK menyediakan fitur kalkulator zakat untuk memudahkan muzakki menghitung kewajiban zakatnya. "
        "Berikut alamat situs resminya: rumahamal.usk.ac.id"
    ),
    "info_kontak": "Hubungi WhatsApp resmi di nomor 0811-6888-123.",

    # Bagian III: Program beasiswa dan bantuan mahasiswa
    "info_program": (
        "Tersedia beberapa program bantuan atau beasiswa seperti Beasiswa Pendidikan Rumah Amal Uang Kuliah Tunggal (BPRA-UKT), "
        "Beasiswa Biaya Hidup, Beasiswa Orang Tua Asuh, Beasiswa Palestina, Bantuan Peduli Sigra, Bantuan Nasi Bungkus, Pinjaman Tanpa Syarat, "
        "serta bantuan lainnya. Untuk program lengkap dapat dilihat di situs resmi: rumahamal.usk.ac.id"
    ),
    "info_bpra_ukt": (
        "Program Beasiswa Pendidikan Rumah Amal untuk membiayai atau meringankan tagihan Uang Kuliah Tunggal (UKT) mahasiswa Universitas Syiah Kuala "
        "yang berasal dari keluarga kurang mampu agar tidak putus kuliah."
    ),
    "syarat_beasiswa_umum": (
        "Secara umum, pendaftar adalah mahasiswa aktif D3/S1 USK dari keluarga kurang mampu, tidak merokok, tidak berpacaran, "
        "tidak terlibat judi online, dan tidak sedang menerima beasiswa rutin lain."
    ),
    "alasan_aturan_akhlak": (
        "Aturan ini diterapkan untuk memastikan dana umat yang disalurkan tepat sasaran kepada penerima manfaat yang berakhlak baik "
        "serta memiliki komitmen moral tinggi."
    ),
    "diskualifikasi_judol": (
        "Ya, keterlibatan dalam judi online atau tindakan melanggar hukum/syariat Islam lainnya akan membatalkan status kepesertaan beasiswa secara mutlak."
    ),
    "cara_daftar_beasiswa": (
        "Pendaftaran dilakukan secara online melalui pengisian formulir dan pengunggahan berkas pada tautan pendaftaran resmi yang disediakan "
        "di website Rumah Amal USK saat periode pendaftaran dibuka."
    ),
    "dokumen_beasiswa": (
        "Surat Permohonan, Surat Rekomendasi, Surat Pernyataan, Pas Foto, KTP, KTM, Surat Keterangan Tidak Mampu (SKTM) dari Desa, "
        "Transkrip Nilai/KHS terakhir, Slip Gaji/Keterangan Penghasilan Orang Tua, serta foto rumah."
    ),
    "semester_beasiswa": (
        "Beasiswa dari Rumah Amal diprioritaskan bagi mahasiswa yang sudah berjalan minimal semester 2 dan maksimal semester 8."
    ),
    "syarat_ipk": (
        "Umumnya batas minimal IPK adalah 3.00 (menyesuaikan jenis beasiswa), sebagai bentuk tanggung jawab akademik penerima manfaat."
    ),
    "double_funding": (
        "Tidak boleh (double funding). Setiap pendaftar tidak sedang menerima beasiswa rutin dari lembaga atau instansi lain."
    ),
    "peduli_sigra": (
        "Program respon cepat dan bantuan insidental kemanusiaan yang diberikan kepada civitas akademika USK yang mengalami musibah atau kondisi darurat."
    ),
    "bantuan_bencana_mahasiswa": (
        "Memberikan bantuan dana darurat tunai (misal: evakuasi kebakaran asrama), kebutuhan logistik harian, hingga dukungan dana pengadaan laptop baru "
        "untuk kelancaran kuliah."
    ),
    "seleksi_wawancara": (
        "Ya, setelah seleksi administrasi, pendaftar yang lolos wajib mengikuti tahapan wawancara untuk verifikasi komitmen dan kondisi ekonomi."
    ),
    "survei_rumah": (
        "Ya, tim Rumah Amal USK melakukan kunjungan lapangan (field survey) secara acak maupun menyeluruh guna memastikan keabsahan data kemiskinan yang diajukan."
    ),
    "kewajiban_penerima": (
        "Penerima manfaat wajib mengikuti program pembinaan karakter, kegiatan keagamaan di Masjid Jamik, serta berkontribusi dalam aksi sosial "
        "atau kerelawanan yang diadakan Rumah Amal."
    ),
    "periode_beasiswa": (
        "Pembukaan pendaftaran umumnya dibuka sebanyak 2 kali dalam setahun, menyesuaikan kalender akademik perguruan tinggi menjelang pembayaran UKT tiap semester baru."
    ),

    # Bagian IV: Kemitraan, pemberdayaan, dan akuntabilitas
    "modal_usaha": (
        "Ya, selain bantuan konsumtif, Rumah Amal memiliki Program Pemberdayaan Ekonomi Masyarakat Dhuafa (P2EMD) berupa pemberian modal usaha produktif "
        "bagi pelaku UMKM dari keluarga kurang mampu."
    ),
    "pembinaan_umkm": (
        "Pembinaan meliputi pelatihan manajemen keuangan syariah, pendampingan pemasaran produk, hingga bantuan sertifikasi halal."
    ),
    "mitra_eksternal": (
        "Rumah Amal Masjid Jamik USK bermitra dengan berbagai pihak, termasuk instansi pemerintahan, sektor swasta, dan tim Corporate Social Responsibility "
        "(CSR) perusahaan seperti PT Solusi Bangun Andalas (SBA)."
    ),
    "tujuan_kolaborasi_csr": (
        "Untuk melakukan diskusi, pendampingan inovasi, serta eksekusi bersama program-program CSR yang mampu menghadirkan dampak positif "
        "berkelanjutan bagi kesejahteraan masyarakat."
    ),
    "laporan_publik": "Laporan tahunan dapat diunduh langsung via website resmi rumahamal.usk.ac.id",

    # Bagian V: Ramadan dan penyaluran lainnya
    "takjil_ramadan": (
        "Ya, Rumah Amal bekerja sama dengan BKM Masjid Jamik USK mengelola dapur umum untuk mendistribusikan ribuan paket berbuka puasa gratis "
        "setiap harinya bagi mahasiswa dan jamaah."
    ),
    "apresiasi_fisabilillah": (
        "Program tahunan berupa pembagian paket sembako dan santunan hari raya menjelang Idul Fitri bagi para tenaga kebersihan, satpam kampus, "
        "serta lansia dhuafa di lingkar kampus."
    ),
    "qurban": (
        "Rumah Amal menerima titipan hewan/donasi kurban, mengelola pemotongan, dan menyalurkan kupon daging kurban secara merata kepada masyarakat miskin "
        "serta mahasiswa kurang mampu."
    ),
    "posko_bencana": (
        "Ya, Rumah Amal sering menggalang dana kemanusiaan khusus untuk solidaritas global (seperti bantuan Palestina) maupun bencana alam nasional "
        "(gempa, banjir, dll)."
    ),
    "bantuan_siswa": (
        "Program prioritas utama adalah mahasiswa USK, namun dalam beberapa skema bantuan sosial kemasyarakatan, anak yatim/piatu prasejahtera "
        "di lingkungan sekitar kampus juga mendapat santunan."
    ),
    "kritik_saran": (
        "Saran dapat dikirimkan secara tertulis via email resmi lembaga, maupun pesan langsung ke media sosial resmi."
    ),

    # Balasan pesan doa
    "doa_zakat_mal": (
        "Semoga Allah memberikan pahala kepada Bapak/Ibu atas apa saja yang Bapak/Ibu berikan, memberikan keberkahan apa saja yang masih tersisa, "
        "dan semoga Allah mensucikannya.\n\n"
        "\"Ya Allah berikanlah ganti pada orang yang dermawan, Mudahkanlah segala urusannya serta keluarganya dan berikanlah kebahagian untuknya dan keluarganya.\"\n\n"
        "Alhamdulillah\n\n"
        "Terimakasih Bapak/Ibu\n\n"
        "Zakat Mal atas nama Bapak/Ibu sudah kami terima dan InsyaAllah akan disalurkan kepada penerima yang berhak.\n\n"
        "Semoga Bapak/Ibu dan keluarga senantiasa diberikan kesehatan, kemudahan dan keberkahan dalam rezeki, dan dijauhkan dari segala marabahaya. "
        "Semoga zakat ini menjadi amal jariyah yang akan menghantarkan ke dalam surga.\n\n"
        "Aamiin Yaa Rabbal 'Aalamiin.\n\n"
        "Salam kami,\n\n"
        "Rumah Amal Masjid Jamik\n\n"
        "Universitas Syiah Kuala\n\n"
        "#rumahamalusk"
    ),
    "doa_zakat_penghasilan": (
        "Semoga Allah memberikan pahala kepada Bapak/Ibu atas apa saja yang Bapak/Ibu berikan, memberikan keberkahan apa saja yang masih tersisa, "
        "dan semoga Allah mensucikannya.\n\n"
        "\"Ya Allah berikanlah ganti pada orang yang dermawan, Mudahkanlah segala urusannya serta keluarganya dan berikanlah kebahagian untuknya dan keluarganya.\"\n\n"
        "Alhamdulillah\n\n"
        "Terimakasih Bapak/Ibu\n\n"
        "Zakat atas nama Bapak/Ibu sudah kami terima dan InsyaAllah akan disalurkan kepada penerima yang berhak.\n\n"
        "Semoga Bapak/Ibu dan keluarga senantiasa diberikan kesehatan, kemudahan dan keberkahan dalam rezeki, dan dijauhkan dari segala marabahaya. "
        "Semoga zakat ini menjadi amal jariyah yang akan menghantarkan ke dalam surga.\n\n"
        "Aamiin Yaa Rabbal 'Aalamiin.\n\n"
        "Salam kami,\n\n"
        "Rumah Amal Masjid Jamik\n\n"
        "Universitas Syiah Kuala\n\n"
        "#rumahamalusk"
    ),
    "doa_infak": (
        "Ya Allah berikanlah ganti pada orang yang dermawan, Mudahkanlah segala urusannya serta keluarganya dan berikanlah kebahagiaan untuknya dan keluarganya\"\n\n"
        "Alhamdulillah, Terimakasih Bapak/Ibu\n\n"
        "*Donasi/Sedekah/infaq* dari Bapak/Ibu sudah kami terima dan InsyaAllah akan disalurkan kepada penerima manfaat yang berhak.\n\n"
        "Semoga Bapak/Ibu dan keluarga senantiasa diberikan kesehatan, kemudahan dan keberkahan dalam rezeki, dan dijauhkan dari segala marabahaya. "
        "Semoga Donasi/Sedekah/infaq ini menjadi amal jariyah yang akan menghantarkan ke dalam surga.\n\n"
        "Aamiin Yaa Rabbal 'Aalamiin.\n\n"
        "Salam kami,\n\n"
        "Rumah Amal Masjid Jamik\n\n"
        "Universitas Syiah Kuala\n\n"
        "#rumahamalusk"
    ),

    # Jaring pengaman (Jawaban Ramah OOT)
    "tidak_diketahui": (
        "Wah, Mimin kurang paham nih kalau mengenai hal itu 🙏\n\n"
        "Mimin fokus membantu seputar *Zakat, Infak, Sedekah,* serta *Program Beasiswa USK* ya {sapaan_panggilan}. Ada yang bisa Mimin bantu terkait program Rumah Amal USK hari ini? 😊\n\n"
        "----------------------------------------\n"
        "📌 *Pilihan Cepat:*\n"
        "• Ketik *1* - Katalog Program & Beasiswa\n"
        "• Ketik *2* - Panduan Berdonasi\n"
        "• Ketik *0* - Kembali ke Menu Utama"
    ),
}

# KAMUS_PENDAFTARAN (di susun_balasan/klasifikasi_pesan) bisa menghasilkan
# intent "daftar_zakat_mal" / "daftar_zakat_penghasilan" / "daftar_peduli_
# palestina" saat pengguna menyebut niat mendaftar/membayar secara spesifik
# (mis. "zakat maal", "daftar donasi palestina") - sebelumnya QA_SCRIPT tidak
# punya balasan untuk ketiganya sehingga ambil_balasan() diam-diam jatuh ke
# "tidak_diketahui" padahal niat penggunanya sudah dikenali dengan benar.
# Dipetakan ke jalur setor yang sama seperti kasus "bayar zakat" umum.
QA_SCRIPT["daftar_zakat_mal"] = QA_SCRIPT["cara_donasi"] + "\n\n" + QA_SCRIPT["info_rekening"]
QA_SCRIPT["daftar_zakat_penghasilan"] = QA_SCRIPT["cara_donasi"] + "\n\n" + QA_SCRIPT["info_rekening"]
QA_SCRIPT["daftar_peduli_palestina"] = QA_SCRIPT["cara_donasi"] + "\n\n" + QA_SCRIPT["info_rekening"]

# klasifikasi_pesan() bisa mengembalikan "handoff_admin" lewat pencocokan kata
# kunci (pinjam/pintas/hubungi admin/dst) - sebelumnya tidak ada balasannya
# sendiri di QA_SCRIPT, jatuh ke "tidak_diketahui".
QA_SCRIPT["handoff_admin"] = QA_SCRIPT["handoff_admin_prompt"]

# get_intent() (fallback klasifikasi via Gemini) bisa mengembalikan 3 intent
# ini untuk kalimat bebas yang tidak kena kata kunci cepat manapun -
# sebelumnya juga tidak ada balasannya, diam-diam ke-guard jadi
# "tidak_diketahui" di klasifikasi_pesan() walau niatnya sudah benar dikenali.
QA_SCRIPT["ingin_donasi"] = QA_SCRIPT["cara_donasi"] + "\n\n" + QA_SCRIPT["info_rekening"]
QA_SCRIPT["minta_bantuan_pintas"] = QA_SCRIPT["handoff_admin_prompt"]
# "konfirmasi_donasi" sengaja TIDAK memakai template "sudah tercatat" seperti
# doa_infak/doa_zakat_* - intent ini cuma hasil klasifikasi teks bebas tanpa
# ekstraksi nama/nominal, jadi belum ada apa pun yang benar-benar tersimpan.
# Mengaku "sudah tercatat" di sini akan menyesatkan donatur.
QA_SCRIPT["konfirmasi_donasi"] = (
    "Alhamdulillah, terima kasih atas kepercayaannya! 🙏 Supaya donasinya bisa Mimin catat dengan tepat, "
    "boleh kirimkan foto bukti transfer, atau sebutkan Nama, Nominal, dan Program donasinya secara lengkap ya."
)


def _dapatkan_doa_spesifik(
    nama_program: str = "Donasi", nama_donatur: str = "Bapak/Ibu", nominal_fmt: str = "",
    program_diketahui: bool = True,
) -> str:
    """
    Generator Doa Syar'i Acak (Random Doa Generator):
    Menghasilkan variasi doa syar'i berbahasa Arab + terjemahan yang berganti-ganti secara acak
    agar balasan terima kasih donasi tidak monoton jika donatur berdonasi berkali-kali.

    program_diketahui=False dipakai saat donatur cuma mengirim resi/konfirmasi
    tanpa pernah menyebut ingin berdonasi untuk program apa (mis. langsung
    kirim foto resi tanpa basa-basi) - balasan TIDAK menyebut nama program
    sama sekali (diganti kalimat "bukti pembayaran ... telah tercatat") supaya
    tidak mengarang seolah-olah sistem tahu peruntukan donasinya.
    """
    nom_str = f" sebesar *Rp {nominal_fmt}*" if nominal_fmt else ""
    sapaan = nama_donatur if nama_donatur else "Bapak/Ibu"

    if program_diketahui:
        label = "Donasi/Penyaluran"
        keterangan_program = f" untuk program *{nama_program}*"
    else:
        label = "bukti pembayaran"
        keterangan_program = ""

    variasi_doa = [
        # Variasi 1: Doa Penyucian Harta & Pahala
        (
            f"Alhamdulillah! 🙏 {label}{nom_str} dari *{sapaan}*{keterangan_program} telah kami terima dengan baik.\n\n"
            f"🤲 *Doa untuk {sapaan} & Keluarga:*\n"
            f"\"آجَرَكَ اللهُ فِيْمَا أَعْطَيْتَ، وَبَارَكَ فِيْمَا أَبْقَيْتَ وَجَعَلَهُ لَكَ طَهُوْرًا\"\n"
            f"_(\"Semoga Allah memberikan pahala atas apa yang {sapaan} berikan, memberkahi harta yang tersisa, dan menyucikan jiwa serta rezeki keluarga.\")_\n\n"
            f"InsyaAllah donasi ini segera disalurkan kepada para penerima manfaat yang berhak. Jazakallahu Khairan atas kepercayaannya bersama Rumah Amal USK! ✨"
        ),
        # Variasi 2: Doa Keberkahan Kelipatan Rezeki
        (
            f"Alhamdulillah, masyaAllah! 🌟 {label}{nom_str} dari *{sapaan}*{keterangan_program} telah tercatat di sistem kami.\n\n"
            f"🤲 *Doa Keberkahan Rezeki:*\n"
            f"\"اللَّهُمَّ أَعْطِ مُنْفِقًا خَلَفًا\"\n"
            f"_(\"Ya Allah, berikanlah ganti keberkahan yang berlipat ganda bagi {sapaan} yang telah berderma, serta mudahkanlah seluruh urusan keluarga.\")_\n\n"
            f"Aamiin Yaa Rabbal 'Aalamiin. Terima kasih banyak {sapaan}! 🙏"
        ),
        # Variasi 3: Doa Kemudahan Urusan & Kebahagiaan
        (
            f"Alhamdulillah, terima kasih banyak {sapaan}! 🙏 {label}{nom_str}{keterangan_program} telah kami terima.\n\n"
            f"🤲 *Doa Kemudahan & Kebahagiaan:*\n"
            f"\"Ya Allah, berikanlah ganti bagi hamba-Mu yang dermawan ini. Mudahkanlah segala urusannya serta keluarganya, dan berikanlah kebahagiaan sejati di dunia dan akhirat.\"\n\n"
            f"Semoga donasi ini menjadi amal jariyah yang terus mengalir pahalanya. Aamiin Yaa Rabbal 'Aalamiin. ✨"
        ),
        # Variasi 4: Doa Perlindungan & Kesucian Rezeki
        (
            f"Alhamdulillah! {label}{nom_str} dari *{sapaan}*{keterangan_program} sudah kami terima dan InsyaAllah akan segera disalurkan.\n\n"
            f"🤲 *Doa Perlindungan & Keberkahan:*\n"
            f"Semoga {sapaan} dan keluarga senantiasa diberikan kesehatan, kemudahan, keberkahan rezeki, dan dijauhkan dari segala marabahaya.\n\n"
            f"Jazakallahu Khairan atas kepedulian bersama Rumah Amal Masjid Jamik USK! 🙏"
        )
    ]
    return random.choice(variasi_doa)


PROGRAM_UMUM_TERSEBUT = [
    "palestina",
    "orang tua asuh",
    "biaya hidup",
    "nasi bungkus",
    "sigra",
]


def klasifikasi_pesan(pesan: str, has_media: bool = False) -> str:
    teks = _normalisasi_teks(pesan)

    if not teks and has_media:
        return "doa_infak"

    # 1. Konfirmasi transfer / bukti donasi
    is_konfirmasi = has_media or _ada_salah_satu(
        teks,
        [
            "bukti transfer",
            "sudah transfer",
            "barusan transfer",
            "habis transfer",
            "udah transfer",
            "sudah tf",
            "bukti tf",
            "sudah kirim",
            "konfirmasi transfer",
        ],
    )
    if is_konfirmasi:
        if _ada_salah_satu(teks, ["zakat mal", "zakat maal"]):
            return "doa_zakat_mal"
        if _ada_salah_satu(teks, ["zakat penghasilan", "zakat profesi", "zakat fitrah", "zakat maal", "zakat perdagangan", "zakat"]):
            return "doa_zakat_penghasilan"
        return "doa_infak"

    # 2. Human handoff wajib untuk PINTAS/pengajuan bantuan
    if _ada_salah_satu(
        teks,
        [
            "pintas",
            "pinjam",
            "meminjam",
            "pinjaman tanpa syarat",
            "pinjaman tanpa agunan",
            "pengajuan bantuan",
            "ajukan bantuan",
            "minta bantuan dana",
            "butuh bantuan dana",
            "permohonan bantuan",
            "ingin dibantu admin",
            "bicara admin",
            "hubungi admin",
            "cs",
            "customer service",
            "staf admin",
        ],
    ):
        return "handoff_admin"

    # 3. Sapaan
    if _is_sapaan(teks):
        return "sapaan"

    # 4. Profil lembaga
    if _ada_salah_satu(teks, ["apa itu rumah amal", "rumah amal itu apa", "profil rumah amal", "tentang rumah amal", "lembaga apa"]):
        return "profil_lembaga"
    if _ada_salah_satu(teks, ["alamat", "letak kantor", "lokasi kantor", "di mana kantor", "dimana kantor", "sebelah mana", "posisi kantor", "lokasi", "di mana", "dimana"]):
        return "info_alamat"
    if _ada_salah_satu(teks, ["jam kerja", "jam buka", "jam operasional", "waktu operasional", "kapan buka", "hari kerja", "buka jam", "tutup jam"]):
        return "info_jam_kerja"
    if "visi" in teks:
        return "visi_lembaga"
    if "misi" in teks:
        return "misi_lembaga"
    if _ada_salah_satu(teks, ["motto", "jargon"]):
        return "motto_lembaga"
    if _ada_salah_satu(teks, ["sasaran utama", "mustahik", "penerima manfaat", "siapa yang dibantu"]):
        return "sasaran_mustahik"
    if _ada_salah_satu(teks, ["siapa direktur", "direktur rumah amal", "pimpinan rumah amal"]):
        return "direktur_lembaga"
    if _ada_salah_satu(teks, ["bagian struktural resmi", "resmi dari usk", "bagian dari usk", "di bawah usk"]):
        return "status_resmi_usk"

    # 5. Donasi & ZIS
    if _ada_salah_satu(teks, ["qris", "barcode", "scan qr", "kode qr"]):
        return "info_qris"
    if _ada_salah_satu(teks, ["rekening", "nomor rekening", "norek", "transfer ke mana", "transfer kemana"]):
        return "info_rekening"
    if _ada_salah_satu(
        teks,
        [
            "cara donasi",
            "cara menyalurkan donasi",
            "cara zakat",
            "cara infak",
            "cara sedekah",
            "ingin berdonasi",
            "mau donasi",
            "bayar zakat",
            "membayar zakat",
            "pembayaran zakat",
            "menunaikan zakat",
            "mau bayar zakat",
        ],
    ):
        return "cara_donasi"
    if _ada_salah_satu(teks, ["laporan penyaluran", "laporan donasi", "laporan rutin", "transparan"]):
        return "laporan_penyaluran"
        
    # =================================================================
    # 1. Cek niat MENDAFTAR (Lebih Spesifik) dengan KAMUS PENDAFTARAN
    # =================================================================
    KAMUS_PENDAFTARAN = {
        "daftar_infak_rutin": ["daftar infak rutin", "mendaftar infak rutin", "komunitas infak rutin", "bayar infak rutin"],
        "daftar_zakat_mal": ["daftar zakat mal", "bayar zakat mal", "tunaikan zakat mal", "zakat harta", "zakat maal"],
        "daftar_zakat_penghasilan": ["daftar zakat penghasilan", "bayar zakat profesi", "zakat gaji", "zakat profesi", "zakat penghasilan"],
        "daftar_peduli_palestina": ["daftar donasi palestina", "bantu palestina", "donasi palestina", "ota palestina"]
    }

    for intent_program, kata_kunci in KAMUS_PENDAFTARAN.items():
        if _ada_salah_satu(teks, kata_kunci):
            return intent_program
            
    # =================================================================
    # 2. Baru cek niat BERTANYA INFO (Lebih Umum)
    # =================================================================
    if _ada_salah_satu(teks, ["infak rutin", "apa itu infak rutin"]):
        return "info_infak_rutin"
    if _ada_salah_satu(teks, ["kurangi pajak", "pengurang pajak", "zakat untuk pajak"]):
        return "zakat_pajak"
    if _ada_salah_satu(teks, ["jenis zakat", "zakat apa saja", "layanan zakat apa saja"]):
        return "jenis_zakat"
    if _ada_salah_satu(teks, ["masyarakat umum", "di luar kampus", "boleh berdonasi", "alumni boleh donasi"]):
        return "donatur_umum"
    if _ada_salah_satu(teks, ["kalkulator zakat", "situs resmi", "website rumah amal"]):
        return "kalkulator_zakat"
    if _ada_salah_satu(teks, ["hotline", "nomor kontak", "nomor wa", "whatsapp resmi", "kontak layanan"]):
        return "info_kontak"

    # 6. Program umum dan beasiswa
    if _ada_salah_satu(teks, ["syarat beasiswa", "syarat utama beasiswa", "persyaratan beasiswa"]):
        return "syarat_beasiswa_umum"
    if _ada_semua(teks, ["beasiswa", "apa saja"]) or _ada_salah_satu(teks, ["program apa saja", "program bantuan apa saja", "daftar program", "program rumah amal"]):
        return "info_program"
    if _ada_salah_satu(teks, ["bpra ukt", "bpra", "ukt"]) and _ada_salah_satu(teks, ["apa itu", "program", "beasiswa", "info"]):
        return "info_bpra_ukt"
    if _ada_salah_satu(teks, ["tidak merokok", "tidak berpacaran", "syarat mutlak"]):
        return "alasan_aturan_akhlak"
    if _ada_salah_satu(teks, ["judi online", "judol", "didiskualifikasi"]):
        return "diskualifikasi_judol"
    if _ada_salah_satu(teks, ["cara daftar beasiswa", "bagaimana cara mendaftar", "pendaftaran beasiswa", "daftar bantuan mahasiswa"]):
        return "cara_daftar_beasiswa"
    if _ada_salah_satu(teks, ["dokumen apa saja", "berkas beasiswa", "unggah berkas", "dokumen beasiswa"]):
        return "dokumen_beasiswa"
    if _ada_salah_satu(teks, ["semester 1", "maba", "minimal semester", "maksimal semester"]):
        return "semester_beasiswa"
    if _ada_salah_satu(teks, ["ipk minimal", "batas ipk", "minimal ipk"]):
        return "syarat_ipk"
    if _ada_salah_satu(teks, ["kip kuliah", "double funding", "beasiswa rutin lainnya"]):
        return "double_funding"
    if _ada_salah_satu(teks, ["peduli sigra", "apa itu sigra"]):
        return "peduli_sigra"
    if _ada_salah_satu(teks, ["korban kebakaran", "korban bencana", "bantuan darurat mahasiswa", "laptop baru"]):
        return "bantuan_bencana_mahasiswa"
    if _ada_salah_satu(teks, ["seleksi wawancara", "tahapan wawancara", "apakah ada wawancara"]):
        return "seleksi_wawancara"
    if _ada_salah_satu(teks, ["survei rumah", "kunjungan lapangan", "field survey"]):
        return "survei_rumah"
    if _ada_salah_satu(teks, ["kewajiban penerima", "setelah lulus beasiswa", "penerima manfaat wajib"]):
        return "kewajiban_penerima"
    if _ada_salah_satu(teks, ["berapa kali dibuka", "2 kali setahun", "kapan beasiswa dibuka", "periode beasiswa"]):
        return "periode_beasiswa"

    # Pertanyaan program yang ada di daftar, tetapi detail spesifik tidak tertulis di dokumen.
    if _ada_salah_satu(teks, PROGRAM_UMUM_TERSEBUT):
        if _ada_salah_satu(teks, ["syarat", "cara daftar", "persyaratan", "apa itu", "program", "ada", "tersedia"]):
            return "info_program"

    # 7. Kemitraan & pemberdayaan
    if _ada_salah_satu(teks, ["modal usaha", "bantuan modal usaha", "p2emd", "umkm"]):
        return "modal_usaha"
    if _ada_salah_satu(teks, ["pembinaan usaha", "pelatihan usaha", "pendampingan usaha", "sertifikasi halal"]):
        return "pembinaan_umkm"
    if _ada_salah_satu(teks, ["kerja sama eksternal", "mitra eksternal", "bermitra dengan siapa", "sba"]):
        return "mitra_eksternal"
    if _ada_salah_satu(teks, ["tujuan kolaborasi", "tujuan kerja sama csr", "kolaborasi csr"]):
        return "tujuan_kolaborasi_csr"
    if _ada_salah_satu(teks, ["laporan keuangan", "laporan tahunan", "publikasi laporan"]):
        return "laporan_publik"

    # 8. Ramadan & penyaluran lainnya
    if _ada_salah_satu(teks, ["takjil gratis", "dapur umum", "berbuka puasa gratis", "ramadan"]):
        return "takjil_ramadan"
    if _ada_salah_satu(teks, ["apresiasi fi sabilillah", "fi sabilillah", "paket sembako", "santunan hari raya"]):
        return "apresiasi_fisabilillah"

    # Fallback ke LLM untuk klasifikasi intent fleksibel
    llm_intent = llm_agent.get_intent(teks)
    if llm_intent and (llm_intent in QA_SCRIPT or llm_intent == "sapaan"):
        return llm_intent

    return "tidak_diketahui"


def ambil_balasan(intent: str, nama_pengirim: str | None = None) -> str:
    from services.gender_detector import deteksi_sapaan_gender, bersihkan_dan_normalisasi_nama
    sapaan_donatur = deteksi_sapaan_gender(nama_pengirim)
    clean_name = bersihkan_dan_normalisasi_nama(nama_pengirim).title() if nama_pengirim else ""
    # Hindari duplikasi seperti "Kak Kak" saat nama asli tidak diketahui dan
    # fallback-nya kebetulan sama dengan kata sapaan (mis. nama_pengirim="Kak").
    if clean_name and clean_name.lower() != sapaan_donatur.lower():
        sapaan_lengkap = f"{sapaan_donatur} {clean_name}"
    else:
        sapaan_lengkap = sapaan_donatur

    if intent in ["doa_zakat_mal", "doa_zakat_penghasilan", "doa_infak"]:
        prog_tag = "Zakat Mal" if intent == "doa_zakat_mal" else ("Zakat Penghasilan" if intent == "doa_zakat_penghasilan" else "Infak Rutin")
        return _dapatkan_doa_spesifik(prog_tag, sapaan_lengkap)

    if intent == "info_program":
        return get_program_list()

    text = QA_SCRIPT.get(intent, QA_SCRIPT["tidak_diketahui"])

    if "{sapaan_panggilan}" in text:
        text = text.replace("{sapaan_panggilan}", sapaan_lengkap)

    return text


FOLLOW_UP_PROGRAM_HINTS = [
    "syaratnya",
    "persyaratannya",
    "cara daftarnya",
    "cara daftar",
    "prosesnya",
    "detailnya",
    "itu bagaimana",
    "itu gimana",
    "yang tadi",
    "yang itu",
    "program itu",
]

MULTI_INTENT_SPLITTER = re.compile(r"(?:\?|\!|\n|,\s+dan\s+|\s+dan\s+|\s+serta\s+|\s+lalu\s+|\s+terus\s+)", re.IGNORECASE)


def normalisasi_output_model(raw_output: str) -> list[str]:
    """
    Penjaga jika suatu saat jalur model diaktifkan lagi.
    Fungsi ini merapikan label intent yang sering keluar dengan format tidak konsisten.
    """
    teks = _normalisasi_teks(raw_output)
    if not teks:
        return []

    kandidat = []
    peta = {
        "info jam kerja": "info_jam_kerja",
        "jam kerja": "info_jam_kerja",
        "info alamat": "info_alamat",
        "alamat": "info_alamat",
        "info kontak": "info_kontak",
        "kontak": "info_kontak",
        "info rekening": "info_rekening",
        "rekening": "info_rekening",
        "info qris": "info_qris",
        "qris": "info_qris",
        "info program": "info_program",
        "program": "info_program",
        "syarat beasiswa umum": "syarat_beasiswa_umum",
        "syarat beasiswa": "syarat_beasiswa_umum",
        "syarat ipk": "syarat_ipk",
        "konfirmasi zakat mal": "doa_zakat_mal",
        "konfirmasi infak": "doa_infak",
        "sapaan": "sapaan",
        "handoff admin": "handoff_admin",
        "tidak diketahui": "tidak_diketahui",
    }

    for frasa, intent in peta.items():
        if frasa in teks:
            kandidat.append(intent)

    hasil = []
    for item in kandidat:
        if item not in hasil:
            hasil.append(item)
    return hasil


def _pecah_pesan_multi_intent(pesan: str) -> list[str]:
    bagian = [item.strip() for item in MULTI_INTENT_SPLITTER.split(pesan or "") if item and item.strip()]
    return bagian or [pesan or ""]


def _gunakan_konteks_program(teks: str, context: dict | None) -> str | None:
    if not context:
        return None

    last_program_key = context.get("last_program_key")
    if not last_program_key:
        return None

    teks_norm = _normalisasi_teks(teks)
    if not teks_norm:
        return None

    if _ada_salah_satu(teks_norm, FOLLOW_UP_PROGRAM_HINTS):
        return last_program_key

    if teks_norm in {"syarat", "syaratnya apa", "proses", "detail", "detailnya", "gimana", "bagaimana", "yang itu", "yang tadi"}:
        return last_program_key

    return None


def _cocokkan_qna(teks_norm: str, qna_list: list[dict]) -> dict | None:
    """Web Chat tidak punya mekanisme 'ketik angka 1' seperti WhatsApp untuk
    menjawab salah satu 'Pertanyaan Populer' yang ditampilkan - tanpa ini,
    pertanyaan itu cuma jadi teaser yang tidak pernah bisa benar-benar
    dijawab di kanal web (kalimat bebasnya cuma memicu info program yang
    sama diulang lagi, bukan jawaban spesifiknya). Dicocokkan lewat
    "kata_kunci" pendek per QnA (program_manager.py) - bukan kalimat "tanya"
    penuh - supaya tahan typo/parafrase wajar (mis. "beassiswa")."""
    for qna in qna_list:
        kata_kunci = qna.get("kata_kunci") or []
        if kata_kunci and _ada_salah_satu(teks_norm, kata_kunci):
            return qna
    return None


def _tambah_hasil(daftar: list[str], item: str):
    if item and item not in daftar:
        daftar.append(item)

def _skip_fallback_if_minor_followup(teks_norm: str, context: dict | None) -> bool:
    """
    Hindari menambahkan balasan fallback untuk potongan pesan yang bersifat bercanda/lanjutan ringan,
    misalnya setelah user tanya program, lalu bertanya hal remeh: "apakah hewannya berwarna green?".
    """
    if not teks_norm:
        return True

    if not context or not context.get("last_program_key"):
        return False

    # heuristik: potongan pendek atau mengandung kata ganti yang merujuk konteks sebelumnya
    if len(teks_norm) <= 35:
        return True

    if _ada_salah_satu(teks_norm, ["itu", "nya", "yang tadi", "yang itu", "apakah", "warnanya", "warna"]):
        return True

    return False


def susun_balasan(
    pesan: str,
    has_media: bool = False,
    context: dict | None = None,
    nama_pengirim: str = "",
    use_llm_paraphrase: bool = True,
) -> dict:
    """
    Menangani:
    - daftar semua program dari `program_manager.py`
    - pertanyaan program spesifik
    - pesan multi-niat
    - konteks program dari percakapan sebelumnya
    - normalisasi output model jika suatu saat jalur model dipakai lagi
    - pengemasan balasan alami dengan LLM (paraphrasing) dengan fakta 100% terjaga
    """
    context = context or {}
    potongan = _pecah_pesan_multi_intent(pesan)
    intents: list[str] = []
    responses: list[str] = []
    detected_program_key = None
    should_wait_admin = False

    for index, potong in enumerate(potongan):
        potong = potong.strip()
        if not potong and not has_media:
            continue

        teks_norm = _normalisasi_teks(potong)
        if not teks_norm and has_media:
            intent = "doa_infak"
            _tambah_hasil(intents, intent)
            _tambah_hasil(responses, ambil_balasan(intent))
            continue

        # Kasus khusus: user ingin membayar/menunaikan zakat
        # Lebih natural jika diberi "cara donasi" + "nomor rekening" sekaligus.
        if _ada_salah_satu(
            teks_norm,
            [
                "bayar zakat",
                "membayar zakat",
                "pembayaran zakat",
                "menunaikan zakat",
                "mau bayar zakat",
                "ingin membayar zakat",
                "ingin bayar zakat",
            ],
        ):
            _tambah_hasil(intents, "cara_donasi")
            _tambah_hasil(responses, ambil_balasan("cara_donasi"))
            _tambah_hasil(intents, "info_rekening")
            _tambah_hasil(responses, ambil_balasan("info_rekening"))
            # jika user spesifik sebut qris, tambahkan juga
            if _ada_salah_satu(teks_norm, ["qris", "barcode", "scan qr", "kode qr"]):
                _tambah_hasil(intents, "info_qris")
                _tambah_hasil(responses, ambil_balasan("info_qris"))
            continue

        # context dinamis selama 1 pesan: jika di potongan sebelumnya sudah ketemu program,
        # potongan berikutnya boleh menganggap itu sebagai konteks.
        context_dinamis = dict(context or {})
        context_dinamis["last_program_key"] = detected_program_key or context_dinamis.get("last_program_key")

        is_pinjam = _ada_salah_satu(teks_norm, ["pintas", "pinjam", "pinjaman", "meminjam", "pinjam uang"])
        program_key = "pintas" if is_pinjam else extract_program_keyword(potong)
        if not program_key:
            program_key = _gunakan_konteks_program(potong, context_dinamis)

        minta_daftar_program = _ada_salah_satu(
            teks_norm,
            ["program apa saja", "daftar program", "program rumah amal", "beasiswa apa saja", "program bantuan apa saja"],
        )
        minta_detail_program = _ada_salah_satu(
            teks_norm,
            ["apa itu", "detail", "syarat", "persyaratan", "cara daftar", "cara ikut", "proses", "program", "gimana", "bagaimana", "ada"],
        )

        if program_key and not minta_daftar_program:
            data_program = get_program_info(program_key)
            if data_program:
                detected_program_key = program_key
                _tambah_hasil(intents, f"program:{program_key}")

                # Web tidak punya "ketik angka 1" seperti WhatsApp untuk
                # menjawab salah satu "Pertanyaan Populer" - kalau kalimat
                # bebas user cocok kata kunci salah satu QnA program ini,
                # balas jawaban spesifiknya saja, bukan info program lagi.
                qna_cocok = _cocokkan_qna(teks_norm, data_program.get("qna", []))
                # Untuk beberapa pertanyaan bercanda, berikan klarifikasi ringan tapi tetap aman.
                if qna_cocok:
                    _tambah_hasil(responses, f"❓ *{qna_cocok['tanya']}*\n\n{qna_cocok['jawab']}")
                elif program_key == "green_qurban" and _ada_salah_satu(teks_norm, ["warna", "berwarna", "green"]):
                    _tambah_hasil(
                        responses,
                        format_program_response(data_program)
                        + "\n\nCatatan: kata \"Green\" di sini merujuk pada konsep ramah lingkungan (non-plastik), bukan warna hewannya.",
                    )
                else:
                    # Jika potongan ini hanya follow-up ke program yang sama dan kita sudah menjawab programnya,
                    # hindari duplikasi jawaban panjang.
                    if f"program:{program_key}" in intents and responses and _ada_salah_satu(teks_norm, ["apakah", "warnanya", "warna", "yang itu", "itu"]):
                        if program_key == "green_qurban" and _ada_salah_satu(teks_norm, ["warna", "berwarna", "green"]):
                            _tambah_hasil(responses, "Catatan: kata \"Green\" di sini merujuk pada konsep ramah lingkungan (non-plastik), bukan warna hewannya.")
                        # selain itu: cukup abaikan follow-up kecil yang tidak punya jawaban eksplisit
                    else:
                        _tambah_hasil(responses, format_program_response(data_program))
                if program_key == "pintas":
                    should_wait_admin = True
            continue

        if minta_daftar_program:
            intent = "info_program"
            _tambah_hasil(intents, intent)
            _tambah_hasil(responses, ambil_balasan(intent, nama_pengirim=nama_pengirim))
            continue

        intent = klasifikasi_pesan(potong, has_media=has_media if index == 0 else False)
        # Jika sudah ada jawaban lain dan potongan ini hanya jatuh ke "tidak_diketahui",
        # jangan ganggu user dengan fallback yang terasa kaku.
        if intent == "tidak_diketahui" and responses and _skip_fallback_if_minor_followup(teks_norm, context_dinamis):
            _tambah_hasil(intents, intent)
        else:
            _tambah_hasil(intents, intent)
            _tambah_hasil(responses, ambil_balasan(intent, nama_pengirim=nama_pengirim))

    if not responses:
        intents = ["tidak_diketahui"]
        responses = [ambil_balasan("tidak_diketahui", nama_pengirim=nama_pengirim)]

    # Jika PINTAS termasuk salah satu niat, pertahankan alur admin.
    if should_wait_admin:
        _tambah_hasil(intents, "handoff_admin")
        _tambah_hasil(responses, ambil_balasan("handoff_admin_prompt", nama_pengirim=nama_pengirim))

    reply_statis = "\n\n".join(responses)

    return {
        "intents": intents,
        "reply": reply_statis,
        "last_program_key": detected_program_key or context.get("last_program_key"),
        "should_wait_admin": should_wait_admin,
        "normalized_model_output": normalisasi_output_model(" | ".join(intents)),
    }


