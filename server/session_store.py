"""Persist the Claude session id so a conversation survives restarts."""

from __future__ import annotations

import json
from pathlib import Path


class SessionStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> str | None:
        try:
            return json.loads(self._path.read_text(encoding="utf-8")).get("session_id")
        except (FileNotFoundError, ValueError, AttributeError):
            return None

    def save(self, session_id: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"session_id": session_id}), encoding="utf-8")

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
