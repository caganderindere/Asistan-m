"""One-off reminders kept in a JSON file and fired by Windows Task Scheduler."""

from __future__ import annotations

import json
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from server.config import ROOT

TASK_PATH = "\\ClaudeSes\\"
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
REMIND_SCRIPT = ROOT / "tools" / "remind.py"


class PastTimeError(ValueError):
    pass


@dataclass
class Reminder:
    id: str
    at: datetime
    text: str
    created: datetime
    done: bool = False


class Scheduler(Protocol):
    def create(self, task_name: str, at: datetime, command: list[str]) -> None: ...

    def delete(self, task_name: str) -> None: ...


def _powershell(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


class WindowsScheduler:
    """Per-user tasks under \\ClaudeSes\\; no administrator rights needed."""

    def create(self, task_name: str, at: datetime, command: list[str]) -> None:
        executable, *args = command
        arguments = " ".join(f'"{a}"' if " " in a else a for a in args)
        # The time is built as a DateTime from numbers, so the Turkish date
        # format of the system locale never gets parsed.
        script = f"""
$action = New-ScheduledTaskAction -Execute '{executable}' -Argument '{arguments}' -WorkingDirectory '{ROOT}'
$trigger = New-ScheduledTaskTrigger -Once -At ([datetime]::new({at.year},{at.month},{at.day},{at.hour},{at.minute},0))
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskPath '{TASK_PATH}' -TaskName '{task_name}' -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
"""
        result = _powershell(script)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Register-ScheduledTask failed")

    def delete(self, task_name: str) -> None:
        _powershell(
            f"Unregister-ScheduledTask -TaskPath '{TASK_PATH}' -TaskName '{task_name}' "
            "-Confirm:$false -ErrorAction SilentlyContinue"
        )


class ReminderStore:
    def __init__(self, path: Path, scheduler: Scheduler, now: Callable[[], datetime] = datetime.now) -> None:
        self._path = path
        self._scheduler = scheduler
        self._now = now

    def add(self, at: datetime, text: str) -> Reminder:
        if at <= self._now():
            raise PastTimeError("Bu zaman geçmişte")
        reminder = Reminder(uuid.uuid4().hex[:8], at, text, self._now())
        # Schedule first: a record without a task would promise a reminder
        # that never fires.
        self._scheduler.create(reminder.id, at, [str(PYTHONW), str(REMIND_SCRIPT), reminder.id])
        self._save([*self._load(), reminder])
        return reminder

    def upcoming(self) -> list[Reminder]:
        now = self._now()
        return sorted((r for r in self._load() if not r.done and r.at > now), key=lambda r: r.at)

    def get(self, id: str) -> Reminder | None:
        return next((r for r in self._load() if r.id == id), None)

    def delete(self, id: str) -> bool:
        reminders = self._load()
        kept = [r for r in reminders if r.id != id]
        if len(kept) == len(reminders):
            return False
        self._scheduler.delete(id)
        self._save(kept)
        return True

    def mark_done(self, id: str) -> None:
        reminders = self._load()
        for r in reminders:
            if r.id == id:
                r.done = True
        self._save(reminders)

    def _load(self) -> list[Reminder]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return []
        return [
            Reminder(r["id"], datetime.fromisoformat(r["at"]), r["text"],
                     datetime.fromisoformat(r["created"]), r.get("done", False))
            for r in raw
        ]

    def _save(self, reminders: list[Reminder]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {**asdict(r), "at": r.at.isoformat(timespec="minutes"), "created": r.created.isoformat(timespec="seconds")}
            for r in reminders
        ]
        self._path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
