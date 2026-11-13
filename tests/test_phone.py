import json

import httpx
from fastapi.testclient import TestClient

from server.phone import Phone
from tests.test_app import TOKEN, FakeBridge, make_app


def recording(answer: str = "Call queued"):
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, text=answer)

    return seen, httpx.MockTransport(handle)


async def test_call_rings_the_named_user_in_turkish_once_per_gap(tmp_path):
    (tmp_path / "arama.json").write_text(json.dumps({"telegram": "@cagan"}), encoding="utf-8")
    seen, transport = recording()
    now = [1000.0]
    phone = Phone(tmp_path / "arama.json", transport, clock=lambda: now[0])
    assert (await phone.call("Ekip   UAC onayı bekliyor"))["ok"]
    params = seen[0].url.params
    assert params["user"] == "@cagan" and params["lang"] == "tr-TR-Standard-A" and params["text"] == "Ekip UAC onayı bekliyor"
    assert "error" in await phone.call("yine")
    now[0] += 121
    assert (await phone.call("yine"))["ok"] and len(seen) == 2


async def test_call_without_setup_says_so(tmp_path):
    assert "kurulmamış" in (await Phone(tmp_path / "arama.json").call("x"))["error"]


class FakePhone:
    def __init__(self):
        self.calls = []

    async def call(self, text):
        self.calls.append(text)
        return {"ok": True}


class FakeTelegram:
    def __init__(self):
        self.sent = []

    async def send(self, text, buttons=None):
        self.sent.append(text)

    async def run(self):
        return None

    async def close(self):
        return None


def test_team_reaches_cagan_by_telegram_and_rings_when_urgent(tmp_path):
    phone, telegram = FakePhone(), FakeTelegram()
    app = make_app(tmp_path, FakeBridge(), phone=phone, telegram=telegram)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        auth = {"X-Ekip-Token": TOKEN}
        r = client.post("/api/team/cagan", headers=auth, json={"mesaj": "Giriş lazım", "terminal": str(tmp_path)})
        assert r.json()["ok"] and phone.calls == []
        client.post("/api/team/cagan", headers=auth, json={"mesaj": "UAC onayı", "acil": True})
        assert "UAC onayı" in phone.calls[0]
        assert len(telegram.sent) == 2 and "EKİP ÇAĞAN'I ARIYOR" in telegram.sent[0]
        assert client.post("/api/team/cagan", headers=auth, json={"mesaj": " "}).status_code == 400


async def test_cuba_can_ring(tmp_path):
    from server.live import CubaTools

    async def hand_over(*_):
        return None

    phone = FakePhone()
    tools = CubaTools(hand_over, lambda keys: None, tmp_path, phone=phone)
    assert (await tools.run("beni_ara", {"mesaj": "Toplantı 5 dakika sonra"}))["ok"]
    assert phone.calls == ["Toplantı 5 dakika sonra"]
