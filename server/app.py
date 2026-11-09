"""HTTP + WebSocket server joining the browser, Claude, Whisper and Edge TTS."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime
import logging
import shutil
import socket
import threading
import time
import webbrowser
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from server.claude_events import TextDelta, ToolUse, TurnResult
from server.config import ROOT, Config
from server.sentences import SentenceSplitter
from server.stt import is_meaningful

logger = logging.getLogger(__name__)

BRIEFING_PROMPT = "Günün planını kısaca özetle."
CLAUDE_MISSING = (
    "Claude Code bulunamadı ya da giriş yapılmamış. Bir terminalde 'claude' yazıp giriş yapın."
)

Synth = Callable[[str, str], Awaitable[bytes]]


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
    bridge,
    transcriber,
    synth: Synth,
    data_dir: Path = ROOT / "data",
    web_dir: Path = ROOT / "web",
) -> FastAPI:
    clients = _Clients()
    state = {"startup_error": ""}

    async def pump() -> None:
        splitter = SentenceSplitter()
        # Text written before and after a tool call comes as separate messages
        # with nothing between them; a line break keeps "kuruyorum.Kurdum" apart.
        text_seen = after_tool = False
        async for event in bridge.events():
            if isinstance(event, TextDelta):
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
                await clients.send({"type": "turn_end", "error": event.is_error})
                splitter = SentenceSplitter()
                text_seen = after_tool = False

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            await bridge.start()
        except OSError:
            logger.exception("claude could not be started")
            state["startup_error"] = CLAUDE_MISSING
        task = asyncio.create_task(pump())
        yield
        task.cancel()
        await bridge.close()

    app = FastAPI(lifespan=lifespan)

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
            await clients.send({"type": "turn_end", "error": False}, ws)
            return
        data_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(today, encoding="utf-8")
        await bridge.send(BRIEFING_PROMPT)

    @app.websocket("/ws")
    async def websocket(ws: WebSocket) -> None:
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
        try:
            while True:
                message = await ws.receive_json()
                kind = message.get("type")
                if kind == "say":
                    text = message.get("text", "")
                    await clients.send({"type": "user_text", "text": text}, ws)
                    await bridge.send(text)
                elif kind == "stop":
                    await bridge.interrupt()
                elif kind == "new_session":
                    await bridge.new_session()
                    await clients.send({"type": "session_reset"}, ws)
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
    from server.session_store import SessionStore
    from server.stt import Transcriber
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
    bridge = ClaudeBridge(
        config.workdir,
        SessionStore(ROOT / "data" / "session.json"),
        lambda session_id: build_command(claude_exe, session_id),
        on_spawn=kill_with_me,
    )
    print("Ses tanıma modeli yükleniyor…", flush=True)
    transcriber = Transcriber(config.whisper_model, config.vocabulary)
    app = create_app(config, bridge, transcriber, synthesize)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=config.port))
    if args.open:
        threading.Thread(target=_open_when_ready, args=(server, url), daemon=True).start()
    print(f"Claude Ses hazırlanıyor: {url} — kapatmak için bu pencereyi kapatın.", flush=True)
    server.run()


if __name__ == "__main__":
    main()
