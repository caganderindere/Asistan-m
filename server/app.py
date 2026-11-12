"""HTTP + WebSocket server joining the browser, Claude, Whisper and Edge TTS."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime
import json
import logging
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from server.claude_events import TextDelta, ToolUse, TurnResult
from server.config import ROOT, Config
from server.gemini_bridge import MissingKey
from server.projects import ProjectList, project_name
from server.sentences import SentenceSplitter
from server.stt import is_meaningful
from server.team import LeadTurn, MeetingEnded, Team, TeamError
from server.gemini_bridge import MEMORY_DIR, MEMORY_FILES
from server.live import LiveHub
from server.meeting import hold_meeting
from server.memory import ConversationLog, Diary, ensure_profile
from server.supervisor import Supervisor
from server.terminal import (
    AGENT_TOOLS, LEAD_DESK, PERMISSION_LINE, ROLE_NAMES, Terminal, TerminalCrew, TerminalPool, folder_key,
)
from server.usage import GEMINI, ClaudeMeter

logger = logging.getLogger(__name__)

BRIEFING_PROMPT = "Günün planını kısaca özetle."
# The spots in web/office.js; "" sends someone back to their own routine.
OFFICE_PLACES = {"desk", "meeting", "coffee", "sofa", "visit", ""}
OFFICE_PEOPLE = {"lider", "kidemli", "gelistirici", "testci", "asistan", "cagan"}
LOCAL_HOSTS = ("127.0.0.1", "localhost")
USAGE_EVERY_S = 30
DIARY_EVERY_S = 600
MEETING_PACE_S = 3.5  # a line of the meeting every few seconds, so it can be followed
DUTIES = {
    "kidemli": "zor mimari ve kritik kod", "gelistirici": "kodu yazar", "testci": "test eder ve doğrular",
    "asistan": "belge, araştırma ve küçük işler",
}
CLAUDE_MISSING = (
    "Claude Code bulunamadı ya da giriş yapılmamış. Bir terminalde 'claude' yazıp giriş yapın."
)

Synth = Callable[[str, str], Awaitable[bytes]]


def greeting(hour: int) -> str:
    """What Cuba says when the user starts talking and the day's briefing is already done."""
    if hour < 5 or hour >= 22:
        return "Geç saatte de buradayım efendim, dinliyorum."
    if hour < 12:
        return "Günaydın efendim, dinliyorum."
    if hour < 18:
        return "Buyurun efendim, dinliyorum."
    return "İyi akşamlar efendim, dinliyorum."


class _Clients:
    """The single active browser tab; a newer tab replaces the older one."""

    def __init__(self) -> None:
        self.active: WebSocket | None = None
        self._lock = asyncio.Lock()

    async def send(self, message: dict, ws: WebSocket | None = None) -> None:
        target = ws or self.active
        if target is None:
            return
        async with self._lock:
            with contextlib.suppress(Exception):
                await target.send_json(message)


