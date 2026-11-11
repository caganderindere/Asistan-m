"""A real PowerShell, with interactive Claude Code in it, for the browser.

The terminal runs Claude Code exactly as a console window would; its replies
reach the voice through a Stop hook (tools/terminal_hook.py) that posts the
last answer back to the server.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from server.claude_bridge import child_env
from server.config import ROOT

HOOK = ROOT / "tools" / "terminal_hook.py"
SCROLLBACK_CHARS = 200_000
SPOKEN_LIMIT = 400
MORE_ON_SCREEN = "Ayrıntılar ekranda."
PERMISSION_LINE = "Onayın gerekiyor efendim. Evet ya da hayır de."
# Claude Code starts a subagent with one of these tools.
AGENT_TOOLS = ("Task", "Agent")
# The office's desks: the lead's for Claude itself, the others for its subagents.
LEAD_DESK = "lider"
SUB_DESKS = ("kidemli", "gelistirici", "testci", "asistan")
LOG_LINES = 12
ROLE_NAMES = {"kidemli": "Kıdemli", "gelistirici": "Geliştirici", "testci": "Testçi", "asistan": "Asistan"}


def hook_settings(
    python: str, out_dir: Path, charter: Path | None = None, allow: tuple[str, ...] = ()
) -> Path:
    """Write the settings file that makes the terminal's Claude speak through us."""
    command = f'"{python}" "{HOOK}"'

    def hook(kind: str, matcher: str | None = None, timeout: int = 10) -> list[dict]:
        entry: dict = {"hooks": [{"type": "command", "command": f"{command} {kind}", "timeout": timeout}]}
        if matcher is not None:
            entry["matcher"] = matcher
        return [entry]

    settings = {
        "hooks": {
            # Long enough for Daim to think over the answer while the user is away.
            "Stop": hook("stop", timeout=90),
            # Tells the terminal's Claude it is Daim, who its team is and whose orders count.
            **({"SessionStart": hook(f'session_start "{charter}"')} if charter else {}),
            "PermissionRequest": hook("permission_request", "*"),
            "Notification": hook("permission", "permission_prompt"),
            "UserPromptSubmit": hook("prompt"),
            "PreToolUse": hook("pre", "*"),
            "PostToolUse": hook("post", "|".join(AGENT_TOOLS)),
        },
        # Walking around the office is not worth asking Çağan about.
        "permissions": {"allow": [f"Bash({command}:*)" for command in allow]},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "terminal-settings.json"
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return path


def powershell_command(
    claude_exe: str, settings: Path, model: str = "", plugin: Path | None = None
) -> list[str]:
    """PowerShell that starts Claude at once; typing `claude` later keeps the hook too."""
    model_arg = f" --model '{model}'" if model else ""
    if plugin is not None:
        model_arg += f" --plugin-dir '{plugin}'"
    init = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        f"function claude {{ & '{claude_exe}' --settings '{settings}'{model_arg} @args }}; "
        "claude"
    )
    return ["powershell.exe", "-NoLogo", "-NoExit", "-Command", init]


def spoken(text: str) -> str:
    """The part of a written answer worth reading aloud: prose only, a few sentences."""
    text = re.sub(r"```.*?(```|$)", " ", text, flags=re.S)
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("|") or set(line) <= set("-=*_ "):
            continue
        line = re.sub(r"^(#+|[-*+]|\d+[.)])\s+", "", line)
        lines.append(line if line[-1] in ".!?:" else line + ".")
    prose = " ".join(lines)
    prose = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", prose)
    prose = re.sub(r"[*_`]+", "", prose)
    prose = re.sub(r"\s+", " ", prose).strip()
    if len(prose) <= SPOKEN_LIMIT:
        return prose
    cut = max(prose.rfind(mark, 0, SPOKEN_LIMIT) for mark in ".!?")
    head = prose[: cut + 1] if cut > 0 else prose[:SPOKEN_LIMIT]
    return f"{head} {MORE_ON_SCREEN}"


