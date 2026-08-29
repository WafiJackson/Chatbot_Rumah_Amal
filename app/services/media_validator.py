# ==========================================
# VALIDATOR GAMBAR RESI (dipakai bersama WhatsApp & Web Chat)
# ==========================================
# Dipisah jadi modul sendiri supaya kedua kanal punya pengaman yang SAMA -
# sebelumnya Web Chat sudah punya batas ukuran + sniff format, tapi WhatsApp
# tidak sama sekali (celah yang ditemukan lewat audit keamanan 28 Agustus).

import requests

MAKS_UKURAN_RESI_BYTES = 5 * 1024 * 1024  # 5 MB


def unduh_dengan_batas_ukuran(url: str, headers: dict, timeout: int, maks_bytes: int = MAKS_UKURAN_RESI_BYTES) -> bytes | None:
    """Unduh via streaming dan batalkan begitu melebihi maks_bytes - supaya
    tidak membebani memori/bandwidth dengan file besar yang tidak wajar
    untuk sebuah resi transfer sebelum sempat ditolak."""
    try:
        with requests.get(url, headers=headers, timeout=timeout, stream=True) as res:
            if res.status_code != 200:
                return None
            total = 0
            potongan = []
            for chunk in res.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > maks_bytes:
                    return None
                potongan.append(chunk)
            return b"".join(potongan)
    except Exception:
        return None


def sniff_gambar_valid(data: bytes) -> bool:
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
