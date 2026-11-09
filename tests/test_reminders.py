from datetime import datetime

import pytest

from assistant.reminders import PastTimeError, ReminderStore
from tools.reminder import main

NOW = datetime(2026, 11, 10, 10, 0)


def fixed():
    return NOW


class FakeScheduler:
    def __init__(self, fail=False):
        self.created = []
        self.deleted = []
        self.fail = fail

    def create(self, task_name, at, command):
        if self.fail:
            raise RuntimeError("Register-ScheduledTask failed")
        self.created.append((task_name, at, command))

    def delete(self, task_name):
        self.deleted.append(task_name)


@pytest.fixture
def fake():
    return FakeScheduler()


@pytest.fixture
def store(tmp_path, fake):
    return ReminderStore(tmp_path / "h.json", fake, now=fixed)


def test_add_persists_turkish_and_schedules(tmp_path, fake, store):
    r = store.add(datetime(2026, 11, 10, 18, 0), "Su iç, ğüşıöç İĞÜŞ")
    reloaded = ReminderStore(tmp_path / "h.json", fake, now=fixed).get(r.id)
    assert reloaded.text == "Su iç, ğüşıöç İĞÜŞ" and reloaded.at == datetime(2026, 11, 10, 18, 0)
    name, at, command = fake.created[0]
    assert name == r.id and at == datetime(2026, 11, 10, 18, 0) and command[-1] == r.id
    assert command[0].endswith("pythonw.exe") and command[1].endswith("remind.py")


def test_past_time_rejected(store, fake):
    with pytest.raises(PastTimeError):
        store.add(datetime(2026, 11, 10, 9, 0), "x")
    assert fake.created == [] and store.upcoming() == []


def test_failed_scheduling_keeps_no_record(tmp_path):
    s = ReminderStore(tmp_path / "h.json", FakeScheduler(fail=True), now=fixed)
    with pytest.raises(RuntimeError):
        s.add(datetime(2026, 11, 10, 18, 0), "x")
    assert s.upcoming() == []


def test_upcoming_excludes_done_and_past_sorted(tmp_path, fake, store):
    late = store.add(datetime(2026, 11, 12, 9, 0), "geç")
    early = store.add(datetime(2026, 11, 11, 9, 0), "erken")
    done = store.add(datetime(2026, 11, 11, 8, 0), "bitti")
    store.mark_done(done.id)
    assert [r.id for r in store.upcoming()] == [early.id, late.id]
    later = ReminderStore(tmp_path / "h.json", fake, now=lambda: datetime(2026, 11, 11, 12, 0))
    assert [r.id for r in later.upcoming()] == [late.id]


def test_delete_removes_task(store, fake):
    r = store.add(datetime(2026, 11, 10, 18, 0), "x")
    assert store.delete(r.id) is True
    assert fake.deleted == [r.id] and store.get(r.id) is None
    assert store.delete("yok") is False


def test_cli_add_list_delete(store, capsys):
    assert main(["add", "--at", "2026-11-10 18:30", "--text", "Nevka'yı ara"], store=store) == 0
    out = capsys.readouterr().out
    assert out.startswith("Kuruldu: ") and "2026-11-10 18:30" in out
    rid = out.split()[1]
    assert main(["list"], store=store) == 0
    assert f"{rid}  2026-11-10 18:30  Nevka'yı ara" in capsys.readouterr().out
    assert main(["delete", rid], store=store) == 0
    assert main(["delete", rid], store=store) == 1


def test_cli_exit_codes(tmp_path, store, capsys):
    assert main(["add", "--at", "2026-11-10 09:00", "--text", "x"], store=store) == 2
    assert "Bu zaman geçmişte" in capsys.readouterr().err
    failing = ReminderStore(tmp_path / "f.json", FakeScheduler(fail=True), now=fixed)
    assert main(["add", "--at", "2026-11-10 18:00", "--text", "x"], store=failing) == 3
    assert main(["add", "--at", "yarın akşam", "--text", "x"], store=store) == 2