class Terminal:
    """One pseudo-console shared by every viewer, kept alive across page reloads."""

    def __init__(self, argv: list[str], cwd: str, spawn: Callable | None = None) -> None:
        self._argv = argv
        self._cwd = cwd
        self._spawn = spawn
        self._proc = None
        self._scrollback: deque[str] = deque()
        self._size = 0
        self._listeners: set[asyncio.Queue[str]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.isalive()

    def start(self, cols: int = 120, rows: int = 30) -> None:
        if self.alive:
            return
        spawn = self._spawn
        if spawn is None:
            from winpty import PtyProcess

            spawn = PtyProcess.spawn
        self._loop = asyncio.get_running_loop()
        self._scrollback.clear()
        self._size = 0
        self._proc = spawn(self._argv, cwd=self._cwd, env=child_env(os.environ), dimensions=(rows, cols))
        threading.Thread(target=self._read, args=(self._proc,), daemon=True).start()

    def write(self, data: str) -> None:
        if self.alive:
            self._proc.write(data)

    def resize(self, cols: int, rows: int) -> None:
        if self.alive and cols > 0 and rows > 0:
            self._proc.setwinsize(rows, cols)

    def history(self) -> str:
        return "".join(self._scrollback)

    def listen(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._listeners.add(queue)
        return queue

    def unlisten(self, queue: asyncio.Queue[str]) -> None:
        self._listeners.discard(queue)

    def close(self) -> None:
        if self.alive:
            self._proc.terminate(force=True)
        self._proc = None

    def _read(self, proc) -> None:
        while True:
            try:
                data = proc.read(4096)
            except EOFError:
                break
            if data and self._loop is not None:
                self._loop.call_soon_threadsafe(self._publish, data)
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._publish, "\r\n[Terminal kapandı. Yeniden açmak için sayfayı yenileyin.]\r\n")

    def _publish(self, data: str) -> None:
        self._scrollback.append(data)
        self._size += len(data)
        while self._size > SCROLLBACK_CHARS and len(self._scrollback) > 1:
            self._size -= len(self._scrollback.popleft())
        for queue in self._listeners:
            queue.put_nowait(data)


def tool_summary(tool_input: dict) -> str:
    for key in ("description", "command", "file_path", "pattern", "url", "prompt"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().splitlines()[0][:80]
    return ""


class TerminalCrew:
    """Who in the terminal's Claude session is doing what, drawn as the office's people."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.question = ""
        self._desks = {
            desk: {"name": "Claude Code" if desk == LEAD_DESK else "Alt ajan", "state": "idle",
                   "activity": "", "since": clock(), "key": "", "agent": "",
                   "log": deque(maxlen=LOG_LINES)}
            for desk in (LEAD_DESK, *SUB_DESKS)
        }

    def prompt(self) -> None:
        self.question = ""
        self._work(LEAD_DESK, "Düşünüyor")

    def tool(self, name: str, tool_input: dict, use_id: str = "", agent: str = "") -> None:
        summary = tool_summary(tool_input)
        if name in AGENT_TOOLS:
            free = next((d for d in SUB_DESKS if self._desks[d]["state"] == "idle"), None)
            self._work(LEAD_DESK, f"Ajan başlattı: {summary}")
            # A team member sits at its own desk when it is free.
            role = str(tool_input.get("subagent_type") or "").rpartition(":")[2]
            if role in SUB_DESKS and self._desks[role]["state"] == "idle":
                free = role
            if free is not None:
                name = ROLE_NAMES.get(role) or role or "Alt ajan"
                self._desks[free].update(key=use_id, agent="", name=name)
                self._work(free, summary or "Görevde")
            return
        self._work(self._desk_of(agent), f"{name}: {summary}" if summary else name)

    def tool_done(self, name: str, use_id: str) -> None:
        if name not in AGENT_TOOLS:
            return
        for desk_id in SUB_DESKS:
            if self._desks[desk_id]["key"] == use_id:
                self._rest(desk_id)

    def stop(self) -> None:
        self.question = ""
        for desk_id in self._desks:
            self._rest(desk_id)

    def permission(self) -> None:
        self.question = "Claude onayını bekliyor."

    def snapshot(self) -> dict:
        now = self._clock()
        working = any(d["state"] == "working" for d in self._desks.values())
        return {
            "type": "terminal_team",
            "phase": "working" if working else "idle",
            "question": self.question,
            "review": None,
            "tasks": [],
            "agents": [
                {"id": desk_id, "name": d["name"], "department": "Terminal", "duty": "", "model": "",
                 "state": d["state"], "activity": d["activity"], "seconds": round(now - d["since"]),
                 "task": None, "log": list(d["log"])}
                for desk_id, d in self._desks.items()
            ],
        }

    def _desk_of(self, agent: str) -> str:
        """The desk of the subagent behind *agent*; Claude itself when there is none."""
        if not agent:
            return LEAD_DESK
        busy = [d for d in SUB_DESKS if self._desks[d]["state"] == "working"]
        for desk_id in busy:
            if self._desks[desk_id]["agent"] == agent:
                return desk_id
        # A subagent's first tool call: it sits at the oldest desk not yet claimed.
        for desk_id in busy:
            if not self._desks[desk_id]["agent"]:
                self._desks[desk_id]["agent"] = agent
                return desk_id
        return LEAD_DESK

    def _work(self, desk_id: str, activity: str) -> None:
        desk = self._desks[desk_id]
        if desk["state"] != "working":
            desk["since"] = self._clock()
        desk.update(state="working", activity=activity)
        desk["log"].append(activity)

    def _rest(self, desk_id: str) -> None:
        desk = self._desks[desk_id]
        if desk["state"] == "working":
            desk["since"] = self._clock()
        desk.update(state="idle", activity="", key="", agent="")
