import json

from server.office_bus import OfficeBus
from server.omni import OmniError
from server.team import ROLES
from server.worker import MAX_CALLS, OfficeWorker

ROLE = {r.id: r for r in ROLES}


def call(name: str, **args) -> dict:
    return {"content": None, "tool_calls": [
        {"id": f"c-{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


class FakeOmni:
    """Answers with the queued messages in turn; the last one repeats."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    async def chat(self, messages, tools=None):
        self.seen.append((messages, tools))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


def worker(tmp_path, omni, role="pazarlama", colleagues=None) -> OfficeWorker:
    bus = OfficeBus(tmp_path / "log")
    return OfficeWorker(ROLE[role], omni, bus, colleagues or (lambda who: None))


def tool_results(omni) -> list[str]:
    return [m["content"] for m in omni.seen[-1][0] if m["role"] == "tool"]


async def test_run_writes_file_and_reports(tmp_path):
    omni = FakeOmni(call("dosya_yaz", yol="pazarlama/plan.md", icerik="# Plan"), call("rapor_ver", metin="Plan yazıldı"))
    report = await worker(tmp_path, omni).run("Plan yaz", tmp_path)
    assert (tmp_path / "pazarlama" / "plan.md").read_text(encoding="utf-8") == "# Plan"
    assert report == "Plan yazıldı"


async def test_write_outside_pazarlama_is_refused(tmp_path):
    omni = FakeOmni(call("dosya_yaz", yol="../x.md", icerik="x"), call("dosya_yaz", yol="src/app.py", icerik="x"),
                    call("rapor_ver", metin="bitti"))
    await worker(tmp_path, omni).run("yaz", tmp_path)
    assert not (tmp_path.parent / "x.md").exists() and not (tmp_path / "src" / "app.py").exists()
    assert all("HATA" in r for r in tool_results(omni))


async def test_mesaj_at_returns_colleague_answer_and_is_logged(tmp_path):
    icerik = worker(tmp_path, FakeOmni({"content": "Samimi"}), role="icerik")
    omni = FakeOmni(call("mesaj_at", kime="icerik", metin="Ton ne?"), call("rapor_ver", metin="tamam"))
    pazarlama = worker(tmp_path, omni, colleagues={"icerik": icerik}.get)
    icerik.bus = pazarlama.bus
    await pazarlama.run("tonu sor", tmp_path)
    assert "Samimi" in tool_results(omni)[0]
    assert [(m.sender, m.to, m.text) for m in pazarlama.bus.recent("pazarlama")] == [
        ("pazarlama", "icerik", "Ton ne?"), ("icerik", "pazarlama", "Samimi")]


async def test_unknown_colleague(tmp_path):
    omni = FakeOmni(call("mesaj_at", kime="yok", metin="?"), call("rapor_ver", metin="tamam"))
    await worker(tmp_path, omni).run("sor", tmp_path)
    assert "HATA" in tool_results(omni)[0]


async def test_message_limit(tmp_path):
    icerik = worker(tmp_path, FakeOmni({"content": "evet"}), role="icerik")
    omni = FakeOmni(*[call("mesaj_at", kime="icerik", metin=f"soru {i}") for i in range(5)], call("rapor_ver", metin="ok"))
    pazarlama = worker(tmp_path, omni, colleagues={"icerik": icerik}.get)
    icerik.bus = pazarlama.bus
    await pazarlama.run("sor", tmp_path)
    assert "HATA" in tool_results(omni)[-1]
    assert len(pazarlama.bus.recent("pazarlama", limit=50)) == 8


async def test_call_limit_stops_loop(tmp_path):
    omni = FakeOmni(call("dosya_oku", yol="README.md"))
    report = await worker(tmp_path, omni).run("oku", tmp_path)
    assert len(omni.seen) == MAX_CALLS and report.startswith("HATA")


async def test_omni_error_becomes_report(tmp_path):
    report = await worker(tmp_path, FakeOmni(OmniError("OmniRoute'a ulaşılamadı"))).run("iş", tmp_path)
    assert report == "HATA: OmniRoute'a ulaşılamadı"


async def test_answer_is_short_and_toolless(tmp_path):
    omni = FakeOmni({"content": "a" * 500})
    answer = await worker(tmp_path, omni).answer("lider", "Ne düşünüyorsun?")
    assert len(answer) == 300 and omni.seen[0][1] is None


async def test_activity_is_reported(tmp_path):
    seen = []
    omni = FakeOmni(call("dosya_oku", yol="README.md"), call("rapor_ver", metin="ok"))
    w = OfficeWorker(ROLE["pazarlama"], omni, OfficeBus(tmp_path / "log"), lambda who: None,
                     on_activity=lambda who, what: seen.append((who, what)))
    await w.run("oku", tmp_path)
    assert seen[0][0] == "pazarlama" and "dosya_oku" in seen[0][1] and seen[-1] == ("pazarlama", "")