def create_app(
    config: Config,
    team: Team,
    projects: ProjectList,
    transcriber,
    synth: Synth,
    data_dir: Path = ROOT / "data",
    web_dir: Path = ROOT / "web",
    allowed_hosts: tuple[str, ...] = LOCAL_HOSTS,
    token: str = "",
    terminal: Terminal | None = None,
    supervisor: Supervisor | None = None,
    live: LiveHub | None = None,
    terminals: TerminalPool | None = None,
    ask=None,
    telegram=None,
    remote_hosts: tuple[str, ...] = (),
    memory_dir: Path = MEMORY_DIR,
    claude_meter: ClaudeMeter | None = None,
) -> FastAPI:
    clients = _Clients()
    if terminals is None and terminal is not None:
        terminals = TerminalPool(lambda cwd: terminal)  # one terminal, whatever the project
    crews: dict[str, TerminalCrew] = {}  # one office crew per project terminal
    boss = supervisor or Supervisor(None, data_dir / "terminal" / "outputs.json")
    places: dict[str, str] = {}  # who was sent where; the rest follow their own routine
    talk = ConversationLog(data_dir / "konusmalar")
    diary = Diary(memory_dir, talk, ask)
    meter = claude_meter or ClaudeMeter()
    terminal_sockets: set[WebSocket] = set()
    asking: list[str] = terminals.asking if terminals is not None else []  # terminals waiting for a yes

    def team_view() -> dict:
        return {**team.snapshot(), "places": places}

    def crew_for(folder: str) -> TerminalCrew:
        return crews.setdefault(folder_key(folder or projects.current), TerminalCrew())

    def crew_view(folder: str = "") -> dict:
        folder = folder or projects.current
        return {**crew_for(folder).snapshot(), "places": places, "project": folder}

    def terminals_view() -> dict:
        busy = [p for p in projects.paths() if folder_key(p) in crews and crews[folder_key(p)].busy]
        return {"type": "terminals", "busy": busy, "open": terminals.alive() if terminals else []}

    def usage_view() -> dict:
        return {"type": "usage", "claude": meter.today(), "gemini": GEMINI.today()}

    state = {"startup_error": ""}

    async def pump() -> None:
        """Carry what the lead says to the browser, sentence by sentence."""
        splitter = SentenceSplitter()
        # Text written before and after a tool call comes as separate messages
        # with nothing between them; a line break keeps "kuruyorum.Kurdum" apart.
        text_seen = after_tool = False
        async for event in team.lead_events():
            if isinstance(event, LeadTurn):
                await clients.send({"type": "lead_turn"})
            elif isinstance(event, MeetingEnded):
                await clients.send({"type": "meeting", "lines": event.lines})
            elif isinstance(event, TextDelta):
                text = f"\n{event.text}" if text_seen and after_tool else event.text
                text_seen, after_tool = True, False
                await clients.send({"type": "text", "text": text})
                for sentence in splitter.feed(text):
                    await clients.send({"type": "sentence", "text": sentence})
            elif isinstance(event, ToolUse):
                after_tool = True
                await clients.send({"type": "tool", "name": event.name, "summary": event.summary})
            elif isinstance(event, TurnResult):
                for sentence in splitter.flush():
                    await clients.send({"type": "sentence", "text": sentence})
                end = {"type": "turn_end", "error": event.is_error}
                if event.message:
                    end["message"] = event.message
                await clients.send(end)
                splitter = SentenceSplitter()
                text_seen = after_tool = False

    async def publish() -> None:
        async for snapshot in team.changes():
            await clients.send({**snapshot, "places": places})

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        await team.open(projects.current)
        try:
            await team.start_lead()
        except MissingKey as e:
            state["startup_error"] = str(e)
        except OSError:
            logger.exception("claude could not be started")
            state["startup_error"] = CLAUDE_MISSING
        ensure_profile(memory_dir / "cagan.md")
        tasks = [asyncio.create_task(pump()), asyncio.create_task(publish()),
                 asyncio.create_task(report_usage()), asyncio.create_task(keep_diary())]
        if telegram is not None:
            tasks.append(asyncio.create_task(telegram.run()))
        yield
        for task in tasks:
            task.cancel()
        if terminals is not None:
            terminals.close()
        if telegram is not None:
            await telegram.close()
        await team.close()

    async def report_usage() -> None:
        while True:
            with contextlib.suppress(Exception):
                await clients.send(await asyncio.to_thread(usage_view))
            await asyncio.sleep(USAGE_EVERY_S)

    async def keep_diary() -> None:
        """Once a day is over, Cuba writes its diary page and learns from it."""
        while True:
            for day in diary.missing(datetime.date.today().isoformat()):
                written = await diary.write(day, boss.outputs)
                if written and written["learned"]:
                    await clients.send({"type": "notice", "text": f"Cuba {len(written['learned'])} yeni şey öğrendi."})
            await asyncio.sleep(DIARY_EVERY_S)

    app = FastAPI(lifespan=lifespan)
    # Rejects DNS-rebinding requests, whose Host is the attacker's domain.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[*allowed_hosts, *remote_hosts])
    # The phone reaches the page through Tailscale's https proxy, under the machine's tailnet name.
    allowed_origins = {f"http://{host}:{config.port}" for host in LOCAL_HOSTS} | {f"https://{h}" for h in remote_hosts}

    def same_site(request: Request) -> bool:
        """A request from this page, not from another site the user has open."""
        origin = request.headers.get("origin")
        return origin is None or origin in allowed_origins

    @app.middleware("http")
    async def always_fresh(request: Request, call_next):
        # The page and its scripts change with every update; the browser must
        # ask each time (an unchanged file still comes back as a quick 304).
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @app.get("/sw.js")
    async def service_worker() -> FileResponse:
        # Served from the root so it may look after the whole page, which makes it installable.
        return FileResponse(web_dir / "sw.js", media_type="text/javascript")

    @app.get("/manifest.webmanifest")
    async def manifest() -> FileResponse:
        return FileResponse(web_dir / "manifest.webmanifest", media_type="application/manifest+json")

    app.mount("/static", StaticFiles(directory=web_dir, check_dir=False), name="static")

    # ── Memory: Çağan's notebook, the memory files and the diary ──

    @app.get("/api/memory")
    async def memory_read() -> JSONResponse:
        files = {}
        for name in MEMORY_FILES:
            with contextlib.suppress(FileNotFoundError):
                files[name] = (memory_dir / name).read_text(encoding="utf-8")
            files.setdefault(name, "")
        return JSONResponse({"files": files, "diary": diary.pages()})

    @app.put("/api/memory")
    async def memory_write(request: Request) -> JSONResponse:
        if not same_site(request) or request.headers.get("content-type") != "application/json":
            return JSONResponse({"error": "Yetkisiz istek."}, status_code=403)
        body = await request.json()
        name = str(body.get("name", ""))
        if name not in MEMORY_FILES:
            return JSONResponse({"error": "Bilinmeyen dosya."}, status_code=400)
        memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / name).write_text(str(body.get("text", "")), encoding="utf-8")
        return JSONResponse({"ok": True})

    @app.post("/api/diary")
    async def diary_today(request: Request) -> JSONResponse:
        """Write today's page now, without waiting for the day to end."""
        if not same_site(request):
            return JSONResponse({"error": "Yetkisiz istek."}, status_code=403)
        written = await diary.write(datetime.date.today().isoformat(), boss.outputs)
        if written is None:
            return JSONResponse({"error": "Bugün yazılacak bir şey yok ya da Gemini'ye ulaşılamadı."}, status_code=400)
        return JSONResponse(written)

    @app.post("/api/transcribe")
    async def transcribe(request: Request) -> JSONResponse:
        audio = await request.body()
        try:
            text = await asyncio.to_thread(transcriber.transcribe, audio)
        except Exception:
            logger.exception("transcription failed")
            return JSONResponse({"error": "stt"}, status_code=500)
        return JSONResponse({"text": text, "meaningful": is_meaningful(text)})

    @app.post("/api/tts")
    async def tts(request: Request) -> Response:
        text = (await request.json()).get("text", "")
        try:
            wav = await synth(text, config.voice)
        except Exception:
            logger.exception("speech synthesis failed")
            return JSONResponse({"error": "tts"}, status_code=502)
        return Response(wav, media_type="audio/wav")

    async def start_briefing(ws: WebSocket) -> None:
        marker = data_dir / "last_briefing.txt"
        today = datetime.date.today().isoformat()
        try:
            already = marker.read_text(encoding="utf-8").strip() == today
        except FileNotFoundError:
            already = False
        if already:
            await clients.send({"type": "sentence", "text": greeting(datetime.datetime.now().hour)}, ws)
            await clients.send({"type": "turn_end", "error": False}, ws)
            return
        try:
            await team.say(BRIEFING_PROMPT)
        except OSError:
            logger.exception("briefing could not be sent")
            await clients.send({"type": "turn_end", "error": True, "message": CLAUDE_MISSING}, ws)
            return
        data_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(today, encoding="utf-8")

    # ── The lead's tool (tools/ekip.py) ─────────────────────────

    def team_route(path: str, method: str = "POST"):
        """A team endpoint only the lead's own tool may call."""

        def register(handler):
            async def endpoint(request: Request) -> JSONResponse:
                # Workers run with full permissions, so a web page must never be
                # able to hand them work: no browser request carries this token.
                supplied = request.headers.get("x-ekip-token", "")
                if not token or not secrets.compare_digest(supplied, token) or "origin" in request.headers:
                    return JSONResponse({"error": "Yetkisiz istek."}, status_code=403)
                try:
                    body = await request.json() if method == "POST" else {}
                    return JSONResponse(await handler(body))
                except TeamError as e:
                    return JSONResponse({"error": str(e)}, status_code=400)
                except (ValueError, KeyError, TypeError, AttributeError):
                    return JSONResponse({"error": "İstek biçimi hatalı."}, status_code=400)

            app.add_api_route(f"/api/team/{path}", endpoint, methods=[method])
            return handler

        return register

    @team_route("plan")
    async def team_plan(body: dict) -> dict:
        tasks = team.plan([(str(t["to"]), str(t["text"])) for t in body["tasks"]])
        return {"tasks": [asdict(t) for t in tasks]}

    @team_route("begin")
    async def team_begin(body: dict) -> dict:
        tasks = await team.begin([int(i) for i in body.get("ids") or []])
        return {"tasks": [asdict(t) for t in tasks]}

    @team_route("assign")
    async def team_assign(body: dict) -> dict:
        return {"task": asdict(await team.assign(str(body["to"]), str(body["text"])))}

    @team_route("ask")
    async def team_ask(body: dict) -> dict:
        team.ask(str(body["question"]))
        return {}

    @team_route("cancel")
    async def team_cancel(body: dict) -> dict:
        return {"removed": team.cancel()}

    @team_route("move")
    async def team_move(body: dict) -> dict:
        who, where = [str(w) for w in body["who"]], str(body["where"])
        if where not in OFFICE_PLACES or not set(who) <= OFFICE_PEOPLE:
            raise TeamError("Bilinmeyen yer ya da kişi.")
        for person in who:
            if where:
                places[person] = where
            else:
                places.pop(person, None)
        await clients.send(team_view())
        await clients.send(crew_view())
        return {"places": places}

    @team_route("places", method="GET")
    async def team_places(body: dict) -> dict:
        return {"places": places}

    @team_route("state", method="GET")
    async def team_state(body: dict) -> dict:
        return team.snapshot()

    @team_route("terminal")
    async def terminal_reply(body: dict) -> dict:
        """What the terminal's Claude is doing; a finished answer or a permission prompt is said aloud."""
        kind = body.get("kind")
        folder = str(body.get("terminal") or projects.current)
        crew = crew_for(folder)
        name = project_name(folder)
        if kind == "permission_request":
            # Away, Cuba says yes in the user's place; present, Claude asks as usual.
            return {"behavior": "allow"} if boss.away else {}
        if kind == "prompt":
            boss.note_prompt(str(body.get("text", "")), folder)
            crew.prompt()
        elif kind == "pre":
            if body.get("tool") in AGENT_TOOLS:
                # Given work, a team member goes back to their desk.
                places.pop(str((body.get("input") or {}).get("subagent_type", "")).rpartition(":")[2], None)
            crew.tool(str(body.get("tool", "")), dict(body.get("input") or {}),
                      str(body.get("use_id", "")), str(body.get("agent", "")))
        elif kind == "post":
            crew.tool_done(str(body.get("tool", "")), str(body.get("use_id", "")), str(body.get("result", "")))
        elif kind == "permission":
            crew.permission()
            if folder not in asking:
                asking.append(folder)
        elif kind == "stop":
            if folder in asking:
                asking.remove(folder)
            if len(crew.reports) >= 2 and ask is not None:
                # Two or more did the work: they talk it over while Cuba reports.
                asyncio.create_task(meet(folder, crew, list(crew.reports)))
            crew.stop()
        await clients.send(crew_view(folder))
        await clients.send(terminals_view())
        answer: dict = {}
        live_on = live is not None and live.active and not boss.away
        # Nobody at the screen: the phone hears about it.
        far = telegram is not None and (boss.away or clients.active is None)
        if kind == "stop" and live_on:
            # Cuba, on the line, passes the report on in his own words.
            report = str(body.get("text", ""))
            boss.note_report(report, folder)
            await clients.send({"type": "outputs", "items": boss.outputs})
            await live.tell(f"[EKİP RAPORU — {name}]\n{report[-4000:]}")
            return {}
        if kind == "permission" and far and not boss.away:
            await telegram.ask_approval(f"🔐 {name}: ekip bir işlem için onayını bekliyor. Ayrıntı terminalde.",
                                        lambda choice: press_in(folder, "\r" if choice == "evet" else "\x1b"))
        if kind == "permission" and live_on:
            await live.tell(f"[ONAY İSTENİYOR] {name} projesindeki ekip bir işlem için Çağan'ın onayını bekliyor.")
            return {}
        if kind == "stop":
            answer = await boss.on_stop(str(body.get("text", "")), folder)
            await clients.send({"type": "outputs", "items": boss.outputs})
            await clients.send(boss.state())
            if far and boss.outputs and boss.outputs[-1].get("project") == name:
                await telegram.send(f"✅ {name}: {boss.outputs[-1]['summary']}")
            if "continue_with" in answer:
                crew.prompt()  # Claude goes on at once
                await clients.send(crew_view(folder))
        if kind == "permission" and not boss.away:
            answer = {"speak": PERMISSION_LINE}
        if "speak" not in answer:
            return answer
        text = answer["speak"]
        splitter = SentenceSplitter()
        for sentence in [*splitter.feed(text), *splitter.flush()]:
            await clients.send({"type": "sentence", "text": sentence})
        await clients.send({"type": "turn_end", "error": False, "source": "terminal"})
        return {}

    def press_in(folder: str, keys: str) -> None:
        if terminals is not None:
            terminals.get(folder).write(keys)

    async def meet(folder: str, crew: TerminalCrew, reports: list[dict]) -> None:
        """The subagents who did the work talk it over, line by line, in the office and the feed."""
        members = []
        for report in reports:
            if report["who"] not in [m["id"] for m in members]:
                members.append({"id": report["who"], "name": report["name"], "duty": DUTIES.get(report["who"], "")})
        lead = {"id": LEAD_DESK, "name": "Cuba", "duty": "takım lideri"}
        result = await hold_meeting(ask, members, [f"{r['name']}:\n{r['text']}" for r in reports], lead)
        if result is None:
            return
        crew.review = {"members": [m["id"] for m in members], "speaker": "", "lines": []}
        names = {**{m["id"]: m["name"] for m in members}, LEAD_DESK: "Cuba"}
        for line in result["lines"]:
            crew.review["speaker"] = line["who"]
            await clients.send(crew_view(folder))
            await asyncio.sleep(MEETING_PACE_S)
            crew.review["lines"].append(line)
        crew.review = None
        crew.tasks = [{"id": i + 1, "to": t["to"], "status": "proposed", "text": t["text"]}
                      for i, t in enumerate(result["tasks"])]
        await clients.send(crew_view(folder))
        await clients.send({"type": "meeting", "lines": result["lines"], "names": names,
                            "decisions": result["decisions"], "project": folder})
        summary = "; ".join(result["decisions"]) or "Toplantı yapıldı."
        boss.note_meeting(summary, "\n".join(f"{names.get(l['who'], l['who'])}: {l['text']}" for l in result["lines"]), folder)
        await clients.send({"type": "outputs", "items": boss.outputs})
        work = "\n".join(f"- {ROLE_NAMES.get(t['to'], 'Cuba')}: {t['text']}" for t in result["tasks"])
        if live is not None and live.active:
            await live.tell(f"[TOPLANTI SONUCU — {project_name(folder)}] Kararlar: {summary}"
                            + (f"\nÖnerilen işler:\n{work}\nÇağan onaylarsa terminale_ver ile ekibe ver." if work else ""))
        elif telegram is not None:
            await telegram.send(f"🗣 {project_name(folder)} toplantısı: {summary}" + (f"\nÖnerilen işler:\n{work}" if work else ""))

    async def say_aloud(text: str, ws: WebSocket | None = None) -> None:
        if not text:
            return
        if live is not None and live.active:
            await live.tell(f"[HOŞ GELDİN] Çağan döndü. Ona şunu kendi sözlerinle anlat: {text}")
            return
        splitter = SentenceSplitter()
        for sentence in [*splitter.feed(text), *splitter.flush()]:
            await clients.send({"type": "sentence", "text": sentence}, ws)
        await clients.send({"type": "notice", "text": text}, ws)

    @app.get("/api/project")
    async def project_summary() -> JSONResponse:
        return JSONResponse(await asyncio.to_thread(describe_project, projects.current))

    async def open_project(path: str, ws: WebSocket) -> None:
        if path not in projects.paths():
            await clients.send({"type": "notice", "text": "Bu klasör proje listesinde yok."}, ws)
            return
        projects.select(path)
        await team.open(path)
        # Open terminal views reconnect, and so show the new project's own terminal.
        for open_view in list(terminal_sockets):
            with contextlib.suppress(Exception):
                await open_view.close(code=1012)
        await clients.send(projects.listing(), ws)
        await clients.send(crew_view(path), ws)
        await clients.send({"type": "chat", "turns": team.chat}, ws)

    @app.websocket("/ws/live")
    async def live_socket(ws: WebSocket) -> None:
        if live is None or not live.available or ws.headers.get("origin", next(iter(allowed_origins))) not in allowed_origins:
            await ws.close(code=1008)
            return
        await ws.accept()
        await live.serve(ws)

    @app.websocket("/ws/terminal")
    async def terminal_socket(ws: WebSocket) -> None:
        if terminals is None or ws.headers.get("origin", next(iter(allowed_origins))) not in allowed_origins:
            await ws.close(code=1008)
            return
        await ws.accept()
        terminal_sockets.add(ws)
        terminal = terminals.get(projects.current)
        terminal.start()
        output = terminal.listen()
        await ws.send_text(terminal.history())

        async def forward() -> None:
            while True:
                await ws.send_text(await output.get())

        sender = asyncio.create_task(forward())
        try:
            while True:
                message = await ws.receive_json()
                if message.get("type") == "input":
                    terminal.write(str(message.get("data", "")))
                elif message.get("type") == "resize":
                    terminal.resize(int(message.get("cols", 0)), int(message.get("rows", 0)))
        except (WebSocketDisconnect, ValueError):
            pass
        finally:
            terminal_sockets.discard(ws)
            sender.cancel()
            terminal.unlisten(output)

    @app.websocket("/ws")
    async def websocket(ws: WebSocket) -> None:
        # Browsers send Origin on every WebSocket and CORS does not apply to
        # WebSockets: without this check any web page the user visits could
        # drive Claude, which runs with full permissions.
        origin = ws.headers.get("origin")
        if origin is not None and origin not in allowed_origins:
            await ws.close(code=1008)
            return
        await ws.accept()
        previous, clients.active = clients.active, ws
        if previous is not None:
            await clients.send({"type": "replaced"}, previous)
            with contextlib.suppress(Exception):
                await previous.close()
        await clients.send(
            {
                "type": "status",
                "state": "error" if state["startup_error"] else "ready",
                "detail": state["startup_error"],
                "stt_device": transcriber.device,
                "live": live is not None and live.available,
            },
            ws,
        )
        await clients.send(projects.listing(), ws)
        await clients.send(team_view(), ws)
        for key in list(crews):
            await clients.send(crew_view(next((p for p in projects.paths() if folder_key(p) == key), key)), ws)
        await clients.send(crew_view(), ws)
        await clients.send(terminals_view(), ws)
        await clients.send(await asyncio.to_thread(usage_view), ws)
        if telegram is not None and telegram.configured and not telegram.paired:
            await clients.send({"type": "notice", "text": f"Telegram eşleme kodu: bota '/esle {telegram.pair_code}' yazın."}, ws)
        await clients.send(boss.state(), ws)
        await clients.send({"type": "outputs", "items": boss.outputs}, ws)
        await clients.send({"type": "chat", "turns": team.chat}, ws)
        try:
            while True:
                message = await ws.receive_json()
                kind = message.get("type")
                if kind == "say":
                    text = message.get("text", "")
                    await clients.send({"type": "user_text", "text": text}, ws)
                    try:
                        await team.say(text)
                    except OSError:
                        logger.exception("message could not be sent to claude")
                        await clients.send({"type": "turn_end", "error": True, "message": CLAUDE_MISSING}, ws)
                elif kind == "stop":
                    await team.interrupt()
                elif kind == "new_session":
                    await team.new_session()
                    await clients.send({"type": "session_reset"}, ws)
                elif kind == "select_project":
                    await open_project(str(message.get("path", "")), ws)
                elif kind == "add_project":
                    added = projects.add(str(message.get("path", "")))
                    if added is None:
                        await clients.send({"type": "notice", "text": "Klasör bulunamadı. Tam yolu yaz."}, ws)
                    else:
                        await open_project(added, ws)
                elif kind == "start":
                    await start_briefing(ws)
                elif kind == "away":
                    was_away = boss.away
                    boss.set_away(bool(message.get("on")))
                    await clients.send(boss.state())
                    if was_away and not boss.away:
                        await say_aloud(await boss.welcome_back(), ws)
        except (WebSocketDisconnect, RuntimeError):
            pass  # RuntimeError: a newer tab closed this one while it was waiting
        finally:
            if clients.active is ws:
                clients.active = None

    return app


