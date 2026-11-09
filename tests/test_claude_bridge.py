import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from server.claude_bridge import ClaudeBridge, build_command, child_env
from server.claude_events import TextDelta, TurnResult
from server.session_store import SessionStore

FAKE = Path(__file__).parent / "fake_claude.py"


def factory(*extra):
    def make(session_id):
        return [sys.executable, str(FAKE), *(["--resume", session_id] if session_id else []), *extra]
    return make


@pytest.fixture
def args_log(tmp_path, monkeypatch):
    log = tmp_path / "args.log"
    monkeypatch.setenv("FAKE_ARGS_LOG", str(log))
    return log


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "session.json")


async def make_bridge(tmp_path, store, *extra):
    bridge = ClaudeBridge(str(tmp_path), store, factory(*extra))
    await bridge.start()
    return bridge


@pytest.fixture
async def bridge(tmp_path, store, args_log):
    b = await make_bridge(tmp_path, store)
    yield b
    await b.close()


@pytest.fixture
async def bridge_ignoring(tmp_path, store, args_log):
    b = await make_bridge(tmp_path, store, "--ignore-interrupt")
    yield b
    await b.close()


async def collect_until_result(bridge, timeout=10):
    collected = []

    async def run():
        async for event in bridge.events():
            collected.append(event)
            if isinstance(event, TurnResult):
                return

    await asyncio.wait_for(run(), timeout)
    return collected


def text_of(evs):
    return "".join(e.text for e in evs if isinstance(e, TextDelta))


def last_command_args(log):
    return json.loads(log.read_text(encoding="utf-8").splitlines()[-1])


async def test_echo_turkish(bridge, store):
    await bridge.send("ğüşıöç İĞÜŞ")
    ev = await collect_until_result(bridge)
    assert "ğüşıöç İĞÜŞ" in text_of(ev) and store.load()


async def test_crash_ends_turn_and_next_send_resumes_session(bridge, store, args_log):
    await bridge.send("merhaba")
    await collect_until_result(bridge)
    sid = store.load()
    await bridge.send("öl")
    crashed = await collect_until_result(bridge)
    assert crashed[-1].is_error
    await bridge.send("tekrar")
    ev = await collect_until_result(bridge)
    assert "tekrar" in text_of(ev)
    assert last_command_args(args_log)[-2:] == ["--resume", sid]


async def test_interrupt_answered(bridge):
    await bridge.send("yavaş")
    await asyncio.sleep(0.2)
    await bridge.interrupt(timeout=3)
    assert isinstance((await collect_until_result(bridge))[-1], TurnResult)


async def test_interrupt_ignored_kills_and_resumes(bridge_ignoring):
    await bridge_ignoring.send("yavaş")
    await asyncio.sleep(0.5)
    started = time.monotonic()
    await bridge_ignoring.interrupt(timeout=1)
    result = (await collect_until_result(bridge_ignoring))[-1]
    assert result.is_error and time.monotonic() - started < 3
    await bridge_ignoring.send("devam")
    assert "devam" in text_of(await collect_until_result(bridge_ignoring))


async def test_very_long_output_line(bridge):
    await bridge.send("uzun")
    assert "uzun" in text_of(await collect_until_result(bridge))


async def test_new_session_forgets_id(bridge, store, args_log):
    await bridge.send("merhaba")
    await collect_until_result(bridge)
    await bridge.new_session()
    assert store.load() is None or "--resume" not in last_command_args(args_log)
    await bridge.send("yeni")
    await collect_until_result(bridge)
    assert "--resume" not in last_command_args(args_log)


def test_child_env_strips_nesting():
    env = child_env({"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "PATH": "x"})
    assert "CLAUDECODE" not in env and "CLAUDE_CODE_ENTRYPOINT" not in env
    assert env["PATH"] == "x" and env["PYTHONIOENCODING"] == "utf-8"


def test_build_command_flags():
    cmd = build_command("claude.exe", "sid-1")
    assert cmd[0] == "claude.exe" and cmd[-2:] == ["--resume", "sid-1"]
    for flag in ("-p", "--verbose", "--include-partial-messages", "--disable-slash-commands"):
        assert flag in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "bypassPermissions"
    assert cmd[cmd.index("--append-system-prompt-file") + 1].endswith("asistan\\ASISTAN.md")
    assert "--resume" not in build_command("claude.exe", None)
