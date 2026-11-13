"""Work branches: each code job gets its own git worktree, so a bad job never touches the project.

The terminal's Cuba opens one with tools/dal.py before handing code work to the team; Çağan then
hears what changed and says merge or throw away. Branches are named `cuba/<slug>` and their folders
sit beside the project in `<project>-isler/<slug>`.
"""

from __future__ import annotations

import re
import subprocess
import unicodedata
from pathlib import Path

PREFIX = "cuba/"


class DalError(Exception):
    """A git step failed; the message says why, in Turkish."""


def _git(folder: str | Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise DalError(f"git çalışmadı: {e}") from e
    if done.returncode != 0:
        raise DalError((done.stderr or done.stdout).strip()[:300] or f"git {args[0]} başarısız")
    return done.stdout


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.replace("ı", "i")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:40] or "is"


def is_repo(folder: str | Path) -> bool:
    try:
        return _git(folder, "rev-parse", "--is-inside-work-tree").strip() == "true"
    except DalError:
        return False


def _root(folder: str | Path) -> Path:
    return Path(_git(folder, "rev-parse", "--show-toplevel").strip())


def _main_branch(root: Path) -> str:
    return _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()


def open_branch(folder: str | Path, name: str) -> dict:
    """A fresh worktree for the job *name*, branched from what the project has checked out now."""
    root = _root(folder)
    branch = PREFIX + slug(name)
    path = root.parent / f"{root.name}-isler" / slug(name)
    if path.exists():
        return {"dal": branch, "klasor": str(path), "not": "Bu iş dalı zaten açık; onda devam et."}
    _git(root, "worktree", "add", "-b", branch, str(path))
    return {"dal": branch, "klasor": str(path), "ana": _main_branch(root)}


def branches(folder: str | Path) -> list[dict]:
    """The open work branches: their folder and what they changed against the project's branch."""
    root = _root(folder)
    main = _main_branch(root)
    found, path = [], ""
    for line in _git(root, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line.removeprefix("worktree ")
        elif line.startswith("branch refs/heads/" + PREFIX):
            branch = line.removeprefix("branch refs/heads/")
            # Committed work and what is still only in the folder both count.
            committed = _git(root, "diff", "--shortstat", f"{main}...{branch}").strip()
            pending = _git(path, "status", "--porcelain").strip()
            found.append({"dal": branch, "klasor": path, "degisiklik": committed or "commit yok",
                          "kaydedilmemis": len(pending.splitlines()) if pending else 0})
    return found


def _find(folder: str | Path, wanted: str) -> dict:
    open_ = branches(folder)
    key = slug(wanted.removeprefix(PREFIX))
    for b in open_:
        if b["dal"] == wanted or b["dal"] == PREFIX + key:
            return b
    matches = [b for b in open_ if key in b["dal"]]
    if len(matches) == 1:
        return matches[0]
    raise DalError(f"'{wanted}' diye açık iş dalı yok. Açık olanlar: {', '.join(b['dal'] for b in open_) or 'yok'}")


def diff(folder: str | Path, wanted: str, chars: int = 4000) -> dict:
    b = _find(folder, wanted)
    root = _root(folder)
    stat = _git(root, "diff", "--stat", f"{_main_branch(root)}...{b['dal']}").strip()
    pending = _git(b["klasor"], "status", "--short").strip()
    return {"dal": b["dal"], "ozet": stat[-chars:] or "commit yok", "kaydedilmemis": pending[:1000]}


def merge(folder: str | Path, wanted: str) -> dict:
    """Merge the branch into the project's branch and remove its worktree; a conflict leaves nothing half done."""
    b = _find(folder, wanted)
    if b["kaydedilmemis"]:
        raise DalError(f"{b['dal']} klasöründe commit edilmemiş {b['kaydedilmemis']} dosya var; önce ekip commit etmeli.")
    root = _root(folder)
    if _git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise DalError("Projenin kendisinde commit edilmemiş değişiklik var; birleştirmeden önce temizlenmeli.")
    try:
        _git(root, "merge", "--no-ff", "-m", f"Merge {b['dal']}", b["dal"])
    except DalError as e:
        try:
            _git(root, "merge", "--abort")
        except DalError:
            pass
        raise DalError(f"Çakışma var, birleştirme geri alındı: {e}") from e
    _git(root, "worktree", "remove", b["klasor"])
    _git(root, "branch", "-d", b["dal"])
    return {"ok": True, "dal": b["dal"], "ana": _main_branch(root)}


def discard(folder: str | Path, wanted: str) -> dict:
    """Throw the branch and its folder away: only on Çağan's word."""
    b = _find(folder, wanted)
    root = _root(folder)
    _git(root, "worktree", "remove", "--force", b["klasor"])
    _git(root, "branch", "-D", b["dal"])
    return {"ok": True, "dal": b["dal"], "not": "İş dalı silindi; proje değişmedi."}
