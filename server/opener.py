"""Cuba opens things on this PC when Çağan asks: a song on YouTube, a site, a document, a program."""

from __future__ import annotations

import os
import re
import subprocess
import urllib.parse
import webbrowser
from collections.abc import Callable
from pathlib import Path

import httpx

from server.config import BELGELER

KINDS = ("youtube", "site", "dosya", "uygulama")
VIDEO_ID = re.compile(r'"videoId":"([\w-]{11})"')


async def first_video(query: str) -> str | None:
    """The first YouTube result for *query*, as a watch address that starts playing."""
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    async with httpx.AsyncClient(timeout=10, headers={"Accept-Language": "tr-TR"}) as client:
        page = (await client.get(url)).text
    found = VIDEO_ID.search(page)
    return f"https://www.youtube.com/watch?v={found.group(1)}" if found else None


def find_document(name: str, root: Path = BELGELER) -> Path | None:
    """A document under the desktop's belgeler folder whose name holds every word asked for, newest first."""
    path = Path(name)
    if path.is_absolute():
        return path if path.is_file() else None
    words = [w for w in re.split(r"[\s_\-./\\]+", name.casefold()) if w]
    found = [f for f in root.rglob("*") if f.is_file() and all(w in f.as_posix().casefold() for w in words)]
    return max(found, key=lambda f: f.stat().st_mtime) if found else None


class Opener:
    def __init__(self, browse: Callable[[str], object] = webbrowser.open,
                 start: Callable[[str], None] = os.startfile, root: Path = BELGELER) -> None:
        self._browse = browse
        self._start = start
        self._root = root

    async def open(self, kind: str, what: str) -> dict:
        what = what.strip()
        if not what:
            return {"error": "Neyi açacağım belli değil."}
        if kind == "youtube":
            url = await first_video(what) or "https://www.youtube.com/results?search_query=" + urllib.parse.quote(what)
            self._browse(url)
            return {"ok": True, "acildi": url}
        if kind == "site":
            if re.match(r"^https?://", what):
                url = what
            elif re.fullmatch(r"[\w.-]+\.[a-z]{2,}(/\S*)?", what, re.I):
                url = f"https://{what}"
            else:
                url = "https://www.google.com/search?q=" + urllib.parse.quote(what)
            self._browse(url)
            return {"ok": True, "acildi": url}
        if kind == "dosya":
            found = find_document(what, self._root)
            if found is None:
                return {"error": f"Belgeler klasöründe '{what}' bulunamadı."}
            self._start(str(found))
            return {"ok": True, "acildi": str(found)}
        if kind == "uygulama":
            subprocess.Popen(["cmd", "/c", "start", "", what], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return {"ok": True, "acildi": what}
        return {"error": f"Bilinmeyen tür: {kind}"}
