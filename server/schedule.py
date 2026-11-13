"""Work Cuba hands to a project's terminal later: "in 30 minutes, do this".

Waiting costs no tokens: the jobs sit in a file and a loop hands each to the
terminal when its time comes. A job whose time passed while the server was
off is never run on its own; it waits for Çağan to say run or delete.
"""

from __future__ import annotations

import datetime
import json
import logging
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

TIME_FORMAT = "%Y-%m-%d %H:%M"
LATE_AFTER = datetime.timedelta(minutes=2)  # later than this, the moment was missed: ask first
KEPT_DONE = 20

WAITING, ASK, DONE = "bekliyor", "soruluyor", "yapildi"


class Schedule:
    """Jobs: {id, at, folder, project, text, status, created, ran}."""

    def __init__(self, path: Path, clock: Callable[[], datetime.datetime] = datetime.datetime.now) -> None:
        self._path = path
        self._clock = clock
        self.jobs: list[dict] = []
        if path.exists():
            try:
                self.jobs = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                logger.warning("schedule file unreadable, starting empty")

    def add(self, at: datetime.datetime, folder: str, project: str, text: str) -> dict:
        if at <= self._clock():
            raise ValueError("Bu zaman geçmiş; ileri bir zaman ver.")
        job = {"id": max((j["id"] for j in self.jobs), default=0) + 1, "at": at.strftime(TIME_FORMAT),
               "folder": folder, "project": project, "text": text, "status": WAITING,
               "created": self._clock().strftime(TIME_FORMAT), "ran": ""}
        self.jobs.append(job)
        self._save()
        return job

    def view(self) -> list[dict]:
        """Waiting and asking jobs soonest first, then the last ones done."""
        open_jobs = sorted((j for j in self.jobs if j["status"] != DONE), key=lambda j: j["at"])
        return open_jobs + [j for j in reversed(self.jobs) if j["status"] == DONE]

    def remove(self, job_id: int) -> dict | None:
        job = self.get(job_id)
        if job is not None:
            self.jobs.remove(job)
            self._save()
        return job

    def get(self, job_id: int) -> dict | None:
        return next((j for j in self.jobs if j["id"] == job_id), None)

    def due(self) -> tuple[list[dict], list[dict]]:
        """(jobs to run now, jobs whose moment was missed and now need asking); both are marked."""
        now = self._clock()
        run, ask = [], []
        for job in self.jobs:
            if job["status"] != WAITING or datetime.datetime.strptime(job["at"], TIME_FORMAT) > now:
                continue
            if now - datetime.datetime.strptime(job["at"], TIME_FORMAT) > LATE_AFTER:
                job["status"] = ASK
                ask.append(job)
            else:
                self.mark_done(job, save=False)
                run.append(job)
        if run or ask:
            self._save()
        return run, ask

    def mark_done(self, job: dict, save: bool = True) -> None:
        job.update(status=DONE, ran=self._clock().strftime(TIME_FORMAT))
        done = [j for j in self.jobs if j["status"] == DONE]
        for old in done[:-KEPT_DONE]:
            self.jobs.remove(old)
        if save:
            self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self.jobs, ensure_ascii=False, indent=1), encoding="utf-8")


def parse_when(args: dict, now: datetime.datetime) -> datetime.datetime:
    """`dakika` from now, or `zaman` as YYYY-MM-DD HH:MM (HH:MM alone means the next such time)."""
    if args.get("dakika"):
        return now + datetime.timedelta(minutes=int(args["dakika"]))
    text = str(args.get("zaman", "")).strip()
    try:
        return datetime.datetime.strptime(text, TIME_FORMAT)
    except ValueError:
        pass
    try:
        clock = datetime.datetime.strptime(text, "%H:%M").time()
    except ValueError:
        raise ValueError("Zamanı 'dakika' ya da 'YYYY-MM-DD HH:MM' olarak ver.") from None
    at = datetime.datetime.combine(now.date(), clock)
    return at if at > now else at + datetime.timedelta(days=1)
