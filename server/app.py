"""HTTP + WebSocket server joining the browser, Claude, Whisper and Edge TTS."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime
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
from server.live import LiveHub
from server.supervisor import Supervisor
from server.terminal import AGENT_TOOLS, PERMISSION_LINE, Terminal, TerminalCrew

logger = logging.getLogger(__name__)

BRIEFING_PROMPT = "Günün planını kısaca özetle."
# The spots in web/office.js; "" sends someone back to their own routine.
OFFICE_PLACES = {"desk", "meeting", "coffee", "sofa", "visit", ""}
OFFICE_PEOPLE = {"lider", "kidemli", "gelistirici", "testci", "asistan", "cagan"}
LOCAL_HOSTS = ("127.0.0.1", "localhost")
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
) -> FastAPI:
    clients = _Clients()
    crew = TerminalCrew()
    boss = supervisor or Supervisor(None, data_dir / "terminal" / "outputs.json")
    places: dict[str, str] = {}  # who was sent where; the rest follow their own routine

    def team_view() -> dict:
        return {**team.snapshot(), "places": places}

    def crew_view() -> dict:
        return {**crew.snapshot(), "places": places}
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
        tasks = [asyncio.create_task(pump()), asyncio.create_task(publish())]
        yield
        for task in tasks:
            task.cancel()
        if terminal is not None:
            terminal.close()
        await team.close()

    app = FastAPI(lifespan=lifespan)
    # Rejects DNS-rebinding requests, whose Host is the attacker's domain.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))
    allowed_origins = {f"http://{host}:{config.port}" for host in LOCAL_HOSTS}

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

    app.mount("/static", StaticFiles(directory=web_dir, check_dir=False), name="static")

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
        if kind == "permission_request":
            # Away, Cuba says yes in the user's place; present, Claude asks as usual.
            return {"behavior": "allow"} if boss.away else {}
        if kind == "prompt":
            boss.note_prompt(str(body.get("text", "")))
            crew.prompt()
        elif kind == "pre":
            if body.get("tool") in AGENT_TOOLS:
                # Given work, a team member goes back to their desk.
                places.pop(str((body.get("input") or {}).get("subagent_type", "")).rpartition(":")[2], None)
            crew.tool(str(body.get("tool", "")), dict(body.get("input") or {}),
                      str(body.get("use_id", "")), str(body.get("agent", "")))
        elif kind == "post":
            crew.tool_done(str(body.get("tool", "")), str(body.get("use_id", "")))
        elif kind == "permission":
            crew.permission()
        elif kind == "stop":
            crew.stop()
        await clients.send(crew_view())
        answer: dict = {}
        live_on = live is not None and live.active and not boss.away
        if kind == "stop" and live_on:
            # Cuba, on the line, passes the report on in his own words.
            report = str(body.get("text", ""))
            boss.note_report(report)
            crew.stop()
            await clients.send({"type": "outputs", "items": boss.outputs})
            await live.tell(f"[EKİP RAPORU]\n{report[-4000:]}")
            return {}
        if kind == "permission" and live_on:
            await live.tell("[ONAY İSTENİYOR] Terminaldeki ekip bir işlem için Çağan'ın onayını bekliyor.")
            return {}
        if kind == "stop":
            answer = await boss.on_stop(str(body.get("text", "")))
            await clients.send({"type": "outputs", "items": boss.outputs})
            await clients.send(boss.state())
            if "continue_with" in answer:
                crew.prompt()  # Claude goes on at once
                await clients.send(crew_view())
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
        if terminal is not None:
            terminal.move_to(path)  # Claude restarts in the new folder when next needed
        await clients.send(projects.listing(), ws)
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
        if terminal is None or ws.headers.get("origin", next(iter(allowed_origins))) not in allowed_origins:
            await ws.close(code=1008)
            return
        await ws.accept()
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
        await clients.send(crew_view(), ws)
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
        except WebSocketDisconnect:
            pass
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

    team = Team(config.models, bridge_for, data_dir)
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
    terminal = Terminal(
        powershell_command(claude_exe, settings, config.terminal_model, plugin), projects.current
    )
    from server.gemini_bridge import ask_gemini
    from server.supervisor import Supervisor

    async def ask(system: str, prompt: str, as_json: bool) -> str:
        return await ask_gemini(gemini_key, config.gemini_model, system, prompt, as_json)

    supervisor = Supervisor(ask if gemini_key else None, data_dir / "terminal" / "outputs.json")

    async def hand_over(instruction: str, folder: str) -> None:
        """Type Cuba's instruction into the terminal's Claude, as if Çağan had, in the project's own folder."""
        if folder != projects.current:
            projects.select(folder)
            await team.open(folder)
        terminal.move_to(folder)  # a fresh Claude there reads that project's CLAUDE.md and memory
        if not terminal.alive:
            terminal.start()
            await asyncio.sleep(8)  # Claude Code takes a moment before it reads its prompt
        # One line: a newline would send the instruction before it is all typed.
        instruction = (
            f"[Proje: {project_name(folder)} - {folder}. Çalışma klasörün bu değilse hiçbir şeyi "
            f"değiştirme, dur ve sor.] {' '.join(instruction.split())}"
        )
        supervisor.note_prompt(instruction)
        terminal.write(instruction)
        await asyncio.sleep(0.2)  # text and Enter together would land as a paste
        terminal.write("\r")

    live = None
    if config.voice_engine == "live" and gemini_key:
        live = LiveHub(
            gemini_key, config.live_model, config.live_voice, hand_over, terminal.write, projects=projects.listing
        )
    app = create_app(
        config, team, projects, transcriber, speak, data_dir=data_dir, token=token, terminal=terminal,
        supervisor=supervisor, live=live,
    )
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=config.port))
    if args.open:
        threading.Thread(target=_open_when_ready, args=(server, url), daemon=True).start()
    print(f"Claude Ses hazırlanıyor: {url} — kapatmak için bu pencereyi kapatın.", flush=True)
    server.run()


if __name__ == "__main__":
    main()
