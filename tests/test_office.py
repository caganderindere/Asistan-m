import asyncio

from server.live import CubaTools
from server.office import Office
from server.office_bus import OfficeBus
from server.terminal import TerminalCrew


class FakeOmni:
    available = True

    def __init__(self, content="Bitti"):
        self.content = content

    async def chat(self, messages, tools=None):
        await asyncio.sleep(0)
        return {"content": self.content}


def office(tmp_path, omni=None):
    told, pushed = [], []
    crew = TerminalCrew(clock=lambda: 0)

    async def tell(text):
        told.append(text)

    async def push(folder):
        pushed.append(folder)

    o = Office(omni or FakeOmni(), OfficeBus(tmp_path / "log"), lambda folder: crew, tell, push)
    return o, crew, told


def desk(crew, who):
    return next(a for a in crew.snapshot()["agents"] if a["id"] == who)


async def test_give_reports_back(tmp_path):
    o, crew, told = office(tmp_path)
    started = await o.give("pazarlama", "Hedef kitleyi çıkar", str(tmp_path))
    assert started["ok"] and desk(crew, "pazarlama")["state"] == "working"
    await o.idle()
    assert desk(crew, "pazarlama")["state"] == "idle"
    assert told and told[-1].startswith("[EKİP RAPORU") and "Bitti" in told[-1]


async def test_floor_answer_is_told_to_cuba(tmp_path):
    o, crew, told = office(tmp_path, FakeOmni("Bayi ağı kurmalıyız"))
    await o.open_meeting("Almanya", ["pazarlama"], str(tmp_path))
    assert crew.snapshot()["phase"] == "review"
    started = await o.give_floor("pazarlama", "Nasıl gireriz?")
    assert started["ok"]
    await o.idle()
    assert told[-1] == "[SÖZ — Pazarlama Uzmanı] Bayi ağı kurmalıyız"
    await o.close_meeting()
    assert crew.snapshot()["phase"] != "review"


async def test_give_rejects_non_member(tmp_path):
    o, _, _ = office(tmp_path)
    assert "error" in await o.give("kidemli", "kod yaz", str(tmp_path))


async def test_office_tools_route_to_office(tmp_path):
    async def nothing(*a):
        return None

    calls = []

    class FakeOffice:
        async def give_floor(self, who, question):
            calls.append((who, question))
            return {"ok": True}

    tools = CubaTools(nothing, lambda k: None, tmp_path, office=FakeOffice())
    assert (await tools.run("soz_ver", {"kim": "pazarlama", "soru": "?"})) == {"ok": True}
    assert calls == [("pazarlama", "?")]
    assert "error" in await CubaTools(nothing, lambda k: None, tmp_path).run("soz_ver", {"kim": "pazarlama", "soru": "?"})


async def test_report_is_kept_even_when_nobody_listens(tmp_path):
    o, _, _ = office(tmp_path)
    await o.give("pazarlama", "Hedef kitleyi çıkar", str(tmp_path))
    await o.idle()
    kept = o.workers["pazarlama"].bus.recent("lider")
    assert [(m.sender, m.channel, m.text) for m in kept] == [("pazarlama", "rapor", "Bitti")]
