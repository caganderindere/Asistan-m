"""The office on the free models, as the server and Cuba see it: give work, chair a meeting.

Work and answers run in the background; Cuba hears the outcome later as `[EKİP RAPORU — …]` or
`[SÖZ — …]`, so a voice tool call never waits on a model.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from server.office_bus import Message, OfficeBus
from server.office_meeting import LiveMeeting
from server.omni import OmniClient
from server.team import ROLES
from server.terminal import TerminalCrew
from server.worker import OfficeWorker

logger = logging.getLogger(__name__)


class Office:
    MEMBERS = ("pazarlama", "icerik", "sosyal")

    def __init__(
        self,
        omni: OmniClient,
        bus: OfficeBus,
        crew_for: Callable[[str], TerminalCrew],
        tell: Callable[[str], Awaitable[None]],
        push: Callable[[str], Awaitable[None]],
        search: Callable[[str], Awaitable[dict]] | None = None,
    ) -> None:
        self._crew_for = crew_for
        self._tell = tell
        self._push = push
        self._where: dict[str, str] = {}  # member id → the project folder it is working in
        self._tasks: set[asyncio.Task] = set()
        self._meeting_folder = ""
        self.workers = {
            role.id: OfficeWorker(role, omni, bus, self.worker, search, self._activity)
            for role in ROLES if role.id in self.MEMBERS
        }
        self._meeting = LiveMeeting(self.worker, omni, bus, self._show_meeting)

    def worker(self, who: str) -> OfficeWorker | None:
        return self.workers.get(who)

    def _background(self, work: Awaitable[None]) -> None:
        task = asyncio.create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def idle(self) -> None:
        """Wait for everything running in the background (tests, shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _activity(self, who: str, what: str) -> None:
        folder = self._where.get(who)
        if folder is None:
            return
        crew = self._crew_for(folder)
        crew.office_work(who, what) if what else crew.office_rest(who)
        self._background(self._push(folder))

    async def give(self, who: str, task: str, folder: str) -> dict:
        worker = self.worker(who)
        if worker is None:
            return {"error": f"{who} ofis ekibinde değil; ofiste {', '.join(self.MEMBERS)} var. Kod işi terminale_ver ile."}
        if who in self._where:
            return {"error": f"{worker.role.name} şu an başka bir işte; bitince ver."}
        self._where[who] = folder
        self._crew_for(folder).office_work(who, "Görevi okuyor")
        await self._push(folder)

        async def work() -> None:
            try:
                report = await worker.run(task, Path(folder))
            except Exception as e:  # noqa: BLE001 - Cuba must always hear back
                logger.exception("office worker failed")
                report = f"HATA: {e}"
            finally:
                self._where.pop(who, None)
                self._crew_for(folder).office_rest(who)
                await self._push(folder)
            # Kept in the log and the feed too: with no voice session open, Cuba may not be there to hear it.
            worker.bus.post(Message(who, "lider", report, channel="rapor"))
            await self._tell(f"[EKİP RAPORU — {Path(folder).name}] {worker.role.name}: {report}")

        self._background(work())
        return {"ok": True, "not": "Ekip işe başladı; bitince [EKİP RAPORU] gelecek."}

    async def _show_meeting(self, state: dict | None) -> None:
        if self._meeting_folder:
            self._crew_for(self._meeting_folder).show_meeting(state)
            await self._push(self._meeting_folder)

    async def open_meeting(self, topic: str, members: list[str], folder: str) -> dict:
        if self._meeting.is_open:
            return {"error": "Zaten açık bir toplantı var; önce toplanti_kapat."}
        self._meeting_folder = folder
        return await self._meeting.open(topic, members)

    async def give_floor(self, who: str, question: str) -> dict:
        if not self._meeting.is_open:
            return {"error": "Açık toplantı yok."}
        worker = self.worker(who)
        if worker is None:
            return {"error": f"{who} ofis ekibinde değil."}

        async def speak() -> None:
            line = await self._meeting.give_floor(who, question)
            await self._tell(f"[SÖZ — {worker.role.name}] {line.get('text') or line.get('error', '')}")

        self._background(speak())
        return {"ok": True, "not": f"Söz verildi; cevap gelince [SÖZ — {worker.role.name}] olarak duyacaksın. Onun adına konuşma."}

    async def close_meeting(self) -> dict:
        await self.idle()  # let the last answer land before summing up
        result = await self._meeting.close()
        self._meeting_folder = ""
        return result
