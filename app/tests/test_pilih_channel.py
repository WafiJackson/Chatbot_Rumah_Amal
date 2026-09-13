"""
Halaman "Pilih Channel" (/pilih-channel) - perantara sebelum masuk Web Chat,
dituju dari widget "robot-toast" yang akan dipasang tim web di beranda situs
resmi. Mockup asli ada di folder pribadi/mockup/pilih-channel.html.
"""


def test_pilih_channel_menampilkan_dua_opsi(client):
    resp = client.get("/pilih-channel")
    assert resp.status_code == 200
    body = resp.text
    assert "Chat via WhatsApp" in body
    assert "Chat di Website" in body


def test_pilih_channel_link_whatsapp_ke_nomor_resmi(client):
    resp = client.get("/pilih-channel")
    body = resp.text
    assert "https://wa.me/628116888123" in body


def test_pilih_channel_link_web_chat_ke_root(client):
    resp = client.get("/pilih-channel")
    body = resp.text
    assert 'href="/"' in body
