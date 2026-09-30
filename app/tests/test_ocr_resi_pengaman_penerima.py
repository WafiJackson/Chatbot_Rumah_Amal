"""Pengaman OCR resi: nama pengirim yang sama dengan nama PENERIMA dibuang.

Ditemukan lewat uji perbandingan model (30 Sep 2026): saat nama pengirim
tidak terlihat di foto, gemini-3.5-flash-lite kadang mengisinya dengan nama
penerima - di resi ke Rumah Amal itu berarti donatur tercatat sebagai
"Rumah Amal". Instruksi di prompt saja tidak cukup (resi kabur tetap lolos).
Respons model disimulasikan di sini - tidak ada panggilan API.
"""
import json

import pytest

from services import llm_agent


def _baca_dengan_respons(monkeypatch, respons: dict) -> dict:
    monkeypatch.setattr(llm_agent, "_panggil_gemini_api", lambda *a, **k: json.dumps(respons))
    return llm_agent.ekstrak_resi_vision(b"\xff\xd8\xff" + b"\x00" * 100)


@pytest.mark.parametrize("pengirim,penerima", [("IKHSAN", "IKHSAN"), ("ikhsan", "  IKHSAN "), ("Rumah Amal Mesjid Unsyiah", "RUMAH AMAL MESJID UNSYIAH")])
def test_nama_sama_dengan_penerima_dibuang(monkeypatch, pengirim, penerima):
    hasil = _baca_dengan_respons(monkeypatch, {"nama": pengirim, "penerima": penerima, "nominal": "501500", "program": "UMUM"})
    assert hasil["nama"] is None
    assert hasil["nominal"] == "501500"


def test_nama_pengirim_berbeda_tetap_dipakai(monkeypatch):
    hasil = _baca_dengan_respons(monkeypatch, {"nama": "Vera Fitria", "penerima": "Rumah Amal Mesjid Unsyiah", "nominal": "2000", "program": "UMUM"})
    assert hasil["nama"] == "Vera Fitria"


def test_nama_yang_hanya_sebagian_mirip_penerima_tidak_dibuang(monkeypatch):
    """Donatur bernama "Amal" yang transfer ke "Rumah Amal" tetap tercatat."""
    hasil = _baca_dengan_respons(monkeypatch, {"nama": "Amal", "penerima": "Rumah Amal Mesjid Unsyiah", "nominal": "50000", "program": "UMUM"})
    assert hasil["nama"] == "Amal"


def test_respons_tanpa_kolom_penerima_tetap_berfungsi(monkeypatch):
    hasil = _baca_dengan_respons(monkeypatch, {"nama": "Faiza Ramadhani", "nominal": "3000000", "program": "UMUM"})
    assert hasil["nama"] == "Faiza Ramadhani"
