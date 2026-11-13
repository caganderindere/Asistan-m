import asyncio
import datetime

import pytest

from server.live import CubaTools
from server.schedule import ASK, DONE, WAITING, Schedule, parse_when

NOW = datetime.datetime(2026, 11, 13, 10, 0)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def test_job_runs_on_time_and_survives_restart(tmp_path):
    clock = Clock()
    schedule = Schedule(tmp_path / "z.json", clock)
    job = schedule.add(NOW + datetime.timedelta(minutes=30), "D:\cuba", "cuba", "testleri çalıştır")
    assert schedule.due() == ([], [])
    clock.now = NOW + datetime.timedelta(minutes=30, seconds=20)
    run, ask = schedule.due()
    assert [j["id"] for j in run] == [job["id"]] and ask == []
    again = Schedule(tmp_path / "z.json", clock)
    assert again.get(job["id"])["status"] == DONE
    assert again.due() == ([], [])


def test_missed_job_waits_for_an_answer(tmp_path):
    clock = Clock()
    schedule = Schedule(tmp_path / "z.json", clock)
    job = schedule.add(NOW + datetime.timedelta(minutes=5), "D:\cuba", "cuba", "x")
    clock.now = NOW + datetime.timedelta(hours=3)  # the server was off
    run, ask = schedule.due()
    assert run == [] and [j["id"] for j in ask] == [job["id"]]
    assert schedule.get(job["id"])["status"] == ASK
    assert schedule.due() == ([], [])  # asked once, not again


def test_past_time_is_refused_and_jobs_can_be_removed(tmp_path):
    schedule = Schedule(tmp_path / "z.json", Clock())
    with pytest.raises(ValueError):
        schedule.add(NOW - datetime.timedelta(minutes=1), "f", "p", "x")
    job = schedule.add(NOW + datetime.timedelta(minutes=1), "f", "p", "x")
    assert schedule.view()[0]["status"] == WAITING
    schedule.remove(job["id"])
    assert schedule.view() == []


def test_parse_when():
    assert parse_when({"dakika": 30}, NOW) == NOW + datetime.timedelta(minutes=30)
    assert parse_when({"zaman": "2026-11-14 09:00"}, NOW) == datetime.datetime(2026, 11, 14, 9, 0)
    assert parse_when({"zaman": "15:00"}, NOW) == datetime.datetime(2026, 11, 13, 15, 0)
    assert parse_when({"zaman": "08:00"}, NOW) == datetime.datetime(2026, 11, 14, 8, 0)
    with pytest.raises(ValueError):
        parse_when({"zaman": "yarın"}, NOW)


def test_cuba_schedules_lists_runs_and_deletes(tmp_path):
    handed = []

    async def hand_over(text, folder):
        handed.append((text, folder))

    listing = {"projects": [{"name": "cuba", "path": "D:\cuba"}]}
    tools = CubaTools(hand_over, lambda keys: None, tmp_path, projects=lambda: listing,
                      schedule=Schedule(tmp_path / "z.json"))

    async def go():
        made = await tools.run("zamanla", {"proje": "cuba", "talimat": "lint çalıştır", "dakika": 30})
        assert made["ok"]
        listed = await tools.run("zamanli_liste", {})
        assert listed["isler"][0]["text"] == "lint çalıştır"
        assert (await tools.run("zamanli_calistir", {"no": made["no"]}))["ok"]
        assert handed == [("lint çalıştır", "D:\cuba")]
        other = await tools.run("zamanla", {"proje": "cuba", "talimat": "y", "zaman": "23:59"})
        assert (await tools.run("zamanli_sil", {"no": other["no"]}))["ok"]
        assert (await tools.run("zamanli_sil", {"no": 99}))["error"]
        assert (await tools.run("zamanla", {"proje": "yok", "talimat": "y", "dakika": 5}))["error"]

    asyncio.run(go())
