import re


def ekstrak_formulir(pesan: str) -> dict:
    """
    Mengekstrak data Nama, Instansi/Pekerjaan, dan Nominal Komitmen
    dari pesan formulir Infak Rutin yang diisi pengguna.
    """
    pesan_str = pesan or ""
    nama = re.search(r'Nama\s*:\s*(.*)', pesan_str, re.IGNORECASE)
    pekerjaan = re.search(r'Instansi/Pekerjaan\s*:\s*(.*)', pesan_str, re.IGNORECASE)
    nominal = re.search(r'Nominal Komitmen\s*:\s*(.*)', pesan_str, re.IGNORECASE)

    return {
        "nama": nama.group(1).strip() if nama and nama.group(1).strip() else None,
        "pekerjaan": pekerjaan.group(1).strip() if pekerjaan and pekerjaan.group(1).strip() else None,
        "nominal": nominal.group(1).strip() if nominal and nominal.group(1).strip() else None
    }
