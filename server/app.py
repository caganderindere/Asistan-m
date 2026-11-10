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
from server.projects import ProjectList
from server.sentences import SentenceSplitter
from server.stt import is_meaningful
from server.team import LeadTurn, MeetingEnded, Team, TeamError

logger = logging.getLogger(__name__)

BRIEFING_PROMPT = "Günün planını kısaca özetle."
LOCAL_HOSTS = ("127.0.0.1", "localhost")
CLAUDE_MISSING = (
    "Claude Code bulunamadı ya da giriş yapılmamış. Bir terminalde 'claude' yazıp giriş yapın."
)

Synth = Callable[[str, str], Awaitable[bytes]]


def greeting(hour: int) -> str:
    """What Jarvis says when the user starts talking and the day's briefing is already done."""
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
) -> FastAPI:
    clients = _Clients()
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
            await clients.send(snapshot)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        await team.open(projects.current)
        try:
            await team.start_lead()
        except OSError:
            logger.exception("claude could not be started")
            state["startup_error"] = CLAUDE_MISSING
        tasks = [asyncio.create_task(pump()), asyncio.create_task(publish())]
        yield
        for task in tasks:
            task.cancel()
        await team.close()

    app = FastAPI(lifespan=lifespan)
    # Rejects DNS-rebinding requests, whose Host is the attacker's domain.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))
    allowed_origins = {f"http://{host}:{config.port}" for host in LOCAL_HOSTS}

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

    @team_route("state", method="GET")
    async def team_state(body: dict) -> dict:
        return team.snapshot()

    async def open_project(path: str, ws: WebSocket) -> None:
        if path not in projects.paths():
            await clients.send({"type": "notice", "text": "Bu klasör proje listesinde yok."}, ws)
            return
        projects.select(path)
        await team.open(path)
        await clients.send(projects.listing(), ws)
        await clients.send({"type": "chat", "turns": team.chat}, ws)

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
            },
            ws,
        )
        await clients.send(projects.listing(), ws)
        await clients.send(team.snapshot(), ws)
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
        except WebSocketDisconnect:
            pass
        finally:
            if clients.active is ws:
                clients.active = None

    return app


def _port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _open_when_ready(server, url: str) -> None:
    for _ in range(1200):
        if server.started:
            webbrowser.open(url)
            return
        time.sleep(0.1)


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    from server.claude_bridge import ClaudeBridge, build_command
    from server.config import load_config
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

    def bridge_for(role, model, workdir, store) -> ClaudeBridge:
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

    app = create_app(config, team, projects, transcriber, speak, data_dir=data_dir, token=token)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=config.port))
    if args.open:
        threading.Thread(target=_open_when_ready, args=(server, url), daemon=True).start()
    print(f"Claude Ses hazırlanıyor: {url} — kapatmak için bu pencereyi kapatın.", flush=True)
    server.run()


if __name__ == "__main__":
    main()
