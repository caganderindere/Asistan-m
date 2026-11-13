import json

from fastapi.testclient import TestClient

from server.phone import Phone
from tests.test_app import TOKEN, FakeBridge, make_app


SUB = {"endpoint": "https://web.push.apple.com/abc", "keys": {"p256dh": "x", "auth": "y"}}


class Pushes:
    def __init__(self, status=201):
        self.sent = []
        self.status = status

    def __call__(self, sub, payload, key_file):
        self.sent.append((sub["endpoint"], json.loads(payload), key_file))
        return self.status


def make_phone(tmp_path, pushes, now=None):
    async def no_wait(_):
        return None

    return Phone(tmp_path, send=pushes, sleep=no_wait, clock=(lambda: now[0]) if now else lambda: 1000.0)


async def test_call_rings_until_answered_and_tells_why(tmp_path):
    pushes = Pushes()
    phone = make_phone(tmp_path, pushes)
    assert "bildirim açılmamış" in (await phone.call("x"))["error"]
    assert phone.subscribe(SUB) == 1 and phone.subscribe(SUB) == 1  # the same phone twice is one device
    assert (await phone.call("Ekip   UAC onayı bekliyor"))["ok"]
    await phone.idle()
    assert len(pushes.sent) == 5  # nobody answered: five rings
    call = pushes.sent[0][1]
    assert call["body"] == "Ekip UAC onayı bekliyor" and call["title"] == "📞 Cuba arıyor"
    assert phone.answer(call["id"]) == "Ekip UAC onayı bekliyor" and phone.answer("yok") == ""
    assert (tmp_path / "push_vapid.pem").exists() and len(phone.public_key()) > 80


async def test_answering_stops_the_ringing(tmp_path):
    pushes = Pushes()
    phone = make_phone(tmp_path, pushes)
    phone.subscribe(SUB)

    def answer_on_first(sub, payload, key_file):
        pushes(sub, payload, key_file)
        phone.answer(json.loads(payload)["id"])
        return 201

    phone._send = answer_on_first
    await phone.call("acil")
    await phone.idle()
    assert len(pushes.sent) == 1


async def test_gone_phones_are_forgotten_and_calls_are_spaced(tmp_path):
    now = [1000.0]
    phone = make_phone(tmp_path, Pushes(status=410), now)
    phone.subscribe(SUB)
    await phone.call("bir")
    await phone.idle()
    assert phone.devices == 0
    phone.subscribe(SUB)
    assert "Az önce" in (await phone.call("iki"))["error"]
    now[0] += 121
    assert (await phone.call("iki"))["ok"]
    await phone.idle()


def test_bad_subscription_is_refused(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        make_phone(tmp_path, Pushes()).subscribe({"endpoint": "http://x"})


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



def test_page_subscribes_and_an_answered_call_opens_the_talk(tmp_path):
    class Live:
        opening = ""
        active = False

    phone, live = Phone(tmp_path), Live()
    app = make_app(tmp_path, FakeBridge(), phone=phone, live=live)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert len(client.get("/api/push/key").json()["key"]) > 80
        assert client.post("/api/push/subscribe", json=SUB).json()["devices"] == 1
        assert client.post("/api/push/subscribe", json={"endpoint": "x"}).status_code == 400
        phone._calls["abc"] = {"text": "UAC onayı lazım", "answered": False}
        assert client.post("/api/push/answer", json={"id": "abc"}).json()["text"] == "UAC onayı lazım"
        assert live.opening == "UAC onayı lazım"
