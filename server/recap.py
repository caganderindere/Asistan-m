"""What Çağan and Claude have been doing, told back by Cuba: a day or a week, or one project's state.

Claude Code keeps every session under ~/.claude/projects as JSONL; Çağan's own requests there, with the
commits made in the same days, say what was worked on. A project's state comes from its git history,
uncommitted changes, open work branches and the documents on the desktop. Gemini turns either into a few
spoken sentences, so none of this spends Claude tokens.
"""

from __future__ import annotations

import datetime
import json
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

from server.config import doc_folder

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
SKIP_DIRS = ("observer-sessions",)  # claude-mem's own background sessions, not Çağan's work
REQUEST_CHARS = 220
MAX_REQUESTS = 300
PERIODS = {"bugun": 0, "dun": 1, "hafta": 6}

RECAP_PROMPT = """Sen Cuba'sın, Çağan'ın sesli asistanı. Aşağıda Çağan'ın {period} Claude Code'a verdiği istekler
(saat, klasör, istek) ve aynı günlerde projelere atılan commit'ler var. Ona "ne yaptık" sorusunun cevabını ver:
Türkçe, sesli okunacak, en fazla sekiz cümle; liste ya da işaret kullanma. Projelere göre grupla, en önemli işleri
öne al, ne bittiğini ve ne yarım kaldığını söyle. Klasör yollarını değil proje adlarını söyle. Metinde olmayanı yazma."""

STATE_PROMPT = """Sen Cuba'sın, Çağan'ın sesli asistanı. Aşağıda {project} projesinin durumu var: son commit'ler,
kaydedilmemiş değişiklikler, açık iş dalları, son belgeler ve son günlerde Claude'a verilen istekler.
"Ne durumda?" sorusuna cevap ver: Türkçe, sesli okunacak, en fazla altı cümle; liste kullanma. Son yapılanı,
yarım kalanı ve sıradaki mantıklı adımı söyle. Metinde olmayanı yazma."""

Ask = Callable[[str, str, bool], Awaitable[str]]


