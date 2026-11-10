"""The folders the team can work in: Claude Code's own projects plus added ones."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
_WINDOWS_PATH = re.compile(r"^[A-Za-z]:\\")
# Claude's own scratch and memory-observer sessions are not the user's projects.
_NOISE = re.compile(r"\\scratch-\d{4}-\d{2}-\d{2}-|observer-sessions")
_HEAD_LINES = 60


def _cwd_of(session: Path) -> str | None:
    """The working directory recorded in a Claude Code session file."""
    try:
        with session.open(encoding="utf-8", errors="replace") as lines:
            for _, line in zip(range(_HEAD_LINES), lines):
                try:
                    cwd = json.loads(line).get("cwd")
                except (ValueError, AttributeError):
                    continue
                if isinstance(cwd, str) and _WINDOWS_PATH.match(cwd):
                    return cwd
    except OSError:
        pass
    return None


def discover(claude_projects: Path = CLAUDE_PROJECTS) -> list[str]:
    """Folders Claude Code has been used in, most recently used first."""
    found: list[tuple[float, str]] = []
    try:
        folders = [p for p in claude_projects.iterdir() if p.is_dir()]
    except OSError:
        return []
    for folder in folders:
        # The folder name is a lossy encoding of the path ("ç" becomes "-"),
        # so the real path is read from the newest session inside.
        sessions = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        for session in sessions[:3]:
            cwd = _cwd_of(session)
            if cwd and not _NOISE.search(cwd):
                found.append((sessions[0].stat().st_mtime, cwd))
                break
    found.sort(reverse=True)
    return [path for _, path in found]


def project_name(path: str) -> str:
    return Path(path).name or path


def project_slug(path: str) -> str:
    """A folder-safe, collision-free name for a project's saved state."""
    digest = hashlib.sha1(path.lower().encode("utf-8")).hexdigest()[:8]
    name = re.sub(r"[^A-Za-z0-9]+", "-", project_name(path)).strip("-")[:40]
    return f"{name}-{digest}" if name else digest


class ProjectList:
    def __init__(self, path: Path, default: str, claude_projects: Path = CLAUDE_PROJECTS) -> None:
        self._path = path
        self._default = default
        self._claude_projects = claude_projects

    def _load(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    @property
    def current(self) -> str:
        current = self._load().get("current")
        return current if isinstance(current, str) and Path(current).is_dir() else self._default

    def select(self, path: str) -> None:
        self._save({**self._load(), "current": path})

    def add(self, path: str) -> str | None:
        """Remember *path* as a project; returns its normal form, or None if it is not a folder."""
        folder = Path(path.strip().strip('"'))
        if not folder.is_absolute() or not folder.is_dir():
            return None
        normal = str(folder)
        data = self._load()
        added = [p for p in data.get("added", []) if p != normal]
        self._save({**data, "added": [normal, *added]})
        return normal

    def paths(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        candidates = [*self._load().get("added", []), *discover(self._claude_projects), self._default]
        for path in candidates:
            key = path.lower().rstrip("\\")
            if key in seen or not Path(path).is_dir():
                continue
            seen.add(key)
            ordered.append(path)
        return ordered

    def listing(self) -> dict:
        return {
            "type": "projects",
            "current": self.current,
            "projects": [{"path": p, "name": project_name(p)} for p in self.paths()],
        }