def _git(path: str, *args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=path, capture_output=True, text=True,
                              encoding="utf-8", timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def describe_project(path: str) -> dict:
    """A quick look at the project for the dashboard: git state and the README's opening."""
    folder = Path(path)
    readme = ""
    for name in ("README.md", "readme.md", "README.txt"):
        with contextlib.suppress(OSError):
            readme = (folder / name).read_text(encoding="utf-8", errors="replace")[:1200]
            break
    status = _git(path, "status", "--porcelain")
    # The team's work papers (ekip/TERMINAL.md), newest first.
    papers = sorted((folder / "docs" / "ekip").glob("*.md"), reverse=True)[:10]
    docs = []
    for paper in papers:
        with contextlib.suppress(OSError):
            docs.append({"name": paper.stem, "text": paper.read_text(encoding="utf-8", errors="replace")[:4000]})
    return {
        "name": folder.name or path,
        "path": path,
        "branch": _git(path, "branch", "--show-current"),
        "commits": [line.split("\x1f", 1) for line in _git(path, "log", "-8", "--format=%cr%x1f%s").splitlines()],
        "changed": len(status.splitlines()) if status else 0,
        "readme": readme,
        "docs": docs,
    }


def _port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _open_when_ready(server, url: str) -> None:
    for _ in range(1200):
        if server.started:
            webbrowser.open(url)
            return
        time.sleep(0.1)


def tailnet_names() -> tuple[str, ...]:
    """This machine's Tailscale name, if Tailscale runs here: the phone reaches Cuba under it."""
    exe = shutil.which("tailscale") or (r"C:\Program Files\Tailscale\tailscale.exe"
                                        if Path(r"C:\Program Files\Tailscale\tailscale.exe").exists() else None)
    if exe is None:
        return ()
    try:
        done = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, encoding="utf-8", timeout=5)
        name = json.loads(done.stdout)["Self"]["DNSName"].rstrip(".")
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return ()
    return (name,) if name else ()


