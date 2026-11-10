"""Five Claude processes working as a team in one project at a time.

The user talks only to the lead. The lead hands work to the others through
tools/ekip.py, which calls plan/begin/assign/ask here; each finished task
is reported back to the lead as a message.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import deque
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from server.claude_events import TextDelta, ToolUse, TurnResult
from server.projects import project_slug
from server.session_store import SessionStore

logger = logging.getLogger(__name__)

LEAD = "lider"
REPORT_LIMIT = 4000
LOG_LINES = 12
KEPT_TASKS = 40
KEPT_TURNS = 50
RESTED_SECONDS = 600


@dataclass(frozen=True)
class Role:
    id: str
    name: str
    department: str
    duty: str


ROLES: tuple[Role, ...] = (
    Role(LEAD, "Takım Lideri", "Yönetim", "Çağan ile konuşur, işi planlar ve dağıtır, sonucu raporlar."),
    Role("kidemli", "Kıdemli Geliştirici", "Mühendislik",
         "Zor işler: mimari kararlar, karmaşık hatalar, çok dosyalı değişiklikler."),
    Role("gelistirici", "Geliştirici", "Mühendislik",
         "Orta işler: tek bir özellik, bilinen kalıpta kod, küçük düzeltmeler."),
    Role("testci", "Testçi", "Kalite", "Test yazar ve çalıştırır, başkalarının değişikliklerini inceler."),
    Role("asistan", "Asistan", "Destek",
         "Basit işler: dosya ve metin arama, yeniden adlandırma, doküman, biçimlendirme."),
)


@dataclass
class LeadTurn:
    """The lead started a turn the user did not ask for (a team report arrived)."""


@dataclass
class Task:
    id: int
    to: str
    text: str
    status: str  # proposed | queued | running | done | error | stopped
    result: str = ""


@dataclass
class Agent:
    role: Role
    model: str
    bridge: Any
    state: str = "idle"  # idle | working | error
    activity: str = ""
    since: float = 0.0
    task: Task | None = None
    interrupted: bool = False
    text: str = ""  # what it has said since its last tool call: its report when the turn ends
    log: deque[str] = field(default_factory=lambda: deque(maxlen=LOG_LINES))


BridgeFactory = Callable[[Role, str, str, SessionStore], Any]


class TeamError(ValueError):
    """A request the lead made that cannot be carried out; the text is shown to it."""


class Team:
    def __init__(
        self,
        models: Mapping[str, str],
        bridge_factory: BridgeFactory,
        data_dir: Path,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._models = models
        self._bridge_factory = bridge_factory
        self._data_dir = data_dir
        self._clock = clock
        self.project = ""
        self.agents: dict[str, Agent] = {}
        self.tasks: list[Task] = []
        self.chat: list[dict[str, str]] = []
        self.question = ""
        self._reports: list[str] = []
        self._watchers: list[asyncio.Task] = []
        self._lead_events: asyncio.Queue = asyncio.Queue()
        self._dirty = asyncio.Event()
        self._turn_open = False  # the lead's reply is being added to the last chat turn
        self._after_tool = False

    # ── Project ────────────────────────────────────────────────

    async def open(self, project: str) -> None:
        """Move the team into *project*, restoring what it did there before."""
        await self.close()
        self.project = project
        folder = self._folder()
        self.tasks = [Task(**t) for t in self._read(folder / "tasks.json")]
        for task in self.tasks:
            if task.status in ("queued", "running"):
                task.status = "stopped"
        self.chat = self._read(folder / "chat.json")
        self.question = ""
        # Nobody has just finished anything: the team starts out resting, not on a coffee break.
        now = self._clock() - RESTED_SECONDS
        self.agents = {
            role.id: Agent(
                role,
                self._models.get(role.id, ""),
                self._bridge_factory(
                    role, self._models.get(role.id, ""), project, SessionStore(folder / f"{role.id}.json")
                ),
                since=now,
            )
            for role in ROLES
        }
        self._watchers = [asyncio.create_task(self._watch(agent)) for agent in self.agents.values()]
        self._touch()

    async def start_lead(self) -> None:
        """Start the lead now so a missing or logged-out claude shows up at once."""
        await self.agents[LEAD].bridge.start()

    async def close(self) -> None:
        for watcher in self._watchers:
            watcher.cancel()
        for watcher in self._watchers:
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
        self._watchers = []
        for agent in self.agents.values():
            with contextlib.suppress(Exception):
                await agent.bridge.close()
        self.agents = {}
        self._reports = []
        self._turn_open = False
        while not self._lead_events.empty():
            self._lead_events.get_nowait()

    @property
    def busy(self) -> bool:
        return any(agent.state == "working" for agent in self.agents.values())

    # ── The user's side ────────────────────────────────────────

    async def say(self, text: str) -> None:
        self.question = ""
        self.chat.append({"you": text, "reply": ""})
        self._turn_open, self._after_tool = True, False
        lead = self.agents[LEAD]
        try:
            await self._send(lead, text)
        except OSError:
            lead.state, self._turn_open = "error", False
            self._touch()
            raise

    async def interrupt(self) -> None:
        """Stop everyone: the user said "dur"."""
        for task in self.tasks:
            if task.status == "queued":
                task.status = "stopped"
        self._reports = []
        working = [a for a in self.agents.values() if a.state == "working"]
        for agent in working:
            agent.interrupted = True
        await asyncio.gather(*(a.bridge.interrupt() for a in working), return_exceptions=True)
        self._save()
        self._touch()

    async def new_session(self) -> None:
        """Forget this project's conversations and tasks; files on disk stay."""
        await asyncio.gather(*(a.bridge.new_session() for a in self.agents.values()), return_exceptions=True)
        now = self._clock()
        for agent in self.agents.values():
            agent.state, agent.activity, agent.task, agent.since = "idle", "", None, now
            agent.interrupted = False
            agent.log.clear()
        self.tasks, self.chat, self._reports, self.question = [], [], [], ""
        self._turn_open = False
        self._save()
        self._touch()

    async def lead_events(self) -> AsyncIterator[Any]:
        while True:
            yield await self._lead_events.get()

    async def changes(self) -> AsyncIterator[dict]:
        """A fresh snapshot each time something visible changed."""
        while True:
            await self._dirty.wait()
            self._dirty.clear()
            yield self.snapshot()

    # ── The lead's side (tools/ekip.py) ────────────────────────

    def plan(self, items: list[tuple[str, str]]) -> list[Task]:
        """Replace the proposed plan; nothing starts until begin()."""
        if not items:
            raise TeamError("Plan boş: en az bir görev gerekli.")
        for to, text in items:
            self._check(to, text)
        self.tasks = [t for t in self.tasks if t.status != "proposed"]
        proposed = [self._add(to, text, "proposed") for to, text in items]
        self._save()
        self._touch()
        return proposed

    async def begin(self, ids: list[int] | None = None) -> list[Task]:
        """Start the proposed tasks the user approved (all of them by default)."""
        proposed = [t for t in self.tasks if t.status == "proposed" and (not ids or t.id in ids)]
        if not proposed:
            raise TeamError("Başlatılacak önerilmiş görev yok. Önce plan yap ya da 'ver' kullan.")
        for task in proposed:
            await self._dispatch(task)
        return proposed

    async def assign(self, to: str, text: str) -> Task:
        self._check(to, text)
        task = self._add(to, text, "queued")
        await self._dispatch(task)
        return task

    def cancel(self) -> int:
        """Drop the proposed plan."""
        before = len(self.tasks)
        self.tasks = [t for t in self.tasks if t.status != "proposed"]
        self._save()
        self._touch()
        return before - len(self.tasks)

    def ask(self, question: str) -> None:
        """The lead is waiting for the user's decision."""
        self.question = question.strip()
        self._touch()

    def snapshot(self) -> dict:
        now = self._clock()
        statuses = {t.status for t in self.tasks}
        if "proposed" in statuses and not statuses & {"running", "queued"}:
            phase = "meeting"  # a plan is on the table, waiting for the user's yes
        else:
            phase = "working" if self.busy else "idle"
        return {
            "type": "team",
            "project": self.project,
            "phase": phase,
            "question": self.question,
            "agents": [
                {
                    "id": a.role.id,
                    "name": a.role.name,
                    "department": a.role.department,
                    "duty": a.role.duty,
                    "model": a.model,
                    "state": a.state,
                    "activity": a.activity,
                    "seconds": round(now - a.since),
                    "task": a.task.id if a.task else None,
                    "log": list(a.log),
                }
                for a in self.agents.values()
            ],
            "tasks": [asdict(t) for t in self.tasks],
        }

    # ── Internals ──────────────────────────────────────────────

    def _check(self, to: str, text: str) -> None:
        workers = [r.id for r in ROLES if r.id != LEAD]
        if to not in workers:
            raise TeamError(f"'{to}' diye bir çalışan yok. Çalışanlar: {', '.join(workers)}.")
        if not text.strip():
            raise TeamError("Görev metni boş.")

    def _add(self, to: str, text: str, status: str) -> Task:
        task = Task(max((t.id for t in self.tasks), default=0) + 1, to, text.strip(), status)
        self.tasks.append(task)
        return task

    async def _dispatch(self, task: Task) -> None:
        agent = self.agents[task.to]
        if agent.state == "working":
            task.status = "queued"
        else:
            task.status = "running"
            agent.task = task
            agent.log.clear()
            try:
                await self._send(agent, f"[GÖREV #{task.id}]\n{task.text}")
            except OSError:
                logger.exception("task could not be sent to %s", agent.role.id)
                task.status, task.result = "error", "Claude başlatılamadı."
                agent.state, agent.task = "error", None
        self._save()
        self._touch()

    async def _send(self, agent: Agent, text: str) -> None:
        agent.state, agent.activity, agent.text = "working", "", ""
        agent.interrupted = False
        agent.since = self._clock()
        self._touch()
        await agent.bridge.send(text)

    async def _watch(self, agent: Agent) -> None:
        is_lead = agent.role.id == LEAD
        async for event in agent.bridge.events():
            if is_lead:
                self._lead_events.put_nowait(event)
            if isinstance(event, TextDelta):
                agent.text += event.text
                if is_lead:
                    self._record_reply(event.text)
            elif isinstance(event, ToolUse):
                agent.text = ""
                agent.activity = f"{event.name}: {event.summary}" if event.summary else event.name
                agent.log.append(agent.activity)
                if is_lead:
                    self._after_tool = True
                self._touch()
            elif isinstance(event, TurnResult):
                try:
                    await self._turn_ended(agent, event)
                except Exception:
                    logger.exception("turn end of %s could not be handled", agent.role.id)

    def _record_reply(self, text: str) -> None:
        if not self._turn_open:
            self.chat.append({"you": "", "reply": ""})
            self._turn_open, self._after_tool = True, False
        turn = self.chat[-1]
        turn["reply"] += f"\n{text}" if self._after_tool and turn["reply"] else text
        self._after_tool = False

    async def _turn_ended(self, agent: Agent, result: TurnResult) -> None:
        failed = result.is_error and not agent.interrupted
        agent.state, agent.activity = ("error" if failed else "idle"), ""
        agent.since = self._clock()
        if agent.role.id == LEAD:
            self._turn_open = False
            del self.chat[:-KEPT_TURNS]
        else:
            self._finish_task(agent, result)
            waiting = next((t for t in self.tasks if t.to == agent.role.id and t.status == "queued"), None)
            if waiting is not None:
                await self._dispatch(waiting)
        agent.interrupted = False
        self._save()
        self._touch()
        await self._deliver_reports()

    def _finish_task(self, agent: Agent, result: TurnResult) -> None:
        task, agent.task = agent.task, None
        if task is None:
            return
        task.result = (result.message or agent.text).strip()[:REPORT_LIMIT]
        if agent.interrupted:
            task.status = "stopped"  # the user stopped it; the lead is not told
            return
        task.status = "error" if result.is_error else "done"
        outcome = "HATA" if result.is_error else "bitti"
        self._reports.append(f"#{task.id} {agent.role.name} — {outcome}:\n{task.result or '(rapor yazmadı)'}")

    async def _deliver_reports(self) -> None:
        lead = self.agents.get(LEAD)
        if lead is None or not self._reports or lead.state == "working":
            return
        still = [
            f"{a.role.name} (#{a.task.id})" for a in self.agents.values() if a.task and a.state == "working"
        ]
        waiting = [f"#{t.id}" for t in self.tasks if t.status == "proposed"]
        lines = ["[EKİP RAPORU]", *self._reports]
        lines.append(f"Hâlâ çalışan: {', '.join(still)}." if still else "Şu an çalışan kimse yok.")
        if waiting:
            lines.append(f"Başlatılmayı bekleyen önerilmiş görevler: {', '.join(waiting)}.")
        self._reports = []
        self._lead_events.put_nowait(LeadTurn())
        try:
            await self._send(lead, "\n\n".join(lines))
        except OSError:
            logger.exception("report could not be sent to the lead")
            lead.state = "error"
            self._lead_events.put_nowait(TurnResult("", True, "Takım liderine ulaşılamadı."))
            self._touch()

    def _touch(self) -> None:
        self._dirty.set()

    def _folder(self) -> Path:
        return self._data_dir / "projects" / project_slug(self.project)

    @staticmethod
    def _read(path: Path) -> list:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return []
        return data if isinstance(data, list) else []

    def _save(self) -> None:
        if not self.project:
            return
        # Finished work scrolls away; anything still open is always kept.
        closed = [t for t in self.tasks if t.status in ("done", "error", "stopped")]
        drop = {t.id for t in closed[:-KEPT_TASKS]} if len(closed) > KEPT_TASKS else set()
        self.tasks = [t for t in self.tasks if t.id not in drop]
        folder = self._folder()
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in (("tasks.json", [asdict(t) for t in self.tasks]), ("chat.json", self.chat)):
            (folder / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
