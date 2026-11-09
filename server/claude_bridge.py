"""Drive one long-lived `claude -p` process over stream-json."""

from __future__ import annotations

import asyncio
import os
from collections import deque
from collections.abc import AsyncIterator, Callable, Mapping

from server.claude_events import Event, SessionInit, TurnResult, interrupt_request, parse_line, user_message
from server.config import ROOT
from server.session_store import SessionStore

ASSISTANT_PROMPT = ROOT / "asistan" / "ASISTAN.md"
# Tool results travel on single stdout lines and can run to megabytes.
LINE_LIMIT = 64 * 1024 * 1024
_NESTING_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


def build_command(claude_exe: str, session_id: str | None) -> list[str]:
    command = [
        claude_exe,
        "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--permission-mode", "bypassPermissions",
        # The user's plugins load into headless sessions too; skills such as
        # brainstorming would turn "plan my day" into a design interview.
        "--disable-slash-commands",
        "--append-system-prompt-file", str(ASSISTANT_PROMPT),
    ]
    if session_id:
        command += ["--resume", session_id]
    return command


def child_env(base: Mapping[str, str]) -> dict[str, str]:
    """The environment for claude: no nested-session markers, UTF-8 I/O."""
    env = {k: v for k, v in base.items() if k not in _NESTING_VARS}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


class ClaudeBridge:
    def __init__(
        self,
        workdir: str,
        store: SessionStore,
        command_factory: Callable[[str | None], list[str]],
    ) -> None:
        self._workdir = workdir
        self._store = store
        self._command_factory = command_factory
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task | None = None
        self._turn_active = False
        self._turn_done = asyncio.Event()
        self._requests = 0
        self.stderr_tail: deque[str] = deque(maxlen=40)

    async def start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *self._command_factory(self._store.load()),
            cwd=self._workdir,
            env=child_env(os.environ),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=LINE_LIMIT,
        )
        self._reader = asyncio.create_task(self._read(self._proc))
        asyncio.create_task(self._drain_stderr(self._proc))

    async def send(self, text: str) -> None:
        if self._proc is None or self._proc.returncode is not None:
            # A crashed or killed process is replaced lazily, resuming the session,
            # so a process that dies on launch cannot restart in a loop.
            await self.start()
        self._turn_active = True
        self._turn_done.clear()
        await self._write(user_message(text))

    async def events(self) -> AsyncIterator[Event]:
        while True:
            yield await self._queue.get()

    async def interrupt(self, timeout: float = 3.0) -> None:
        if not self._turn_active or self._proc is None:
            return
        self._requests += 1
        await self._write(interrupt_request(f"interrupt-{self._requests}"))
        try:
            await asyncio.wait_for(self._turn_done.wait(), timeout)
        except TimeoutError:
            # The reader sees the exit and ends the turn with an error result.
            self._proc.kill()

    async def new_session(self) -> None:
        self._store.clear()
        await self._stop()

    async def close(self) -> None:
        await self._stop()

    async def _write(self, line: str) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            return
        try:
            proc.stdin.write(line.encode("utf-8"))
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass  # The reader reports the exit.

    async def _read(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        while line := await proc.stdout.readline():
            for event in parse_line(line.decode("utf-8", errors="replace")):
                if isinstance(event, (SessionInit, TurnResult)) and event.session_id:
                    self._store.save(event.session_id)
                if isinstance(event, TurnResult):
                    self._finish_turn(event)
                else:
                    self._queue.put_nowait(event)
        await proc.wait()
        if proc is self._proc:
            self._proc = None
        if self._turn_active:
            self._finish_turn(TurnResult(self._store.load() or "", is_error=True))

    def _finish_turn(self, result: TurnResult) -> None:
        self._turn_active = False
        self._turn_done.set()
        self._queue.put_nowait(result)

    async def _drain_stderr(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stderr is not None
        while line := await proc.stderr.readline():
            self.stderr_tail.append(line.decode("utf-8", errors="replace").rstrip())

    async def _stop(self) -> None:
        proc, reader = self._proc, self._reader
        self._proc = None
        self._turn_active = False
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        if reader is not None:
            await reader
