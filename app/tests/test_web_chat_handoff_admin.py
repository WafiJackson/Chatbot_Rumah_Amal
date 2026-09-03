"""
Regression test untuk bug handoff admin via Web Chat (dilaporkan 3 Sep 2026):

1. "Hubungi admin" yang POLOS (tidak menyinggung PINTAS/bantuan dana sama
   sekali) malah dijawab dengan teks PINTAS-spesifik - kedua niat itu
   sebelumnya salah dipetakan ke intent yang SAMA di klasifikasi_pesan().

2. Web chat menanyakan "Balas *Ya* atau *Batal*" tapi TIDAK PERNAH benar-benar
   mengerti balasan Ya/Batal itu sendiri (murni Q&A stateless, beda dari FSM
   MENUNGGU_ADMIN di WhatsApp) - balasan "Batal" yang jelas malah jatuh ke
   fallback "Mimin kurang paham".
"""
import routes.public_web as public_web


def test_hubungi_admin_polos_tidak_menyebut_pintas(client):
    resp = client.post("/api/web-chat", json={"message": "Hubungi admin"})
    reply = resp.json()["reply"]
    assert "PINTAS" not in reply
    assert "Ya" in reply and "Batal" in reply


def test_niat_pintas_tetap_menyebut_pintas(client):
    resp = client.post("/api/web-chat", json={"message": "saya mau ajukan pinjaman PINTAS"})
    reply = resp.json()["reply"]
    assert "PINTAS" in reply


def test_balasan_batal_setelah_hubungi_admin_dipahami(client):
    resp1 = client.post("/api/web-chat", json={"message": "Hubungi admin"})
    assert "Batal" in resp1.json()["reply"]

    resp2 = client.post("/api/web-chat", json={"message": "Batal"})
    reply2 = resp2.json()["reply"]
    assert "dibatalkan" in reply2.lower()
    assert "kurang paham" not in reply2.lower()


def test_balasan_ya_setelah_hubungi_admin_memicu_notify_admin(client, monkeypatch):
    dipanggil = []
    monkeypatch.setattr(public_web, "notify_admin", lambda pesan: dipanggil.append(pesan))

    client.post("/api/web-chat", json={"message": "saya mau bicara dengan admin"})
    resp2 = client.post("/api/web-chat", json={"message": "Ya"})
    reply2 = resp2.json()["reply"]

    assert "diteruskan ke admin" in reply2.lower() or "membalas chat" in reply2.lower()
    assert len(dipanggil) == 1  # admin BENAR-BENAR diberi tahu, bukan cuma klaim kosong


def test_balasan_ambigu_saat_menunggu_konfirmasi_tetap_ditanya_ulang(client):
    client.post("/api/web-chat", json={"message": "hubungi admin"})
    resp2 = client.post("/api/web-chat", json={"message": "hmm gimana ya"})
    reply2 = resp2.json()["reply"]
    assert "Ya" in reply2 and "Batal" in reply2
