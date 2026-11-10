"""Full voice turns against the real server, real Claude, Whisper and Edge TTS.

The microphone is replaced by a WebAudio stream into which Edge-synthesised
Turkish sentences are played, so speech recognition runs on real audio.
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
import time
import urllib.request

import pytest

from server.config import ROOT

pytestmark = pytest.mark.e2e
URL = "http://127.0.0.1:8765/"
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")

FAKE_MIC = """
window.__plays = 0;
const play = HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play = function () { window.__plays++; return play.apply(this, arguments); };
navigator.mediaDevices.getUserMedia = async () => {
  window.__ctx ??= new AudioContext();
  await window.__ctx.resume();
  window.__dest = window.__ctx.createMediaStreamDestination();
  return window.__dest.stream;
};
window.__say = async (text) => {
  const r = await fetch('/api/tts', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                     body: JSON.stringify({text})});
  const buf = await window.__ctx.decodeAudioData(await r.arrayBuffer());
  const src = window.__ctx.createBufferSource();
  src.buffer = buf;
  src.connect(window.__dest);
  src.start();
};
"""


def _ready() -> bool:
    try:
        return urllib.request.urlopen(URL, timeout=2).status == 200
    except OSError:
        return False


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    assert not _ready(), "Claude Ses is already running on 8765; close it before the e2e test"
    # A scratch data folder: no saved conversation, and the daily briefing is due.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "CLAUDE_SES_DATA": str(tmp_path_factory.mktemp("data"))}
    proc = subprocess.Popen([PYTHON, "-m", "server.app"], cwd=ROOT, env=env)
    try:
        for _ in range(240):
            if _ready():
                break
            time.sleep(0.5)
        assert _ready(), "server did not start"
        yield
    finally:
        proc.kill()
        proc.wait()


@pytest.fixture
def page(server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        page = browser.new_page()
        page.add_init_script(FAKE_MIC)
        page.goto(URL)
        page.wait_for_function("document.getElementById('conn').textContent === 'Claude bağlı'", timeout=30_000)
        yield page
        browser.close()


def orb_state(page) -> str:
    return page.get_attribute("#orb", "data-state")


def wait_for(page, predicate, timeout_s: float, what: str):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"timed out waiting for {what}; orb={orb_state(page)} status={page.inner_text('#status')}")


def speak_and_wait_reply(page, sentence: str) -> dict:
    """Say *sentence* once listening; wait until the reply was spoken and listening resumed."""
    wait_for(page, lambda: orb_state(page) == "listening", 30, "listening")
    plays_before = page.evaluate("window.__plays")
    turns_before = page.locator(".turn").count()
    page.evaluate("text => window.__say(text)", sentence)
    wait_for(page, lambda: page.locator(".turn").count() > turns_before, 60, "transcript")
    wait_for(page, lambda: page.evaluate("window.__plays") > plays_before, 180, "spoken reply")
    wait_for(page, lambda: orb_state(page) == "listening", 180, "listening again")
    turn = page.locator(".turn").last
    return {"you": turn.locator(".you").inner_text(), "reply": turn.locator(".reply").inner_text()}


def test_voice_assistant_end_to_end(page):
    page.click("#newSession")
    page.wait_for_timeout(1000)

    # First click of the day: the assistant greets with today's plan, then listens.
    page.click("#orb")
    wait_for(page, lambda: page.evaluate("window.__plays") >= 1, 240, "spoken daily briefing")
    wait_for(page, lambda: orb_state(page) == "listening", 240, "listening after briefing")

    turn = speak_and_wait_reply(page, "Merhaba, bana sadece tamam de.")
    print("turn 1:", turn)
    assert "merhaba" in turn["you"].lower() and turn["reply"].strip()

    # Stop while Claude is busy with a tool: speech must not start afterwards.
    page.evaluate("text => window.__say(text)", "PowerShell'de yirmi saniye bekle, sonra bitti de.")
    wait_for(page, lambda: page.inner_text("#toolLine").strip() != "", 180, "a running tool")
    page.click("#stop")
    wait_for(page, lambda: orb_state(page) == "idle", 5, "idle after stop")
    plays = page.evaluate("window.__plays")
    page.wait_for_timeout(4000)
    assert page.evaluate("window.__plays") == plays and orb_state(page) == "idle"

    # Hands-free again (no second briefing today), then a spoken reminder.
    page.click("#orb")
    turn = speak_and_wait_reply(page, "Yarın saat on birde Nevka Kağıt'ı aramayı hatırlat.")
    print("turn 3:", turn)
    page.click("#stop")

    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    listing = subprocess.run(
        [PYTHON, str(ROOT / "tools" / "reminder.py"), "list"],
        capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    ).stdout
    print("reminders:", listing)
    matches = [line for line in listing.splitlines() if f"{tomorrow} 11:00" in line and "nevka" in line.lower()]
    for line in matches:
        subprocess.run([PYTHON, str(ROOT / "tools" / "reminder.py"), "delete", line.split()[0]], check=True)
    assert matches, listing
