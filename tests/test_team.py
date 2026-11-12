import asyncio

import pytest

from server.claude_events import TextDelta, ToolUse, TurnResult
from server.team import LEAD, LeadTurn, MeetingEnded, TeamError
from tests.test_app import FakeBridge, make_team


@pytest.fixture
async def team(tmp_path):
    t = make_team(tmp_path, FakeBridge())
    await t.open(str(tmp_path))
    await settle()
    yield t
    await t.close()


async def settle():
    """Let the watchers handle everything pushed so far."""
    for _ in range(20):
        await asyncio.sleep(0)


async def finish(team, role, *events, error=False):
    team.fakes[role].push(*events, TurnResult("s", error))
    await settle()


def by_id(team):
    return {a["id"]: a for a in team.snapshot()["agents"]}


async def test_plan_waits_for_approval(team):
    tasks = team.plan([("kidemli", "Giriş hatasını düzelt"), ("asistan", "README'yi güncelle")])
    assert [t.status for t in tasks] == ["proposed", "proposed"]
    assert team.snapshot()["phase"] == "meeting"
    assert team.fakes["kidemli"].sent == []


async def test_begin_sends_each_task_to_its_worker(team):
    team.plan([("kidemli", "Giriş hatasını düzelt"), ("asistan", "README'yi güncelle")])
    await team.begin()
    assert team.fakes["kidemli"].sent == ["[GÖREV #1]\nGiriş hatasını düzelt"]
    assert team.fakes["asistan"].sent == ["[GÖREV #2]\nREADME'yi güncelle"]
    snap = team.snapshot()
    assert snap["phase"] == "working"
    assert by_id(team)["kidemli"]["state"] == "working" and by_id(team)["kidemli"]["task"] == 1
    assert by_id(team)["testci"]["state"] == "idle"


async def test_begin_can_start_only_some(team):
    team.plan([("gelistirici", "Kodu yaz"), ("testci", "Testi yaz")])
    await team.begin([1])
    assert team.fakes["gelistirici"].sent and team.fakes["testci"].sent == []
    assert [t.status for t in team.tasks] == ["running", "proposed"]
    assert team.snapshot()["phase"] == "working"


async def test_finished_task_is_reported_to_the_lead(team):
    await team.assign("gelistirici", "Kodu yaz")
    await finish(team, "gelistirici", TextDelta("Bakıyorum."), ToolUse("Edit", "app.py"), TextDelta("app.py düzeltildi."))
    task = team.tasks[0]
    assert (task.status, task.result) == ("done", "app.py düzeltildi.")
    report = team.fakes[LEAD].sent[-1]
    assert report.startswith("[EKİP RAPORU]") and "#1 Geliştirici — bitti" in report
    assert "app.py düzeltildi." in report and "Bakıyorum" not in report
    assert "Şu an çalışan kimse yok." in report
    assert by_id(team)["gelistirici"]["state"] == "idle"


async def test_lead_hears_nothing_until_everyone_is_done(team):
    await team.assign("gelistirici", "Kodu yaz")
    await team.assign("asistan", "Birinci")
    await team.assign("asistan", "İkinci")
    await finish(team, "gelistirici", TextDelta("Bitti."))
    await finish(team, "asistan", TextDelta("Birinci bitti."))
    assert team.fakes[LEAD].sent == [] and team.snapshot()["phase"] == "working"


async def two_finish_their_work(team):
    await team.assign("gelistirici", "Kodu yaz")
    await team.assign("testci", "Testi yaz")
    await finish(team, "gelistirici", TextDelta("Kod yazıldı."))
    await finish(team, "testci", TextDelta("Bir test kırmızı."))