def _git(folder: str | Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def period_start(period: str, now: datetime.datetime | None = None) -> datetime.datetime:
    today = (now or datetime.datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - datetime.timedelta(days=PERIODS.get(period, 0))


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def claude_requests(since: datetime.datetime, until: datetime.datetime | None = None,
                    root: Path = CLAUDE_PROJECTS) -> list[dict]:
    """Çağan's own requests to Claude Code since *since*, oldest first: {time, folder, text}."""
    found = []
    stamp = since.timestamp()
    for session in root.glob("*/*.jsonl"):
        if any(skip in session.parent.name for skip in SKIP_DIRS) or session.stat().st_mtime < stamp:
            continue
        with session.open(encoding="utf-8", errors="replace") as lines:
            for raw in lines:
                if '"user"' not in raw:  # cheap skip before parsing; most lines are tool traffic
                    continue
                try:
                    entry = json.loads(raw)
                except ValueError:
                    continue
                if entry.get("type") != "user" or "toolUseResult" in entry or entry.get("isSidechain") or entry.get("isMeta"):
                    continue
                text = " ".join(_text((entry.get("message") or {}).get("content")).split())
                if not text or text.startswith(("<", "[Request interrupted", "Caveat:")):
                    continue
                try:
                    when = datetime.datetime.fromisoformat(str(entry.get("timestamp", "")).replace("Z", "+00:00"))
                except ValueError:
                    continue
                when = when.astimezone().replace(tzinfo=None)
                if when < since or (until is not None and when >= until):
                    continue
                found.append({"time": when, "folder": str(entry.get("cwd", "")), "text": text[:REQUEST_CHARS]})
    found.sort(key=lambda r: r["time"])
    return found[-MAX_REQUESTS:]


def commits(folder: str | Path, since: datetime.datetime, until: datetime.datetime | None = None) -> list[str]:
    args = ["log", "--all", f"--since={since:%Y-%m-%d %H:%M}", "--format=%ad %s", "--date=format:%m-%d %H:%M"]
    if until is not None:
        args.insert(3, f"--until={until:%Y-%m-%d %H:%M}")
    out = _git(folder, *args)
    return out.splitlines()[:60] if out else []


def _folders(requests: list[dict], projects: list[dict]) -> list[str]:
    """Every folder worked in: the ones Claude ran in and Cuba's projects, each git root once."""
    seen, roots = set(), []
    for folder in [r["folder"] for r in requests] + [p["path"] for p in projects]:
        if not folder or folder in seen or not Path(folder).is_dir():
            continue
        seen.add(folder)
        root = _git(folder, "rev-parse", "--show-toplevel")
        if root and root not in roots:
            roots.append(root)
    return roots


async def recap(ask: Ask, period: str, projects: list[dict], root: Path = CLAUDE_PROJECTS,
                now: datetime.datetime | None = None) -> dict:
    """What was done in *period* (bugun, dun, hafta), in Cuba's words."""
    since = period_start(period, now)
    until = since + datetime.timedelta(days=1) if period == "dun" else None
    requests = claude_requests(since, until, root)
    done = {Path(f).name: commits(f, since, until) for f in _folders(requests, projects)}
    done = {name: lines for name, lines in done.items() if lines}
    if not requests and not done:
        return {"ozet": "Bu dönemde Claude Code'da bir iş görünmüyor."}
    asked = "\n".join(f"{r['time']:%m-%d %H:%M} [{Path(r['folder']).name}] {r['text']}" for r in requests)
    made = "\n\n".join(f"## {name}\n" + "\n".join(lines) for name, lines in done.items())
    label = {"bugun": "bugün", "dun": "dün", "hafta": "bu hafta"}.get(period, "bugün")
    text = await ask(RECAP_PROMPT.format(period=label), f"# İstekler\n{asked}\n\n# Commit'ler\n{made}", False)
    return {"ozet": text.strip(), "istek_sayisi": len(requests), "projeler": list(done)}


def project_facts(folder: str | Path, root: Path = CLAUDE_PROJECTS, now: datetime.datetime | None = None) -> str:
    """What can be known about the project without asking anyone."""
    week = period_start("hafta", now)
    folder = Path(folder)
    changed = _git(folder, "status", "--porcelain").splitlines()
    branches = [b.strip("* ").strip() for b in _git(folder, "branch", "--list", "cuba/*").splitlines()]
    docs_dir = doc_folder(folder)
    docs = sorted((f for f in docs_dir.glob("*") if f.is_file()), key=lambda f: f.stat().st_mtime, reverse=True)[:6] \
        if docs_dir.is_dir() else []
    asked = [r for r in claude_requests(week, root=root)
             if r["folder"] and Path(r["folder"]).resolve().is_relative_to(folder.resolve())][-25:]
    made = "\n".join(commits(folder, week)[:25]) or "Bu hafta commit yok."
    papers = "\n".join(f"{d.name} ({datetime.datetime.fromtimestamp(d.stat().st_mtime):%m-%d})" for d in docs) or "yok"
    requests = "\n".join(f"{r['time']:%m-%d %H:%M} {r['text']}" for r in asked) or "yok"
    return (f"# Son commit'ler\n{made}\n\n"
            f"# Kaydedilmemiş değişiklik\n{len(changed)} dosya: {', '.join(l[3:] for l in changed[:12])}\n\n"
            f"# Açık iş dalları\n{', '.join(branches) or 'yok'}\n\n"
            f"# Son belgeler\n{papers}\n\n"
            f"# Bu hafta Claude'a verilen istekler\n{requests}")


async def project_state(ask: Ask, folder: str, root: Path = CLAUDE_PROJECTS) -> dict:
    facts = project_facts(folder, root)
    text = await ask(STATE_PROMPT.format(project=Path(folder).name), facts, False)
    return {"durum": text.strip()}
