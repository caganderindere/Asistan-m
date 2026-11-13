"""A meeting Cuba chairs live: Cuba gives someone the floor and that member really answers.

Each answer is one toolless model call with the topic and everything said so far, so members can
pick up on each other. The office plays the lines like any meeting: balloons and voices.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

from server.office_bus import Message, OfficeBus
from server.omni import OmniClient, OmniError

logger = logging.getLogger(__name__)

CHAIR = "lider"
SUMMARY = """Az önce biten toplantının konuşmasını okuyorsun. Konuşmada gerçekten alınan kararları ve gerçekten
ortaya çıkan işleri çıkar; konuşmada olmayan hiçbir şey ekleme. "kim" alanı katılımcılardan birinin kimliğidir:
{members}. Yalnızca şu JSON'u döndür:
{{"kararlar": ["..."], "gorevler": [{{"kim": "kimlik", "is": "..."}}]}}"""


class LiveMeeting:
    def __init__(
        self,
        workers: Callable[[str], object | None],
        omni: OmniClient,
        bus: OfficeBus,
        show: Callable[[dict | None], Awaitable[None]],
    ) -> None:
        self._workers = workers
        self._omni = omni
        self._bus = bus
        self._show = show
        self._topic = ""
        self._members: list[str] = []
        self._lines: list[dict] = []
        self._speaker = ""

    @property
    def is_open(self) -> bool:
        return bool(self._members)

    def _state(self) -> dict:
        names = {CHAIR: "Cuba", **{m: self._workers(m).role.name for m in self._members}}
        return {"members": list(self._members), "speaker": self._speaker, "lines": list(self._lines), "names": names}

    async def open(self, topic: str, members: list[str]) -> dict:
        unknown = [m for m in members if self._workers(m) is None]
        if unknown or not members:
            return {"error": f"Bu kişiler ofis ekibinde yok: {', '.join(unknown) or 'kimse seçilmedi'}."}
        self._topic, self._members, self._lines, self._speaker = topic, list(dict.fromkeys(members)), [], ""
        await self._show(self._state())
        return {"ok": True, "katilimcilar": self._members}

    def _say(self, who: str, text: str) -> dict:
        line = {"who": who, "text": text}
        self._lines.append(line)
        self._bus.post(Message(who, "toplanti", text, channel="toplanti"))
        return line

    async def give_floor(self, who: str, question: str) -> dict:
        if not self.is_open:
            return {"error": "Açık toplantı yok."}
        worker = self._workers(who)
        if worker is None or who not in self._members:
            return {"error": f"{who} bu toplantıda yok. Katılımcılar: {', '.join(self._members)}."}
        if question.strip():
            self._say(CHAIR, question.strip())
        self._speaker = who
        await self._show(self._state())
        said = "\n".join(f"{self._state()['names'].get(l['who'], l['who'])}: {l['text']}" for l in self._lines)
        try:
            answer = await worker.answer("Cuba", question, f"Toplantının konusu: {self._topic}\nŞimdiye kadar:\n{said}")
        except OmniError as e:
            self._speaker = ""
            await self._show(self._state())
            return {"error": f"{worker.role.name} cevap veremedi: {e}"}
        line = self._say(who, answer or "Şu an ekleyeceğim bir şey yok.")
        await self._show(self._state())
        return line

    async def close(self) -> dict:
        if not self.is_open:
            return {"error": "Açık toplantı yok."}
        talk = "\n".join(f"{l['who']}: {l['text']}" for l in self._lines)
        result: dict = {"kararlar": [], "gorevler": []}
        if self._lines:
            try:
                reply = await self._omni.chat([
                    {"role": "system", "content": SUMMARY.format(members=", ".join(self._members))},
                    {"role": "user", "content": f"Konu: {self._topic}\n{talk}"}])
                text = (reply.get("content") or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```")
                data = json.loads(text)
                result = {
                    "kararlar": [str(d) for d in data.get("kararlar", []) if str(d).strip()],
                    "gorevler": [{"kim": str(g.get("kim")), "is": str(g.get("is"))} for g in data.get("gorevler", [])
                                 if isinstance(g, dict) and g.get("kim") in self._members and g.get("is")],
                }
            except (OmniError, ValueError, AttributeError):
                logger.exception("meeting summary failed")
        self._topic, self._members, self._lines, self._speaker = "", [], [], ""
        await self._show(None)
        return result
