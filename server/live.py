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
from server.config import ROOT

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
        "name": "terminal_tus",
        "description": "Terminaldeki ekibe onay verir, reddeder ya da durdurur.",
        "parameters": {
            "type": "object",
            "properties": {"tus": {"type": "string", "enum": list(TERMINAL_KEYS)}},
            "required": ["tus"],
        },
    },
]}]


def project_block(listing: dict) -> str:
    """The projects Cuba can hand work in, the open one marked."""
    lines = [
        f"- {p['name']}: {p['path']}" + (" (şu an açık)" if p["path"] == listing.get("current") else "")
        for p in listing.get("projects", [])
    ]
    return "\n".join(lines) or "Henüz proje yok."


def live_prompt(
    memory_dir: Path = MEMORY_DIR, now: datetime.datetime | None = None, projects: dict | None = None
) -> str:
    return (
        f"{PROMPT.read_text(encoding='utf-8')}\n{now_line(now or datetime.datetime.now())}\n\n"
        f"# Projeler\n{project_block(projects or {})}\n\n"
        f"# Hafıza dosyaları\n{memory_block(memory_dir)}"
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
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self._voice}}},
            },
            "systemInstruction": {"parts": [{"text": live_prompt(self._memory_dir, projects=self._projects())}]},
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
                await self._event({"type": "user", "text": text})
            if text := content.get("outputTranscription", {}).get("text"):
                await self._event({"type": "cuba", "text": text})
            if content.get("interrupted"):
                await self._event({"type": "interrupted"})
            if content.get("turnComplete"):
                await self._event({"type": "turn_complete"})

    async def _run_tools(self, google, calls: list[dict]) -> None:
        replies = []
        for call in calls:
            name, args = call.get("name", ""), call.get("args") or {}
            await self._event({"type": "tool", "name": name, "summary": _summary(name, args)})
            replies.append({"id": call.get("id"), "name": name, "response": await self._tool(name, args)})
        await google.send(json.dumps({"toolResponse": {"functionResponses": replies}}, ensure_ascii=False))

    async def _tool(self, name: str, args: dict) -> dict:
        try:
            if name == "komut":
                return await self._runner(str(args.get("program", "")), [str(a) for a in args.get("args", [])])
            if name == "dosya_yaz" and args.get("ad") in MEMORY_FILES:
                self._memory_dir.mkdir(parents=True, exist_ok=True)
                (self._memory_dir / args["ad"]).write_text(str(args.get("icerik", "")), encoding="utf-8")
                return {"ok": True}
            if name == "terminale_ver" and str(args.get("talimat", "")).strip():
                listing = self._projects()
                folder = find_project(listing, str(args.get("proje", "")))
                if folder is None:
                    names = ", ".join(p["name"] for p in listing.get("projects", []))
                    return {"error": f"Hangi proje olduğu belli değil. Çağan'a sor. Projeler: {names}"}
                await self._hand_over(str(args["talimat"]).strip(), folder)
                return {"ok": True, "proje": folder, "not": "Ekip işe başladı; bitince [EKİP RAPORU] gelecek."}
            if name == "terminal_tus" and args.get("tus") in TERMINAL_KEYS:
                self._press(TERMINAL_KEYS[args["tus"]])
                return {"ok": True}
        except Exception as error:  # noqa: BLE001 - a failed tool is reported to Cuba, not raised
            logger.exception("live tool %s failed", name)
            return {"error": str(error)}
        return {"error": f"Bilinmeyen araç ya da eksik bilgi: {name}"}

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