def _read_key(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    from server.claude_bridge import ClaudeBridge, build_command
    from server.config import load_config
    from server.gemini_bridge import GeminiBridge
    from server.prompts import write_prompts
    from server.stt import Transcriber
    from server.team import LEAD
    from server.tts import synthesize
    from server.winjob import kill_with_me

    parser = argparse.ArgumentParser(prog="server.app")
    parser.add_argument("--open", action="store_true", help="open the browser once the server is up")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    config = load_config(ROOT / "config.json")
    url = f"http://127.0.0.1:{config.port}"
    if _port_in_use(config.port):
        # Already running (e.g. the shortcut was double-clicked twice).
        if args.open:
            webbrowser.open(url)
        return

    claude_exe = shutil.which("claude") or "claude"
    # The end-to-end test points this at a scratch folder to leave real state alone.
    data_dir = Path(os.environ.get("CLAUDE_SES_DATA") or ROOT / "data")
    prompts = write_prompts(data_dir / "prompts", config.models)
    # tools/ekip.py, run by the lead, finds the server and proves itself with these.
    token = secrets.token_urlsafe(32)
    os.environ["CLAUDE_SES_TOKEN"] = token
    os.environ["CLAUDE_SES_PORT"] = str(config.port)

    gemini_key = os.environ.get("GEMINI_API_KEY") or _read_key(data_dir / "gemini_key.txt")

    def bridge_for(role, model, workdir, store) -> ClaudeBridge | GeminiBridge:
        if role.id == LEAD and config.lead_backend == "gemini":
            return GeminiBridge(
                store, prompts[role.id], gemini_key, config.gemini_model, config.gemini_thinking_budget
            )
        # The lead keeps the user's MCP servers for assistant work; the others
        # only code, and start faster without them.
        extra = () if role.id == LEAD else ("--strict-mcp-config",)
        return ClaudeBridge(
            workdir,
            store,
            lambda session_id: build_command(claude_exe, session_id, model, prompts[role.id], extra),
            on_spawn=kill_with_me,
        )

    from server.gemini_bridge import ask_gemini

    async def ask(system: str, prompt: str, as_json: bool) -> str:
        return await ask_gemini(gemini_key, config.gemini_model, system, prompt, as_json)

    async def meeter(members, reports, lead):
        return await hold_meeting(ask, members, reports, lead)

    GEMINI.use(data_dir / "usage.json")
    team = Team(config.models, bridge_for, data_dir, meeter=meeter if gemini_key else None)
    projects = ProjectList(data_dir / "projects.json", config.workdir)
    print("Ses tanıma modeli yükleniyor…", flush=True)
    transcriber = Transcriber(config.whisper_model, config.vocabulary)

    async def speak(text: str, voice: str) -> bytes:
        return await synthesize(text, voice, config.voice_rate, config.voice_pitch)

    from server.terminal import hook_settings, powershell_command

    from server.prompts import write_terminal_team

    charter, plugin = write_terminal_team(data_dir / "terminal", config.models)
    from server.prompts import INSTALLERS, ofis_command

    settings = hook_settings(sys.executable, data_dir / "terminal", charter, allow=(ofis_command(), *INSTALLERS))
    argv = powershell_command(claude_exe, settings, config.terminal_model, plugin)
    # Each project gets its own terminal; the hook tells the server which one it speaks for.
    terminals = TerminalPool(lambda cwd: Terminal(argv, cwd, env={"CLAUDE_SES_TERMINAL": cwd}))
    from server.supervisor import Supervisor

    supervisor = Supervisor(ask if gemini_key else None, data_dir / "terminal" / "outputs.json")

    async def hand_over(instruction: str, folder: str) -> None:
        """Type Cuba's instruction into that project's own terminal, as if Çağan had; others keep working."""
        terminal = terminals.get(folder)
        if not terminal.alive:
            terminal.start()
            await asyncio.sleep(8)  # Claude Code takes a moment before it reads its prompt
        # One line: a newline would send the instruction before it is all typed.
        instruction = (
            f"[Proje: {project_name(folder)} - {folder}. Çalışma klasörün bu değilse hiçbir şeyi "
            f"değiştirme, dur ve sor.] {' '.join(instruction.split())}"
        )
        supervisor.note_prompt(instruction, folder)
        terminal.write(instruction)
        await asyncio.sleep(0.2)  # text and Enter together would land as a paste
        terminal.write("\r")

    def press(keys: str) -> None:
        """Answer the terminal that asked last; with none asking, the open project's."""
        terminals.get(terminals.asking[-1] if terminals.asking else projects.current).write(keys)

    talk = ConversationLog(data_dir / "konusmalar")
    diary = Diary(MEMORY_DIR, talk, ask if gemini_key else None)

    def last_page() -> str:
        return diary.latest(datetime.date.today().isoformat())

    live = None
    if config.voice_engine == "live" and gemini_key:
        live = LiveHub(
            gemini_key, config.live_model, config.live_voice, hand_over, press, projects=projects.listing,
            heard=lambda who, text: talk.add(who, text), diary=last_page,
        )
    telegram = None
    if gemini_key and (data_dir / "telegram.json").exists():
        from server.live import CubaTools
        from server.telegram import TelegramBot

        def status() -> str:
            busy = [project_name(p) for p in terminals.alive()]
            lines = [f"Uzak mod: {'açık' if supervisor.away else 'kapalı'}",
                     f"Açık terminaller: {', '.join(busy) or 'yok'}"]
            lines += [f"Son: {o['time']} {o.get('project', '')} — {o['summary']}" for o in supervisor.outputs[-3:]]
            return "\n".join(lines)

        async def toggle_away() -> str:
            supervisor.set_away(not supervisor.away)
            return "Uzak mod açık: kararları ben veriyorum efendim." if supervisor.away else "Uzak mod kapandı efendim."

        telegram = TelegramBot(
            data_dir / "telegram.json", gemini_key, config.gemini_model,
            CubaTools(hand_over, press, MEMORY_DIR, projects=projects.listing),
            status, toggle_away, lambda: press("\x1b"),
            heard=lambda who, text, channel: talk.add(who, text, channel), diary=last_page,
        )
    remote = (*config.remote_hosts, *tailnet_names())
    if remote:
        print(f"Telefondan: https://{remote[0]}  (Tailscale ile)", flush=True)
    app = create_app(
        config, team, projects, transcriber, speak, data_dir=data_dir, token=token, terminals=terminals,
        supervisor=supervisor, live=live, ask=ask if gemini_key else None, telegram=telegram, remote_hosts=remote,
    )
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=config.port))
    if args.open:
        threading.Thread(target=_open_when_ready, args=(server, url), daemon=True).start()
    print(f"Claude Ses hazırlanıyor: {url} — kapatmak için bu pencereyi kapatın.", flush=True)
    server.run()


if __name__ == "__main__":
    main()
