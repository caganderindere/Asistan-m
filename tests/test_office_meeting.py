import json

from server.office_bus import OfficeBus
from server.office_meeting import LiveMeeting


class FakeWorker:
    def __init__(self, name, line):
        self.role = type("R", (), {"name": name})()
        self.line = line
        self.heard = []

    async def answer(self, sender, question, context=""):
        self.heard.append((sender, question, context))
        return self.line


class FakeOmni:
    def __init__(self, content):
        self.content = content

    async def chat(self, messages, tools=None):
        return {"content": self.content}


def meeting(tmp_path, omni=None):
    shown = []

    async def show(state):
        shown.append(state)

    workers = {"pazarlama": FakeWorker("Pazarlamacı", "Almanya'da bayi ağı"), "icerik": FakeWorker("İçerikçi", "Katılıyorum")}
    m = LiveMeeting(workers.get, omni or FakeOmni("{}"), OfficeBus(tmp_path), show)
    return m, shown, workers


async def test_floor_gets_a_real_answer(tmp_path):
    m, shown, workers = meeting(tmp_path)
    assert (await m.open("Almanya pazarı", ["pazarlama", "icerik"]))["ok"]
    line = await m.give_floor("pazarlama", "Nasıl gireriz?")
    assert line == {"who": "pazarlama", "text": "Almanya'da bayi ağı"}
    assert shown[-1]["lines"] == [{"who": "lider", "text": "Nasıl gireriz?"}, {"who": "pazarlama", "text": "Almanya'da bayi ağı"}]
    assert shown[-1]["speaker"] == "pazarlama" and shown[-1]["members"] == ["pazarlama", "icerik"]
    assert "Almanya pazarı" in workers["pazarlama"].heard[0][2]


async def test_floor_without_meeting(tmp_path):
    m, _, _ = meeting(tmp_path)
    assert (await m.give_floor("pazarlama", "?")) == {"error": "Açık toplantı yok."}
    assert "error" in await m.close()


async def test_unknown_member_on_open(tmp_path):
    m, _, _ = meeting(tmp_path)
    assert "error" in await m.open("konu", ["pazarlama", "yok"])
    assert not m.is_open


async def test_close_summarizes_and_clears(tmp_path):
    summary = {"kararlar": ["Bayi ağı kurulacak"], "gorevler": [{"kim": "pazarlama", "is": "Bayi listesi"}]}
    m, shown, _ = meeting(tmp_path, FakeOmni(json.dumps(summary, ensure_ascii=False)))
    await m.open("konu", ["pazarlama"])
    await m.give_floor("pazarlama", "?")
    result = await m.close()
    assert result == summary and shown[-1] is None and not m.is_open


async def test_close_with_bad_json_returns_empty(tmp_path):
    m, _, _ = meeting(tmp_path, FakeOmni("bozuk"))
    await m.open("konu", ["pazarlama"])
    assert await m.close() == {"kararlar": [], "gorevler": []}


async def test_floor_when_model_fails(tmp_path):
    from server.omni import OmniError

    m, shown, workers = meeting(tmp_path)

    async def broken(sender, question, context=""):
        raise OmniError("Ücretsiz modellerin limiti doldu")

    workers["pazarlama"].answer = broken
    await m.open("konu", ["pazarlama"])
    assert (await m.give_floor("pazarlama", "?")) == {"error": "Pazarlamacı cevap veremedi: Ücretsiz modellerin limiti doldu"}
    assert shown[-1]["speaker"] == ""


async def test_close_reads_fenced_json(tmp_path):
    fenced = '```json\n{"kararlar": ["Bayi ağı"], "gorevler": []}\n```\n'
    m, _, _ = meeting(tmp_path, FakeOmni(fenced))
    await m.open("konu", ["pazarlama"])
    await m.give_floor("pazarlama", "?")
    assert (await m.close())["kararlar"] == ["Bayi ağı"]
