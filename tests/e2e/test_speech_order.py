"""Sentences must be spoken one after another, never on top of each other.

Runs the real page in a browser against a fake Claude and a slow fake voice,
so it needs neither a login nor a graphics card.
"""

from __future__ import annotations

import asyncio
import io
import socket
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import uvicorn

from server.claude_events import TextDelta, TurnResult
from server.config import ROOT, Config
from tests.test_app import FakeBridge, make_app

pytestmark = pytest.mark.e2e

# Counts how many clips are audible at once, and replaces the microphone with silence.
WATCH_AUDIO = """
window.__audible = new Set();
window.__mostAtOnce = 0;
window.__spoken = 0;
const play = HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play = function () {
  if (!this.__watched) {
    this.__watched = true;
    this.addEventListener('playing', () => {
      window.__audible.add(this);
      window.__mostAtOnce = Math.max(window.__mostAtOnce, window.__audible.size);
    });
    for (const end of ['ended', 'pause', 'error']) this.addEventListener(end, () => window.__audible.delete(this));
    this.addEventListener('ended', () => { window.__spoken++; });
  }
  return play.apply(this, arguments);
};
navigator.mediaDevices.getUserMedia = async () => {
  window.__ctx ??= new AudioContext();
  return window.__ctx.createMediaStreamDestination().stream;
};
"""


def tone(seconds: float = 0.6) -> bytes:
    rate = 16000
    t = np.arange(int(rate * seconds)) / rate
    wav = io.BytesIO()
    sf.write(wav, (0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32"), rate, format="WAV")
    return wav.getvalue()


async def slow_voice(text: str, voice: str) -> bytes:
    await asyncio.sleep(0.5)  # the online voice takes about this long to answer
    return tone()


def speak_four_sentences(tmp_path: Path, web_dir: Path = ROOT / "web") -> dict:
    """Start hands-free, let the lead say four sentences at once; report how they were played."""
    from playwright.sync_api import sync_playwright

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    lead = FakeBridge()
    app = make_app(tmp_path, lead, synth=slow_voice, config=Config(port=port), web_dir=web_dir)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        while not server.started:
            time.sleep(0.05)
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            page = browser.new_page()
            page.add_init_script(WATCH_AUDIO)
            page.goto(f"http://127.0.0.1:{port}/")
            page.wait_for_function("document.getElementById('conn').textContent === 'Claude bağlı'")
            page.click("#orb")  # the first start of the day asks the lead for the briefing
            page.wait_for_function("document.getElementById('orb').dataset.state === 'working'")
            lead.push(TextDelta("Günaydın efendim. Bugün iki randevunuz var. İlki saat onda. Hepsi bu."),
                      TurnResult("s", False))
            # Four clips of 0.6 s, each 0.5 s in the making: done well within this.
            page.wait_for_timeout(8_000)
            result = page.evaluate("({ most: window.__mostAtOnce, spoken: window.__spoken,"
                                   " then: document.getElementById('orb').dataset.state })")
            browser.close()
            return result
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_sentences_are_spoken_one_at_a_time(tmp_path):
    assert speak_four_sentences(tmp_path) == {"most": 1, "spoken": 4, "then": "listening"}
