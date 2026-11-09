"""The WebSocket must work under the real uvicorn server, not only TestClient."""

import json
import socket
import threading
import time

import uvicorn

from server.app import create_app
from server.config import Config
from tests.test_app import FakeBridge, FakeTranscriber, ok_synth


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_websocket_over_real_uvicorn(tmp_path):
    from websockets.sync.client import connect

    port = free_port()
    app = create_app(Config(), FakeBridge(), FakeTranscriber(), ok_synth, data_dir=tmp_path)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(50):
            if server.started:
                break
            time.sleep(0.1)
        with connect(f"ws://127.0.0.1:{port}/ws") as ws:
            assert json.loads(ws.recv(timeout=5))["type"] == "status"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
