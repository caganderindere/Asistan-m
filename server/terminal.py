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
PERMISSION_LINE = "Onayın gerekiyor patron. Evet ya da hayır de."
# Claude Code starts a subagent with one of these tools.
AGENT_TOOLS = ("Task", "Agent")
# The office's desks: the lead's for Claude itself, the others for its subagents.
LEAD_DESK = "lider"
SUB_DESKS = ("kidemli", "gelistirici", "testci", "asistan")
LOG_LINES = 30
ROLE_NAMES = {"kidemli": "Kıdemli", "gelistirici": "Geliştirici", "testci": "Testçi", "asistan": "Asistan"}
# Tools that write code: what they write floats over the writer's desk.
CODE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
CODE_LINES = 40


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
            # Long enough for Cuba to think over the answer while the user is away.
            "Stop": hook("stop", timeout=90),
            # Tells the terminal's Claude it is Cuba, who its team is and whose orders count.
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

    def __init__(
        self, argv: list[str], cwd: str, spawn: Callable | None = None, env: dict[str, str] | None = None
    ) -> None:
        self._argv = argv
        self._cwd = cwd
        self._spawn = spawn
        self._env = env or {}
        self._proc = None
        self._scrollback: deque[str] = deque()
        self._size = 0
        self._listeners: set[asyncio.Queue[str]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.isalive()

    @property
    def cwd(self) -> str:
        return self._cwd

    def move_to(self, cwd: str) -> bool:
        """Work in *cwd* from now on; a Claude running elsewhere is closed. True if the folder changed."""
        if os.path.normcase(os.path.normpath(cwd)) == os.path.normcase(os.path.normpath(self._cwd)):
            return False
        self.close()
        self._cwd = cwd
        return True

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
        for queue in self._listeners:
            queue.put_nowait("\x1bc")  # open screens start over too
        self._proc = spawn(self._argv, cwd=self._cwd, env={**child_env(os.environ), **self._env}, dimensions=(rows, cols))
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
            self._loop.call_soon_threadsafe(self._publish, "\r\n[Terminal kapandı; gerektiğinde yeniden açılır.]\r\n")

    def _publish(self, data: str) -> None:
        self._scrollback.append(data)
        self._size += len(data)
        while self._size > SCROLLBACK_CHARS and len(self._scrollback) > 1:
            self._size -= len(self._scrollback.popleft())
        for queue in self._listeners:
            queue.put_nowait(data)


def folder_key(path: str) -> str:
    """One spelling per folder, whatever case or slashes it was written with."""
    return os.path.normcase(os.path.normpath(path)) if path else ""


class TerminalPool:
    """One terminal per project folder, so work in one project never stops another's."""

    def __init__(self, make: Callable[[str], Terminal]) -> None:
        self._make = make
        self._terminals: dict[str, Terminal] = {}
        self.asking: list[str] = []  # folders whose Claude waits for a yes, oldest first

    def get(self, cwd: str) -> Terminal:
        key = folder_key(cwd)
        if key not in self._terminals:
            self._terminals[key] = self._make(cwd)
        return self._terminals[key]

    def alive(self) -> list[str]:
        """The folders whose terminal is running."""
        return [t.cwd for t in self._terminals.values() if t.alive]

    def close(self) -> None:
        for terminal in self._terminals.values():
            terminal.close()


def tool_summary(tool_input: dict) -> str:
    for key in ("description", "command", "file_path", "pattern", "url", "prompt"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().splitlines()[0][:80]
    return ""


class TerminalCrew:
    """Who in the terminal's Claude session is doing what, drawn as the office's people."""

    def __init__(
        self, clock: Callable[[], float] = time.monotonic, names: Callable[[], dict[str, str]] = lambda: ROLE_NAMES
    ) -> None:
        self._clock = clock
        self._names = names  # every member's id → name, hires included
        self.question = ""
        self.reports: list[dict] = []  # what each subagent handed back this turn: {who, name, text}
        self.review: dict | None = None  # the meeting going on: {members, speaker, lines}
        self.tasks: list[dict] = []  # work the last meeting proposed
        self._desks: dict[str, dict] = {}
        for desk in (LEAD_DESK, *SUB_DESKS):
            self._add_desk(desk, "Cuba" if desk == LEAD_DESK else names().get(desk, "Alt ajan"))

    def _add_desk(self, desk: str, name: str) -> None:
        self._desks[desk] = {"name": name, "state": "idle", "activity": "", "since": self._clock(), "key": "",
                             "agent": "", "code": "", "file": "", "log": deque(maxlen=LOG_LINES)}

    @property
    def _subs(self) -> list[str]:
        return [d for d in self._desks if d != LEAD_DESK]

    def prompt(self) -> None:
        self.question = ""
        self.reports = []
        self._work(LEAD_DESK, "Düşünüyor")

    def tool(self, name: str, tool_input: dict, use_id: str = "", agent: str = "") -> None:
        summary = tool_summary(tool_input)
        if name in AGENT_TOOLS:
            role = str(tool_input.get("subagent_type") or "").rpartition(":")[2]
            names = self._names()
            if role in names and role not in self._desks:
                self._add_desk(role, names[role])  # someone hired since this terminal opened
            free = next((d for d in SUB_DESKS if self._desks[d]["state"] == "idle"), None)
            self._work(LEAD_DESK, f"Ajan başlattı: {summary}")
            # A team member sits at its own desk when it is free.
            if role in self._desks and role != LEAD_DESK and self._desks[role]["state"] == "idle":
                free = role
            if free is not None:
                self._desks[free].update(key=use_id, agent="", name=names.get(role) or role or "Alt ajan")
                self._work(free, summary or "Görevde")
            return
        desk = self._desk_of(agent)
        self._work(desk, f"{name}: {summary}" if summary else name)
        code = str(tool_input.get("new_string") or tool_input.get("content") or tool_input.get("new_source") or "")
        if name in CODE_TOOLS and code.strip():
            path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
            self._desks[desk].update(code="\n".join(code.splitlines()[:CODE_LINES]), file=os.path.basename(path))

    def tool_done(self, name: str, use_id: str, result: str = "") -> None:
        if name not in AGENT_TOOLS:
            return
        for desk_id in self._subs:
            if self._desks[desk_id]["key"] == use_id:
                if result.strip():
                    self.reports.append({"who": desk_id, "name": self._desks[desk_id]["name"], "text": result.strip()})
                self._rest(desk_id)

    @property
    def busy(self) -> bool:
        return any(d["state"] == "working" for d in self._desks.values()) or self.review is not None

    def stop(self) -> None:
        self.question = ""
        for desk_id in self._desks:
            self._rest(desk_id)

    def permission(self) -> None:
        self.question = "Claude onayını bekliyor."

    def _sync_staff(self) -> None:
        """Hires get a desk at once; someone who left goes once their desk is free."""
        names = self._names()
        for member, name in names.items():
            if member not in self._desks:
                self._add_desk(member, name)
        for desk in [d for d in self._desks if d not in (LEAD_DESK, *SUB_DESKS) and d not in names]:
            if self._desks[desk]["state"] != "working":
                del self._desks[desk]

    def snapshot(self) -> dict:
        self._sync_staff()
        now = self._clock()
        working = any(d["state"] == "working" for d in self._desks.values())
        return {
            "type": "terminal_team",
            "phase": "review" if self.review else "working" if working else "idle",
            "question": self.question,
            "review": self.review,
            "tasks": self.tasks,
            "agents": [
                {"id": desk_id, "name": d["name"], "department": "Terminal", "duty": "", "model": "",
                 "state": d["state"], "activity": d["activity"], "seconds": round(now - d["since"]),
                 "task": None, "log": list(d["log"]), "code": d["code"], "file": d["file"]}
                for desk_id, d in self._desks.items()
            ],
        }

    def _desk_of(self, agent: str) -> str:
        """The desk of the subagent behind *agent*; Claude itself when there is none."""
        if not agent:
            return LEAD_DESK
        busy = [d for d in self._subs if self._desks[d]["state"] == "working"]
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
        desk.update(state="idle", activity="", key="", agent="", code="", file="")