async def test_workers_talk_it_over_before_the_lead_is_told(team):
    await two_finish_their_work(team)
    snap = team.snapshot()
    assert snap["phase"] == "review"
    assert snap["review"] == {"members": ["gelistirici", "testci"], "speaker": "gelistirici", "lines": []}
    opening = team.fakes["gelistirici"].sent[-1]
    assert opening.startswith("[EKİP TOPLANTISI]") and "Bir test kırmızı." in opening and "ilk sözü sen" in opening
    assert team.fakes[LEAD].sent == [] and team.fakes["testci"].sent == ["[GÖREV #2]\nTesti yaz"]

    await finish(team, "gelistirici", TextDelta("Kırmızı test benim değişikliğimden olabilir."))
    heard = team.fakes["testci"].sent[-1]
    assert "Geliştirici: Kırmızı test benim değişikliğimden olabilir." in heard and "Sıra sende, Testçi" in heard
    assert team.snapshot()["review"]["speaker"] == "testci"

    await finish(team, "testci", TextDelta("Evet, tarih biçimi değişmiş."))
    assert "Son söz sende, Geliştirici" in team.fakes["gelistirici"].sent[-1]
    assert team.fakes[LEAD].sent == []

    await finish(team, "gelistirici", TextDelta("Biçimi geri alıyoruz, anlaştık."))
    told = team.fakes[LEAD].sent[-1]
    assert team.snapshot()["phase"] == "working" and team.snapshot()["review"] is None  # the lead is now talking
    assert told.index("[EKİP RAPORU]") < told.index("[EKİP TOPLANTISI]")
    assert "#1 Geliştirici — bitti" in told and "Testçi: Evet, tarih biçimi değişmiş." in told
    assert told.count("Geliştirici:") == 2
    assert team.chat[-1]["meeting"] == [
        {"who": "gelistirici", "text": "Kırmızı test benim değişikliğimden olabilir."},
        {"who": "testci", "text": "Evet, tarih biçimi değişmiş."},
        {"who": "gelistirici", "text": "Biçimi geri alıyoruz, anlaştık."},
    ]


async def test_meeting_is_announced_to_the_browser_side(team):
    events = team.lead_events()
    await two_finish_their_work(team)
    for role in ("gelistirici", "testci", "gelistirici"):
        await finish(team, role, TextDelta("Tamam."))
    ended = await asyncio.wait_for(anext(events), 1)
    assert isinstance(ended, MeetingEnded) and len(ended.lines) == 3
    assert isinstance(await asyncio.wait_for(anext(events), 1), LeadTurn)


async def test_no_meeting_while_part_of_the_plan_is_still_to_start(team):
    team.plan([("gelistirici", "Kodu yaz"), ("testci", "Testi yaz")])
    await team.begin([1])
    await finish(team, "gelistirici", TextDelta("Kod yazıldı."))
    assert "Başlatılmayı bekleyen önerilmiş görevler: #2." in team.fakes[LEAD].sent[-1]
    await finish(team, LEAD, TextDelta("Testi başlatıyorum."))
    await team.begin([2])
    await finish(team, "testci", TextDelta("Testler geçti."))
    # Now both have worked on the same job, and both reports are on the table.
    assert team.snapshot()["phase"] == "review"
    assert "Kod yazıldı." in team.fakes["gelistirici"].sent[-1] and "Testler geçti." in team.fakes["gelistirici"].sent[-1]


async def test_separate_jobs_do_not_share_a_meeting(team):
    await team.assign("asistan", "README")
    await finish(team, "asistan", TextDelta("Güncellendi."))
    await finish(team, LEAD, TextDelta("Bitti."))
    await team.assign("kidemli", "Hata")
    await finish(team, "kidemli", TextDelta("Düzeltildi."))
    assert team.snapshot()["phase"] == "working" and team.fakes["asistan"].sent == ["[GÖREV #1]\nREADME"]


async def test_stopping_ends_the_meeting(team):
    await two_finish_their_work(team)
    await team.interrupt()
    await finish(team, "gelistirici", error=True)
    assert team.snapshot()["review"] is None and team.fakes[LEAD].sent == []
    assert by_id(team)["gelistirici"]["state"] == "idle"


async def test_reports_wait_while_the_lead_is_talking(team):
    await team.assign("asistan", "Dosyaları bul")
    await team.say("Bu arada takvimime bak")
    await finish(team, "asistan", TextDelta("Üç dosya buldum."))
    assert team.fakes[LEAD].sent == ["Bu arada takvimime bak"]
    await finish(team, LEAD, TextDelta("Bugün boşsun."))
    assert "Üç dosya buldum." in team.fakes[LEAD].sent[-1]


async def test_lead_turn_is_announced_before_a_report_turn(team):
    events = team.lead_events()
    await team.assign("asistan", "Dosyaları bul")
    await finish(team, "asistan", TextDelta("Buldum."))
    assert isinstance(await asyncio.wait_for(anext(events), 1), LeadTurn)


async def test_failed_task_is_reported_as_error(team):
    await team.assign("kidemli", "Derle")
    await finish(team, "kidemli", TextDelta("Derleme başarısız."), error=True)
    assert team.tasks[0].status == "error"
    assert by_id(team)["kidemli"]["state"] == "error"
    assert "#1 Kıdemli Geliştirici — HATA" in team.fakes[LEAD].sent[-1]


async def test_second_task_for_a_busy_worker_queues(team):
    await team.assign("asistan", "Birinci")
    await team.assign("asistan", "İkinci")
    assert [t.status for t in team.tasks] == ["running", "queued"]
    await finish(team, "asistan", TextDelta("Birinci bitti."))
    assert [t.status for t in team.tasks] == ["done", "running"]
    assert team.fakes["asistan"].sent[-1] == "[GÖREV #2]\nİkinci"


