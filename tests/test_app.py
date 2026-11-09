import asyncio
import datetime

import pytest
from fastapi.testclient import TestClient

from server.app import BRIEFING_PROMPT, create_app
from server.claude_events import TextDelta, ToolUse, TurnResult
from server.config import Config


class FakeBridge:
    def __init__(self):
        self.sent = []
        self.interrupted = False
        self.new_sessions = 0
        self.loop = None
        self.queue = None

    async def start(self):
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue()

    async def close(self):
        pass

    async def send(self, text):
        self.sent.append(text)

    async def interrupt(self, timeout=3.0):
        self.interrupted = True

    async def new_session(self):
        self.new_sessions += 1

    async def events(self):
        while True:
            yield await self.queue.get()

    def push(self, *events):
        for event in events:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, event)


class MissingClaude(FakeBridge):
    async def start(self):
        await super().start()
        raise FileNotFoundError("claude")


class FakeTranscriber:
    device = "cuda"

    def __init__(self, text="dosyaları listele"):
        self.text = text

    def transcribe(self, audio):
        return self.text


async def ok_synth(text, voice):
    return b"RIFF" + text.encode()


async def failing_synth(text, voice):
    raise ConnectionError("edge down")


def make_client(tmp_path, bridge, transcriber=None, synth=ok_synth):
    app = create_app(Config(), bridge, transcriber or FakeTranscriber(), synth, data_dir=tmp_path)
    return TestClient(app)


@pytest.fixture
def fake_bridge():
    return FakeBridge()


@pytest.fixture
def client(tmp_path, fake_bridge):
    with make_client(tmp_path, fake_bridge) as c:
        yield c


def read_until(ws, kind):
    msgs = []
    while True:
        msg = ws.receive_json()
        msgs.append(msg)
        if msg["type"] == kind:
            return msgs


def test_status_reports_stt_device(client):
    with client.websocket_connect("/ws") as ws:
        status = ws.receive_json()
    assert status == {"type": "status", "state": "ready", "detail": "", "stt_device": "cuda"}


def test_turn_streams_sentences_and_end(client, fake_bridge):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "say", "text": "selam"})
        assert read_until(ws, "user_text")[-1]["text"] == "selam"
        fake_bridge.push(TextDelta("Merhaba. Nasıl"), TextDelta("sın?"), TurnResult("s1", False))
        msgs = read_until(ws, "turn_end")
    assert [m["text"] for m in msgs if m["type"] == "sentence"] == ["Merhaba.", "Nasılsın?"]
    assert "".join(m["text"] for m in msgs if m["type"] == "text") == "Merhaba. Nasılsın?"
    assert fake_bridge.sent == ["selam"]


def test_tool_only_turn_still_ends(client, fake_bridge):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "say", "text": "listele"})
        read_until(ws, "user_text")
        fake_bridge.push(ToolUse("Bash", "dir"), TurnResult("s1", False))
        msgs = read_until(ws, "turn_end")
    assert {"type": "tool", "name": "Bash", "summary": "dir"} in msgs
    assert msgs[-1] == {"type": "turn_end", "error": False}


def test_second_tab_replaces_first(client):
    with client.websocket_connect("/ws") as a:
        with client.websocket_connect("/ws"):
            assert read_until(a, "replaced")[-1]["type"] == "replaced"


def test_briefing_once_per_day(client, fake_bridge, tmp_path):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        fake_bridge.push(TextDelta("Günaydın."), TurnResult("s1", False))
        read_until(ws, "turn_end")
        ws.send_json({"type": "start"})
        read_until(ws, "turn_end")
    assert fake_bridge.sent == [BRIEFING_PROMPT]
    assert (tmp_path / "last_briefing.txt").read_text() == datetime.date.today().isoformat()


def test_stop_calls_interrupt(client, fake_bridge):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "stop"})
        ws.send_json({"type": "new_session"})
        read_until(ws, "session_reset")
    assert fake_bridge.interrupted and fake_bridge.new_sessions == 1


def test_transcribe_filters(tmp_path, fake_bridge):
    with make_client(tmp_path, fake_bridge, FakeTranscriber("Altyazı M.K.")) as c:
        body = c.post("/api/transcribe", content=b"webm").json()
    assert body == {"text": "Altyazı M.K.", "meaningful": False}


def test_tts_returns_wav(client):
    r = client.post("/api/tts", json={"text": "Merhaba"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content.startswith(b"RIFF")


def test_tts_failure_is_502(tmp_path, fake_bridge):
    with make_client(tmp_path, fake_bridge, synth=failing_synth) as c:
        r = c.post("/api/tts", json={"text": "Merhaba"})
    assert r.status_code == 502 and r.json() == {"error": "tts"}


def test_missing_claude_reports_error(tmp_path):
    with make_client(tmp_path, MissingClaude()) as c, c.websocket_connect("/ws") as ws:
        status = ws.receive_json()
    assert status["state"] == "error" and "claude" in status["detail"]
