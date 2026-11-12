"""How many tokens today cost: Claude read from its own session files, Gemini counted as it answers.

Claude Code writes every reply, with its token usage, to ~/.claude/projects/*/*.jsonl; reading
those counts all of today's Claude work, in the terminal or anywhere else. Gemini replies carry
usageMetadata, which the bridges hand to GEMINI.add().
"""

from __future__ import annotations

import datetime
import json
import threading
from pathlib import Path

from server.projects import CLAUDE_PROJECTS


def _today() -> str:
    return datetime.date.today().isoformat()


class GeminiMeter:
    """Gemini tokens per day, kept on disk so a restart does not reset the count."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._days: dict[str, dict[str, int]] = self._load()

    def use(self, path: Path) -> None:
        self._path = path
        self._days = self._load()

    def add(self, usage: dict | None) -> None:
        """Count one reply's usageMetadata."""
        if not usage:
            return
        with self._lock:
            day = self._days.setdefault(_today(), {"input": 0, "output": 0})
            day["input"] += int(usage.get("promptTokenCount") or 0)
            day["output"] += int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0)
            self._days = dict(sorted(self._days.items())[-31:])
            self._save()

    def today(self) -> dict[str, int]:
        return dict(self._days.get(_today(), {"input": 0, "output": 0}))

    def _load(self) -> dict:
        if self._path is None:
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._days), encoding="utf-8")


GEMINI = GeminiMeter()


class ClaudeMeter:
    """Today's Claude tokens, from the session files; each call reads only what was added since."""

    def __init__(self, root: Path = CLAUDE_PROJECTS) -> None:
        self._root = root
        self._day = ""
        self._offsets: dict[Path, int] = {}
        self._seen: set[str] = set()  # a streamed reply is written several times under one id
        self._totals = {"input": 0, "output": 0, "cache": 0}

    def today(self) -> dict[str, int]:
        day = _today()
        if day != self._day:
            self._day, self._offsets, self._seen = day, {}, set()
            self._totals = {"input": 0, "output": 0, "cache": 0}
        midnight = datetime.datetime.combine(datetime.date.today(), datetime.time()).timestamp()
        try:
            files = [f for f in self._root.glob("*/*.jsonl") if f.stat().st_mtime >= midnight]
        except OSError:
            files = []
        for file in files:
            self._read(file, day)
        return dict(self._totals)

    def _read(self, file: Path, day: str) -> None:
        try:
            with file.open("rb") as f:
                f.seek(self._offsets.get(file, 0))
                data = f.read()
        except OSError:
            return
        # A line still being written is read next time.
        end = data.rfind(b"\n") + 1
        self._offsets[file] = self._offsets.get(file, 0) + end
        for raw in data[:end].splitlines():
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            message = entry.get("message") if isinstance(entry, dict) else None
            if entry.get("type") != "assistant" or not isinstance(message, dict):
                continue
            usage = message.get("usage") or {}
            key = f"{message.get('id')}:{entry.get('requestId')}"
            if not usage or key in self._seen or not _local_day(entry.get("timestamp", "")) == day:
                continue
            self._seen.add(key)
            self._totals["input"] += int(usage.get("input_tokens") or 0)
            self._totals["output"] += int(usage.get("output_tokens") or 0)
            self._totals["cache"] += int(usage.get("cache_read_input_tokens") or 0) + int(
                usage.get("cache_creation_input_tokens") or 0
            )


def _local_day(stamp: str) -> str:
    try:
        moment = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return moment.astimezone().date().isoformat()