async def test_activity_follows_the_tool_in_use(team):
    await team.assign("testci", "Testleri çalıştır")
    team.fakes["testci"].push(ToolUse("Bash", "pytest -q"))
    await settle()
    agent = by_id(team)["testci"]
    assert agent["activity"] == "Bash: pytest -q" and agent["log"] == ["Bash: pytest -q"]


async def test_interrupt_stops_everyone_without_reporting(team):
    await team.assign("asistan", "Birinci")
    await team.assign("asistan", "İkinci")
    await team.interrupt()
    assert team.fakes["asistan"].interrupted
    await finish(team, "asistan", error=True)
    assert [t.status for t in team.tasks] == ["stopped", "stopped"]
    assert by_id(team)["asistan"]["state"] == "idle"
    assert team.fakes[LEAD].sent == []


async def test_unknown_worker_and_lead_are_refused(team):
    for to in ("patron", LEAD):
        with pytest.raises(TeamError):
            await team.assign(to, "iş")
    with pytest.raises(TeamError):
        await team.begin()


async def test_question_shows_until_the_user_answers(team):
    team.ask("Eski yedekleri sileyim mi?")
    assert team.snapshot()["question"] == "Eski yedekleri sileyim mi?"
    await team.say("Sil")
    assert team.snapshot()["question"] == ""


async def test_cancel_drops_the_plan(team):
    team.plan([("asistan", "Bir şey")])
    assert team.cancel() == 1 and team.tasks == [] and team.snapshot()["phase"] == "idle"


async def test_chat_keeps_what_was_said(team):
    await team.say("Selam")
    await finish(team, LEAD, TextDelta("Bakıyorum."), ToolUse("Read", "a.py"), TextDelta("Hazır."))
    assert team.chat == [{"you": "Selam", "reply": "Bakıyorum.\nHazır."}]


async def test_each_project_keeps_its_own_tasks_and_chat(team, tmp_path):
    first, second = tmp_path / "bir", tmp_path / "iki"
    first.mkdir()
    second.mkdir()
    await team.open(str(first))
    await team.say("Birinci proje")
    await team.assign("asistan", "Yarım kalacak iş")
    await team.open(str(second))
    assert team.tasks == [] and team.chat == []
    await team.open(str(first))
    assert team.chat[0]["you"] == "Birinci proje"
    # The process doing it was closed with the project, so it is no longer running.
    assert [(t.text, t.status) for t in team.tasks] == [("Yarım kalacak iş", "stopped")]


async def test_new_session_clears_the_project(team):
    await team.say("Selam")
    await team.assign("asistan", "iş")
    await team.new_session()
    assert team.tasks == [] and team.chat == []
    assert all(b.new_sessions == 1 for b in team.fakes.values())
    assert all(a["state"] == "idle" for a in team.snapshot()["agents"])


async def test_a_gemini_meeting_is_played_out_and_its_proposals_await_approval(tmp_path):
    asked = []

    async def meeter(members, reports, lead):
        asked.append(([m["id"] for m in members], reports, lead["id"]))
        return {"lines": [{"who": "testci", "text": "Geliştirici, tarih biçimi testi kırdı."},
                          {"who": "gelistirici", "text": "Haklısın, geri alıyorum."},
                          {"who": LEAD, "text": "Anlaştık."}],
                "decisions": ["Biçim geri alınacak."],
                "tasks": [{"to": "gelistirici", "text": "Tarih biçimini geri al."}, {"to": LEAD, "text": "x"}]}

    team = make_team(tmp_path, FakeBridge(), meeter=meeter, pace=0)
    await team.open(str(tmp_path))
    await settle()
    await two_finish_their_work(team)
    for _ in range(10):
        await settle()
    assert asked[0][0] == ["gelistirici", "testci"] and asked[0][2] == LEAD and len(asked[0][1]) == 2
    assert all(not s.startswith("[EKİP TOPLANTISI]") for s in team.fakes["gelistirici"].sent)  # no Claude tokens
    told = team.fakes[LEAD].sent[-1]
    assert "Testçi: Geliştirici, tarih biçimi testi kırdı." in told
    assert [(t.to, t.text, t.status) for t in team.tasks if t.status == "proposed"] == [
        ("gelistirici", "Tarih biçimini geri al.", "proposed")]
    assert team.chat[-1]["meeting"][-1] == {"who": LEAD, "text": "Anlaştık."}
    await team.close()
