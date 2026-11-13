"""Cuba's voice on the Gemini Live API: speech in, speech out, about half a second apart.

The browser streams microphone audio here (16 kHz PCM) and plays what comes
back (24 kHz PCM). This server holds the API key, carries both directions to
Google, runs Cuba's tools and hands real work to the terminal's Claude.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import datetime
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from server.gemini_bridge import MEMORY_DIR, MEMORY_FILES, TOOLS, memory_block, now_line, run_program
from server.life import KINDS, SITUATIONS, LifeLog, weather
from server.schedule import Schedule, parse_when
from server.config import ROOT
from server.usage import GEMINI

logger = logging.getLogger(__name__)

URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
PROMPT = ROOT / "ekip" / "CANLI.md"
TERMINAL_KEYS = {"evet": "\r", "hayir": "\x1b", "dur": "\x1b"}
MAX_FAILURES = 3

LIVE_TOOLS = [{"functionDeclarations": [
    *TOOLS[0]["functionDeclarations"],
    {
        "name": "terminale_ver",
        "description": "Kod, proje ya da dosya işini terminaldeki ekibe (Claude Code) verir.",
        "parameters": {
            "type": "object",
            "properties": {
                "proje": {"type": "string", "description": "İşin yapılacağı projenin adı, Projeler listesinden."},
                "talimat": {"type": "string", "description": "İşi eksiksiz anlatan tek paragraf."},
            },
            "required": ["proje", "talimat"],
        },
    },
    {
        "name": "hayat_kaydet",
        "description": "Çağan'ın günlük hayatından bir şeyi kaydeder: spor, araba yolculuğu, yemek, uyku, sağlık, iş, sosyal, alışveriş.",
        "parameters": {
            "type": "object",
            "properties": {
                "tur": {"type": "string", "enum": list(KINDS)},
                "detay": {"type": "string", "description": "Ne yaptı, kısaca: \"45 dk koşu, 6 km\", \"İzmir'e yola çıktı\"."},
                "sure_dk": {"type": "integer", "description": "Süresi dakika olarak, biliniyorsa."},
                "deger": {"type": "string", "description": "Ölçü varsa: kilo, mesafe, kalori, uyku saati, yakıt…"},
            },
            "required": ["tur", "detay"],
        },
    },
    {
        "name": "durum",
        "description": "Çağan'ın şu an ne yaptığını ayarlar; sen de ona göre konuşursun. Bitince \"yok\" ver.",
        "parameters": {
            "type": "object",
            "properties": {
                "durum": {"type": "string", "enum": [*SITUATIONS, "yok"]},
                "sure_dk": {"type": "integer", "description": "Ne kadar sürecek, biliniyorsa."},
            },
            "required": ["durum"],
        },
    },
    {
        "name": "hava",
        "description": "Bir yerin şu anki hava durumu, sonraki saatler, bugün ve yarın.",
        "parameters": {"type": "object", "properties": {"yer": {"type": "string"}}, "required": ["yer"]},
    },
    {
        "name": "ara",
        "description": "Güncel bir bilgiyi Google'da arar: haber, maç sonucu, trafik, fiyat, açılış saati, bir yer, bir olay.",
        "parameters": {"type": "object", "properties": {"soru": {"type": "string"}}, "required": ["soru"]},
    },
    {
        "name": "ise_al",
        "description": "Ekibe yeni bir üye alır: kendi masası, sesi ve uzmanlığı olan yeni bir alt ajan.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad": {"type": "string", "description": "Kısa unvan, örneğin Tasarımcı, Güvenlikçi, Veritabancı."},
                "gorev": {"type": "string", "description": "Ne iş yapacağı, tek cümle."},
                "model": {"type": "string", "enum": ["opus", "sonnet", "haiku"],
                          "description": "Zor iş için opus, olağan iş için sonnet, basit iş için haiku."},
            },
            "required": ["ad", "gorev"],
        },
    },
    {
        "name": "isten_cikar",
        "description": "Sonradan işe alınmış bir üyeyi ekipten çıkarır.",
        "parameters": {"type": "object", "properties": {"ad": {"type": "string"}}, "required": ["ad"]},
    },
    {
        "name": "zamanla",
        "description": "Bir işi ileri bir zamanda terminaldeki ekibe verilmek üzere kaydeder: \"30 dk sonra şunu yap\".",
        "parameters": {
            "type": "object",
            "properties": {
                "proje": {"type": "string", "description": "İşin yapılacağı projenin adı, Projeler listesinden."},
                "talimat": {"type": "string", "description": "İşi eksiksiz anlatan tek paragraf."},
                "dakika": {"type": "integer", "description": "Kaç dakika sonra; ya bu ya zaman."},
                "zaman": {"type": "string", "description": "YYYY-MM-DD HH:MM ya da yalnızca HH:MM."},
            },
            "required": ["proje", "talimat"],
        },
    },
    {
        "name": "zamanli_liste",
        "description": "Zamanlanmış işleri sıralar: bekleyenler, zamanı geçip onay bekleyenler, son yapılanlar.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "zamanli_sil",
        "description": "Zamanlanmış bir işi siler.",
        "parameters": {"type": "object", "properties": {"no": {"type": "integer"}}, "required": ["no"]},
    },
    {
        "name": "zamanli_calistir",
        "description": "Zamanlanmış bir işi hemen ekibe verir; zamanı geçmiş bir iş için Çağan \"yap\" derse kullan.",
        "parameters": {"type": "object", "properties": {"no": {"type": "integer"}}, "required": ["no"]},
    },
    {
        "name": "terminal_tus",
        "description": "Terminaldeki ekibe onay verir, reddeder ya da durdurur.",
        "parameters": {
            "type": "object",
            "properties": {"tus": {"type": "string", "enum": list(TERMINAL_KEYS)}},
            "required": ["tus"],
        },
    },
]}]

# The marketing team works on the free models in the office; Cuba gives it work and chairs its meetings.
OFFICE_TOOLS = [
    {
        "name": "ekibe_ver",
        "description": "Pazarlama ekibinden birine (pazarlama, icerik, sosyal) iş verir; bitince [EKİP RAPORU] gelir.",
        "parameters": {
            "type": "object",
            "properties": {
                "kim": {"type": "string", "enum": ["pazarlama", "icerik", "sosyal"]},
                "proje": {"type": "string", "description": "İşin yapılacağı projenin adı, Projeler listesinden."},
                "talimat": {"type": "string", "description": "İşi eksiksiz anlatan tek paragraf: ürün, hedef kitle, ton, çıktı."},
            },
            "required": ["kim", "proje", "talimat"],
        },
    },
    {
        "name": "toplanti_ac",
        "description": "Pazarlama ekibiyle toplantı açar; katılımcılar toplantı odasına geçer.",
        "parameters": {
            "type": "object",
            "properties": {
                "konu": {"type": "string"},
                "kisiler": {"type": "array", "items": {"type": "string", "enum": ["pazarlama", "icerik", "sosyal"]}},
                "proje": {"type": "string", "description": "Toplantının ilgili olduğu proje; yoksa açık proje."},
            },
            "required": ["konu", "kisiler"],
        },
    },
    {
        "name": "soz_ver",
        "description": "Toplantıda birine söz verir; cevabı [SÖZ — isim] olarak gelir. Onun adına konuşma.",
        "parameters": {
            "type": "object",
            "properties": {"kim": {"type": "string", "enum": ["pazarlama", "icerik", "sosyal"]},
                           "soru": {"type": "string"}},
            "required": ["kim", "soru"],
        },
    },
    {
        "name": "toplanti_kapat",
        "description": "Toplantıyı kapatır; kararları ve önerilen işleri döner.",
        "parameters": {"type": "object", "properties": {}},
    },
]
LIVE_TOOLS[0]["functionDeclarations"].extend(OFFICE_TOOLS)

def project_block(listing: dict) -> str:
    """The projects Cuba can hand work in, the open one marked."""
    lines = [
        f"- {p['name']}: {p['path']}" + (" (şu an açık)" if p["path"] == listing.get("current") else "")
        for p in listing.get("projects", [])
    ]
    return "\n".join(lines) or "Henüz proje yok."


def live_prompt(
    memory_dir: Path = MEMORY_DIR, now: datetime.datetime | None = None, projects: dict | None = None,
    diary: str = "",
) -> str:
    return (
        f"{PROMPT.read_text(encoding='utf-8')}\n{now_line(now or datetime.datetime.now())}\n\n"
        f"# Projeler\n{project_block(projects or {})}\n\n"
        f"# Hafıza dosyaları\n{memory_block(memory_dir)}"
        + (f"\n\n# Son günlük sayfan\n{diary}" if diary else "")
    )


def find_project(listing: dict, wanted: str) -> str | None:
    """The folder of the project Çağan named: by path, by exact name, or by the one name that contains it."""
    wanted = wanted.strip().strip('"').casefold()
    if not wanted:
        return None
    projects = listing.get("projects", [])
    for project in projects:
        if project["path"].casefold().rstrip("\\") == wanted.rstrip("\\"):
            return project["path"]
    exact = [p["path"] for p in projects if p["name"].casefold() == wanted]
    if len(exact) == 1:
        return exact[0]
    close = [p["path"] for p in projects if wanted in p["name"].casefold()]
    return close[0] if len(close) == 1 else None


Hand = Callable[[str, str], Awaitable[None]]  # gives the terminal's Claude an instruction, in a project folder
Keys = Callable[[str], None]  # presses keys in the terminal


class CubaTools:
    """What Cuba can do, wherever Çağan talks to it from: the voice, Telegram."""

    def __init__(
        self,
        hand_over: Hand,
        press: Keys,
        memory_dir: Path = MEMORY_DIR,
        runner: Callable = run_program,
        projects: Callable[[], dict] = dict,
        hire: Callable[..., Awaitable[dict]] | None = None,
        fire: Callable[[str], Awaitable[dict]] | None = None,
        life: LifeLog | None = None,
        search: Callable[[str], Awaitable[dict]] | None = None,
        notify: Callable[[dict], None] = lambda message: None,
        schedule: Schedule | None = None,
        office=None,
    ) -> None:
        self._hand_over = hand_over
        self.office = office  # server/office.py: the marketing team on the free models
        self.schedule = schedule
        self._press = press
        self._hire = hire
        self._fire = fire
        self.life = life
        self._search = search
        self._notify = notify  # tells the page what changed: Çağan's situation, a new log entry
        self.memory_dir = memory_dir
        self._runner = runner
        self.projects = projects  # the project listing, as the browser gets it

    async def _office(self, name: str, args: dict) -> dict:
        if self.office is None:
            return {"error": "Ofis ekibi çalışmıyor: OmniRoute anahtarı yok."}
        if name == "soz_ver":
            return await self.office.give_floor(str(args.get("kim", "")), str(args.get("soru", "")))
        if name == "toplanti_kapat":
            return await self.office.close_meeting()
        listing = self.projects()
        wanted = str(args.get("proje", "")).strip()
        folder = find_project(listing, wanted) if wanted else listing.get("current")
        if folder is None:
            names = ", ".join(p["name"] for p in listing.get("projects", []))
            return {"error": f"Hangi proje olduğu belli değil. Çağan'a sor. Projeler: {names}"}
        if name == "toplanti_ac":
            return await self.office.open_meeting(str(args.get("konu", "")), [str(k) for k in args.get("kisiler", [])], folder)
        if not str(args.get("talimat", "")).strip():
            return {"error": "Talimat boş."}
        return await self.office.give(str(args.get("kim", "")), str(args["talimat"]).strip(), folder)

    async def run(self, name: str, args: dict) -> dict:
        try:
            if name == "komut":
                return await self._runner(str(args.get("program", "")), [str(a) for a in args.get("args", [])])
            if name == "dosya_yaz" and args.get("ad") in MEMORY_FILES:
                self.memory_dir.mkdir(parents=True, exist_ok=True)
                (self.memory_dir / args["ad"]).write_text(str(args.get("icerik", "")), encoding="utf-8")
                return {"ok": True}
            if name == "terminale_ver" and str(args.get("talimat", "")).strip():
                listing = self.projects()
                folder = find_project(listing, str(args.get("proje", "")))
                if folder is None:
                    names = ", ".join(p["name"] for p in listing.get("projects", []))
                    return {"error": f"Hangi proje olduğu belli değil. Çağan'a sor. Projeler: {names}"}
                await self._hand_over(str(args["talimat"]).strip(), folder)
                return {"ok": True, "proje": folder, "not": "Ekip işe başladı; bitince [EKİP RAPORU] gelecek."}
            if name in ("ekibe_ver", "toplanti_ac", "soz_ver", "toplanti_kapat"):
                return await self._office(name, args)
            if name == "hayat_kaydet" and self.life is not None and str(args.get("detay", "")).strip():
                entry = self.life.add(str(args.get("tur", "")), str(args["detay"]), args.get("sure_dk"),
                                      str(args.get("deger") or ""))
                self._notify({"type": "life", "entry": entry})
                return {"ok": True, "kayit": entry, "son_yedi_gun": self.life.week()}
            if name == "durum" and self.life is not None:
                state = self.life.set_situation(str(args.get("durum", "")), args.get("sure_dk"))
                self._notify({"type": "situation", "situation": state})
                return {"ok": True, "durum": state or "yok"}
            if name == "hava" and str(args.get("yer", "")).strip():
                return await weather(str(args["yer"]))
            if name == "ara" and self._search is not None and str(args.get("soru", "")).strip():
                return await self._search(str(args["soru"]))
            if name == "ise_al" and self._hire is not None:
                return await self._hire(str(args.get("ad", "")), str(args.get("gorev", "")), str(args.get("model") or "sonnet"))
            if name == "isten_cikar" and self._fire is not None:
                return await self._fire(str(args.get("ad", "")))
            if name.startswith("zaman") and self.schedule is not None:
                return await self._scheduled(name, args)
            if name == "terminal_tus" and args.get("tus") in TERMINAL_KEYS:
                self._press(TERMINAL_KEYS[args["tus"]])
                return {"ok": True}
        except Exception as error:  # noqa: BLE001 - a failed tool is reported to Cuba, not raised
            logger.exception("cuba tool %s failed", name)
            return {"error": str(error)}
        return {"error": f"Bilinmeyen araç ya da eksik bilgi: {name}"}

    async def _scheduled(self, name: str, args: dict) -> dict:
        if name == "zamanla" and str(args.get("talimat", "")).strip():
            listing = self.projects()
            folder = find_project(listing, str(args.get("proje", "")))
            if folder is None:
                names = ", ".join(p["name"] for p in listing.get("projects", []))
                return {"error": f"Hangi proje olduğu belli değil. Çağan'a sor. Projeler: {names}"}
            try:
                at = parse_when(args, datetime.datetime.now())
                project = next((p["name"] for p in listing.get("projects", []) if p["path"] == folder), folder)
                job = self.schedule.add(at, folder, project, str(args["talimat"]).strip())
            except ValueError as error:
                return {"error": str(error)}
            self._notify({"type": "schedule", "jobs": self.schedule.view()})
            return {"ok": True, "no": job["id"], "zaman": job["at"]}
        if name == "zamanli_liste":
            return {"isler": [{k: j[k] for k in ("id", "at", "project", "text", "status")} for j in self.schedule.view()]}
        job = self.schedule.get(int(args.get("no") or 0))
        if job is None:
            return {"error": "Bu numarada zamanlanmış iş yok."}
        if name == "zamanli_sil":
            self.schedule.remove(job["id"])
        elif name == "zamanli_calistir":
            self.schedule.mark_done(job)
            await self._hand_over(job["text"], job["folder"])
        else:
            return {"error": f"Bilinmeyen araç: {name}"}
        self._notify({"type": "schedule", "jobs": self.schedule.view()})
        return {"ok": True}

    def prompt(self, diary: str = "") -> str:
        text = live_prompt(self.memory_dir, projects=self.projects(), diary=diary)
        return f"{text}\n\n{self.life.prompt()}" if self.life is not None else text


class LiveHub:
    """At most one live conversation: the browser tab that has the microphone."""

    def __init__(
        self,
        api_key: str,
        model: str,
        voice: str,
        hand_over: Hand,
        press: Keys,
        connect: Callable = websockets.connect,
        memory_dir: Path = MEMORY_DIR,
        runner: Callable = run_program,
        projects: Callable[[], dict] = dict,
        heard: Callable[[str, str], None] | None = None,
        diary: Callable[[], str] = str,
        tools: CubaTools | None = None,
    ) -> None:
        self._key = api_key
        self._model = model
        self._voice = voice
        self._hand_over = hand_over
        self._press = press
        self._connect = connect
        self._memory_dir = memory_dir
        self._runner = runner
        self._projects = projects  # the project listing, as the browser gets it
        self.tools = tools or CubaTools(hand_over, press, memory_dir, runner, projects)
        self._heard = heard  # gets each finished line: ("Çağan" | "Cuba", text)
        self._diary = diary  # yesterday's diary page, so Cuba remembers it
        self._said = {"Çağan": "", "Cuba": ""}  # the current turn's words, coming in pieces
        self._google = None  # the open Google session
        self._browser: WebSocket | None = None
        self._handle = ""  # lets a dropped session resume where it was

    @property
    def available(self) -> bool:
        return bool(self._key)

    @property
    def active(self) -> bool:
        return self._google is not None

    async def tell(self, text: str) -> None:
        """Give Cuba something to say: a team report, a permission prompt, a welcome back."""
        if self._google is not None:
            await self._google.send(json.dumps(
                {"clientContent": {"turns": [{"role": "user", "parts": [{"text": text}]}], "turnComplete": True}},
                ensure_ascii=False,
            ))

    async def serve(self, browser: WebSocket) -> None:
        """Carry one browser conversation until the browser leaves; Google sessions are renewed as needed."""
        if self._browser is not None:
            with contextlib.suppress(Exception):
                await self._browser.close()
        self._browser = browser
        failures = 0
        try:
            while self._browser is browser:
                try:
                    async with self._connect(f"{URL}?key={self._key}", max_size=None) as google:
                        await google.send(json.dumps({"setup": self._setup()}, ensure_ascii=False))
                        await google.recv()  # setupComplete
                        self._google = google
                        failures = 0
                        await self._event({"type": "ready"})
                        done = await self._pump(browser, google)
                    if done:
                        return
                except WebSocketDisconnect:
                    return
                except (OSError, websockets.WebSocketException) as error:
                    logger.warning("live session dropped: %s", error)
                    failures += 1
                    if failures >= MAX_FAILURES:
                        await self._event({"type": "failed", "message": "Gemini Live'a bağlanılamadı."})
                        return
                    await self._event({"type": "error", "message": "Gemini Live bağlantısı koptu, yeniden bağlanıyorum."})
                    await asyncio.sleep(1)
                finally:
                    self._google = None
        finally:
            if self._browser is browser:
                self._browser = None

    def _setup(self) -> dict:
        setup = {
            "model": f"models/{self._model}",
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {
                    "voiceName": self._voice() if callable(self._voice) else self._voice}}},
            },
            "systemInstruction": {"parts": [{"text": self.tools.prompt(self._diary())}]},
            "tools": LIVE_TOOLS,
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
            # Long talks stay quick: old turns are compressed rather than piling up.
            "contextWindowCompression": {"slidingWindow": {}},
            "sessionResumption": {"handle": self._handle} if self._handle else {},
        }
        return setup

    async def _pump(self, browser: WebSocket, google) -> bool:
        """Run both directions; True when the browser left, False when Google ended the session."""
        up = asyncio.create_task(self._upstream(browser, google))
        down = asyncio.create_task(self._downstream(google))
        finished, pending = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if up in finished:
            with contextlib.suppress(Exception):
                up.result()
            return True
        return False

    async def _upstream(self, browser: WebSocket, google) -> None:
        while True:
            message = await browser.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes"):
                await google.send(json.dumps({"realtimeInput": {"audio": {
                    "data": base64.b64encode(message["bytes"]).decode(), "mimeType": "audio/pcm;rate=16000",
                }}}))
            elif message.get("text"):
                data = json.loads(message["text"])
                if data.get("type") == "text" and data.get("text"):
                    await google.send(json.dumps({"realtimeInput": {"text": data["text"]}}, ensure_ascii=False))

    async def _downstream(self, google) -> None:
        async for raw in google:
            message = json.loads(raw)
            if update := message.get("sessionResumptionUpdate"):
                if update.get("resumable") and update.get("newHandle"):
                    self._handle = update["newHandle"]
            GEMINI.add(message.get("usageMetadata"))
            if "goAway" in message:
                return  # the session is about to end; reconnect with the handle
            if call := message.get("toolCall"):
                await self._run_tools(google, call.get("functionCalls", []))
            content = message.get("serverContent")
            if not content:
                continue
            for part in content.get("modelTurn", {}).get("parts", []):
                if data := part.get("inlineData", {}).get("data"):
                    await self._audio(base64.b64decode(data))
            if text := content.get("inputTranscription", {}).get("text"):
                self._said["Çağan"] += text
                await self._event({"type": "user", "text": text})
            if text := content.get("outputTranscription", {}).get("text"):
                self._said["Cuba"] += text
                await self._event({"type": "cuba", "text": text})
            if content.get("interrupted"):
                await self._event({"type": "interrupted"})
            if content.get("turnComplete"):
                self._log_turn()
                await self._event({"type": "turn_complete"})

    async def _run_tools(self, google, calls: list[dict]) -> None:
        replies = []
        for call in calls:
            name, args = call.get("name", ""), call.get("args") or {}
            await self._event({"type": "tool", "name": name, "summary": _summary(name, args)})
            replies.append({"id": call.get("id"), "name": name, "response": await self._tool(name, args)})
        await google.send(json.dumps({"toolResponse": {"functionResponses": replies}}, ensure_ascii=False))

    async def _tool(self, name: str, args: dict) -> dict:
        return await self.tools.run(name, args)

    def _log_turn(self) -> None:
        for who, text in self._said.items():
            if text.strip() and self._heard is not None:
                self._heard(who, text)
        self._said = {"Çağan": "", "Cuba": ""}

    async def _audio(self, pcm: bytes) -> None:
        if self._browser is not None:
            with contextlib.suppress(Exception):
                await self._browser.send_bytes(pcm)

    async def _event(self, event: dict) -> None:
        if self._browser is not None:
            with contextlib.suppress(Exception):
                await self._browser.send_json(event)


def _summary(name: str, args: dict) -> str:
    if name == "terminale_ver":
        return f"{args.get('proje', '')}: {args.get('talimat', '')}"[:80]
    if name == "komut":
        return " ".join([str(args.get("program", "")), *map(str, args.get("args", []))])[:80]
    return str(args.get("ad") or args.get("tus") or "")
