"""What Cuba remembers: Çağan's notebook, every day's conversations, and a diary written from them.

asistan/cagan.md holds what is known about Çağan, in fixed sections. Every word spoken with
Cuba is logged per day under data/konusmalar; once a day is over Gemini turns it, with the
team's reports, into a short diary page and picks out anything new to learn about Çağan,
which is added under the right section of the notebook (never removing what is there).
"""

from __future__ import annotations

import datetime
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

logger = logging.getLogger(__name__)

SECTIONS = ("Kimlik", "Tercihler", "Çalışma biçimi", "Projeler", "İnsanlar", "Hedefler", "Sevmedikleri", "Düzeltmeler")
PROFILE_HEAD = (
    "# Çağan hakkında\n\n"
    "Cuba ve ekip Çağan hakkında öğrendiklerini buraya, uygun bölüme tek satır olarak ekler.\n"
)
DIARY_KEEP = 60
TALK_CHARS = 30000

DIARY_PROMPT = """Sen Cuba'sın, Çağan'ın kişisel asistanı. Aşağıda {day} günü Çağan'la konuşmaların ve ekibin
o gün verdiği raporlar var. İki şey yaz:
1. "gunluk": o günün kısa günlüğü, Türkçe, en çok on madde: Çağan ne istedi, ne yapıldı, ne yarım kaldı,
   neye dikkat etmek gerekiyor. Yalnızca metinde olanı yaz.
2. "ogrenilenler": Çağan hakkında kalıcı, yeni öğrenilen bilgiler (tercih, alışkanlık, önemli proje, kişi,
   hedef, hoşlanmadığı şey, Cuba'yı düzelttiği bir konu). Geçici şeyleri (bugünkü iş, saat) yazma.
   Defterde zaten olanı tekrar yazma. Her biri bir bölüm adı ve tek cümle.
Bölümler: {sections}

Defterin şu anki hâli:
{profile}

Yalnızca şu JSON'u döndür: {{"gunluk": "- ...\\n- ...", "ogrenilenler": [{{"bolum": "...", "bilgi": "..."}}]}}"""

Ask = Callable[[str, str, bool], Awaitable[str]]


def blank_profile() -> str:
    return PROFILE_HEAD + "".join(f"\n## {section}\n" for section in SECTIONS)


def ensure_profile(path: Path) -> None:
    """Give the notebook its sections; lines written before there were sections go under Kimlik."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    if all(f"## {section}" in text for section in SECTIONS):
        return
    loose = [line for line in text.splitlines() if line.startswith("- ")]
    profile = blank_profile()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(profile, encoding="utf-8")
    if loose:
        add_facts(path, [{"bolum": "Kimlik", "bilgi": line[2:]} for line in loose])


def add_facts(path: Path, facts: list[dict]) -> list[str]:
    """Add each new fact as a line under its section; return the ones added."""
    text = path.read_text(encoding="utf-8") if path.exists() else blank_profile()
    added = []
    for fact in facts:
        info = " ".join(str(fact.get("bilgi", "")).split())
        section = str(fact.get("bolum", "")).strip()
        if not info or info.casefold() in text.casefold():
            continue
        if section not in SECTIONS:
            section = "Kimlik"
        heading = f"## {section}\n"
        if heading not in text:
            text = text.rstrip("\n") + f"\n\n{heading}"
        # The section ends where the next heading begins.
        start = text.index(heading) + len(heading)
        nxt = text.find("\n## ", start)
        end = len(text) if nxt < 0 else nxt + 1
        body = text[start:end].rstrip("\n")
        body = f"{body}\n- {info}" if body.strip() else f"- {info}"
        text = text[:start] + body + "\n" + ("\n" if nxt >= 0 else "") + text[end:].lstrip("\n")
        added.append(info)
    path.write_text(text, encoding="utf-8")
    return added


class ConversationLog:
    """Everything said with Cuba, one file per day: data/konusmalar/YYYY-MM-DD.jsonl."""

    def __init__(self, folder: Path, clock: Callable[[], datetime.datetime] = datetime.datetime.now) -> None:
        self.folder = folder
        self._clock = clock

    def add(self, who: str, text: str, channel: str = "ses") -> None:
        text = " ".join(text.split())
        if not text:
            return
        now = self._clock()
        self.folder.mkdir(parents=True, exist_ok=True)
        line = {"time": now.strftime("%H:%M"), "who": who, "text": text, "channel": channel}
        with (self.folder / f"{now:%Y-%m-%d}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def day(self, day: str) -> list[dict]:
        try:
            raw = (self.folder / f"{day}.jsonl").read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        lines = []
        for row in raw.splitlines():
            try:
                lines.append(json.loads(row))
            except ValueError:
                continue
        return lines

    def days(self) -> list[str]:
        return sorted(p.stem for p in self.folder.glob("*.jsonl"))


class Diary:
    """One page per day in asistan/gunluk, written by Gemini from the day's talk and reports."""

    def __init__(self, memory_dir: Path, log: ConversationLog, ask: Ask | None) -> None:
        self.folder = memory_dir / "gunluk"
        self.profile = memory_dir / "cagan.md"
        self._log = log
        self._ask = ask

    def pages(self, limit: int = 14) -> list[dict]:
        found = sorted(self.folder.glob("*.md"), reverse=True)[:limit]
        return [{"day": p.stem, "text": p.read_text(encoding="utf-8")} for p in found]

    def latest(self, before: str) -> str:
        """The newest page older than *before*, for Cuba to remember yesterday by."""
        older = [p for p in sorted(self.folder.glob("*.md")) if p.stem < before]
        return f"{older[-1].stem}\n{older[-1].read_text(encoding='utf-8')}" if older else ""

    def missing(self, today: str) -> list[str]:
        """Past days that were talked through but have no page yet."""
        return [d for d in self._log.days() if d < today and not (self.folder / f"{d}.md").exists()]

    async def write(self, day: str, reports: list[dict]) -> dict | None:
        """Write *day*'s page and learn from it; returns {"page", "learned"} or None."""
        if self._ask is None:
            return None
        talk = "\n".join(f"{l['time']} {l['who']}: {l['text']}" for l in self._log.day(day))
        work = "\n".join(f"{o['time']} {o.get('project', '')}: {o['summary']}" for o in reports
                         if str(o.get("time", "")).startswith(day))
        if not talk and not work:
            return None
        ensure_profile(self.profile)
        system = DIARY_PROMPT.format(day=day, sections=", ".join(SECTIONS),
                                     profile=self.profile.read_text(encoding="utf-8"))
        try:
            data = json.loads(await self._ask(system, f"# Konuşmalar\n{talk[-TALK_CHARS:]}\n\n# Ekip raporları\n{work}", True))
        except Exception:  # noqa: BLE001
            logger.exception("diary for %s failed", day)
            return None
        page = str(data.get("gunluk", "")).strip()
        if not page:
            return None
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f"{day}.md").write_text(f"# {day}\n\n{page}\n", encoding="utf-8")
        for old in sorted(self.folder.glob("*.md"))[:-DIARY_KEEP]:
            old.unlink()
        learned = add_facts(self.profile, [f for f in data.get("ogrenilenler", []) if isinstance(f, dict)])
        return {"page": page, "learned": learned}

