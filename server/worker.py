"""An office worker on the free models: a role, a short memory of the office talk, and tools.

A task runs as a loop of model calls; each tool call is answered and the model goes on until it
reports. Asking a colleague is a tool too: the colleague answers in one toolless call, so a chain of
questions always ends there. Limits keep the free quota from burning away.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from server.office_bus import Message, OfficeBus
from server.omni import OmniClient, OmniError
from server.prompts import office_prompt
from server.team import Role

logger = logging.getLogger(__name__)

MAX_CALLS = 12
MAX_MESSAGES = 4
LINE_CHARS = 300
READ_CHARS = 20_000
OUTPUT_DIR = "pazarlama"
ANSWER_RULE = ("Bir ekip arkadaşın sana soru soruyor ya da toplantıda söz sende. Kendi uzmanlığından, en çok iki cümleyle, "
               "düz konuşma diliyle cevap ver. Bilmediğin şeyi uydurma; gerçekten gördüğün sorunu söyle, nezaketen onaylama.")


def _tool(name: str, description: str, **params: str) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": {p: {"type": "string", "description": d} for p, d in params.items()},
                       "required": list(params)},
    }}


TOOLS = [
    _tool("dosya_oku", "Projedeki bir dosyayı okur.", yol="Proje klasörüne göre yol."),
    _tool("dosya_yaz", "pazarlama/ altına bir dosyanın tamamını yazar.", yol="pazarlama/ ile başlayan yol.", icerik="Dosya içeriği."),
    _tool("mesaj_at", "Bir ekip arkadaşına soru sorar; cevabı döner.", kime="Kimlik: pazarlama, icerik ya da sosyal.",
          metin="Soru ya da mesaj."),
    _tool("rapor_ver", "İşi bitirir; metin liderin okuyacağı rapordur.", metin="Rapor."),
]
SEARCH_TOOL = _tool("web_ara", "Web'de güncel bilgi arar.", soru="Aranacak soru.")


class OfficeWorker:
    def __init__(
        self,
        role: Role,
        omni: OmniClient,
        bus: OfficeBus,
        colleagues: Callable[[str], OfficeWorker | None],
        search: Callable[[str], Awaitable[dict]] | None = None,
        on_activity: Callable[[str, str], None] = lambda who, what: None,
    ) -> None:
        self.role = role
        self.omni = omni
        self.bus = bus
        self._colleagues = colleagues
        self._search = search
        self._on_activity = on_activity

    def _system(self) -> str:
        talk = "\n".join(f"{m.sender} → {m.to}: {m.text}" for m in self.bus.recent(self.role.id))
        return office_prompt(self.role) + (f"\n\n# Ofiste son konuşulanlar\n{talk}" if talk else "")

    async def run(self, task: str, folder: Path) -> str:
        """Do *task* in the project at *folder*; the report, or one starting with "HATA" when it could not."""
        tools = [*TOOLS, SEARCH_TOOL] if self._search else TOOLS
        messages = [{"role": "system", "content": self._system()}, {"role": "user", "content": task}]
        sent = 0
        try:
            for _ in range(MAX_CALLS):
                reply = await self.omni.chat(messages, tools)
                calls = reply.get("tool_calls") or []
                if not calls:
                    return (reply.get("content") or "").strip() or "HATA: Model boş cevap verdi."
                messages.append({"role": "assistant", "content": reply.get("content"), "tool_calls": calls})
                for call in calls:
                    name = call["function"]["name"]
                    try:
                        args = json.loads(call["function"].get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    if name == "rapor_ver":
                        return str(args.get("metin", "")).strip() or "Rapor boş."
                    self._on_activity(self.role.id, f"{name}: {next(iter(args.values()), '')}"[:80])
                    if name == "mesaj_at":
                        sent += 1
                        result = await self._ask(args, sent)
                    else:
                        result = await self._use(name, args, folder)
                    messages.append({"role": "tool", "tool_call_id": call.get("id", name), "content": result})
            return f"HATA: {MAX_CALLS} adımda bitmedi; iş yarım kaldı."
        except OmniError as e:
            return f"HATA: {e}"
        finally:
            self._on_activity(self.role.id, "")

    async def answer(self, sender: str, question: str, context: str = "") -> str:
        """One short answer to *sender*, without tools: what a colleague or a meeting hears."""
        prompt = f"{context}\n\n{sender} soruyor: {question}" if context else f"{sender} soruyor: {question}"
        reply = await self.omni.chat(
            [{"role": "system", "content": f"{self._system()}\n\n{ANSWER_RULE}"}, {"role": "user", "content": prompt}])
        return (reply.get("content") or "").strip()[:LINE_CHARS]

    async def _ask(self, args: dict, sent: int) -> str:
        if sent > MAX_MESSAGES:
            return f"HATA: Bu görevde en çok {MAX_MESSAGES} mesaj atabilirsin; işine devam et."
        who, text = str(args.get("kime", "")).strip(), str(args.get("metin", "")).strip()
        colleague = self._colleagues(who)
        if colleague is None or who == self.role.id or not text:
            return f"HATA: '{who}' diye bir ekip arkadaşı yok ya da mesaj boş."
        self.bus.post(Message(self.role.id, who, text))
        try:
            answer = await colleague.answer(self.role.id, text)
        except OmniError as e:
            return f"HATA: {who} cevap veremedi: {e}"
        self.bus.post(Message(who, self.role.id, answer))
        return answer

    async def _use(self, name: str, args: dict, folder: Path) -> str:
        root = folder.resolve()
        path = (root / str(args.get("yol", ""))).resolve()
        if name == "dosya_oku":
            if not path.is_relative_to(root) or not path.is_file():
                return "HATA: Dosya yok ya da proje dışında."
            return path.read_text(encoding="utf-8", errors="replace")[:READ_CHARS]
        if name == "dosya_yaz":
            if not path.is_relative_to(root / OUTPUT_DIR):
                return f"HATA: Yalnızca {OUTPUT_DIR}/ altına yazabilirsin."
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(args.get("icerik", "")), encoding="utf-8")
            return f"Yazıldı: {path.relative_to(root).as_posix()}"
        if name == "web_ara" and self._search is not None:
            try:
                return json.dumps(await self._search(str(args.get("soru", ""))), ensure_ascii=False)[:READ_CHARS]
            except Exception:  # noqa: BLE001 - a failed search is an answer the model can work with
                logger.exception("search failed")
                return "HATA: Arama yapılamadı."
        return f"HATA: '{name}' diye bir araç yok."
