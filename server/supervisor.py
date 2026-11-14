"""Cuba as the boss of the terminal's Claude: brief reports, and decisions while you are away.

Claude Code works in the terminal; each time it stops, its answer comes here.
With the user present, Cuba turns it into a sentence or two to say aloud.
With the user away, Cuba decides in their place: the work is done, or Claude
gets told what to do next, up to a fixed number of rounds.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from server.projects import project_name
from server.terminal import spoken

logger = logging.getLogger(__name__)

MAX_AWAY_TURNS = 40
KEPT_OUTPUTS = 100
# Only the end of a long answer is sent to Gemini: the conclusion is there.
REPORT_CHARS = 6000

SUMMARY_PROMPT = """Aşağıdaki metni Cuba (sen) az önce Çağan'a yazdın; ekranda duruyor. Şimdi aynısını
sesli söyleyeceksin, ama kısaca: bir iki konuşma cümlesi, birinci tekil şahısla, Cuba'nın ağzından.
Kurallar:
- Yalnızca metinde gerçekten yazanı söyle. Metinde olmayan hiçbir şeyi ekleme: test, hata, onay,
  soru ya da rapor metinde yoksa bunlardan söz etme.
- Metin bir iş raporuysa: ne yapıldığını ve metinde geçiyorsa hata ya da başarısız testi söyle;
  metin Çağan'a soru soruyorsa soruyu sor; ayrıntı varsa sonuna "Ayrıntılar terminalde." ekle.
- Metin rapor değilse (kısa bir cevap, yapılan küçük bir iş) onu kısaca olduğu gibi söyle.
- Çağan'a "patron" de; "efendim" ya da "boss" deme. Kendinden emin bir müdür gibi konuş; gerekiyorsa
  bir cümleyle kendi görüşünü ekle. Madde işareti, kod ve dosya yolu okuma.
Yalnızca söyleyeceğin metni yaz."""
# Answers this short are Cuba's own words, read as written: nothing to summarize.
BRIEF_CHARS = 350
BRIEF_LINES = 4
# A report naming a document it wrote is worth keeping, however short.
DOC_PATH = re.compile(r"[\w./\-]+\.(?:md|pdf|html|csv|docx|json)\b", re.I)
LIVE_HEAD = 1200  # a report's opening Cuba always hears: the summary and the document's path
LIVE_CHARS = 4000

AWAY_PROMPT = """Sen Cuba'sın: Çağan'ın takım liderisin. Çağan şu an yok (uyuyor ya da dışarıda) ve tüm
yetkiyi sana verdi; hiçbir şeyi ona sorma, onun yerine sen karar ver. Geliştirici ekip (Claude Code)
az önce durdu ve aşağıdaki raporu verdi.

Çağan'ın verdiği iş: {goal}

Karar ver:
- İş tamamen bittiyse "bitti": true.
- Bitmediyse, ekip soru soruyor, seçenek sunuyor ya da onay bekliyorsa: Çağan'ın yerine en mantıklı
  kararı ver ve ekibe ne yapacağını tek paragraf, net bir talimatla "talimat" alanına yaz; "bitti": false.
  Ekip takıldıysa farklı bir yol dene dedirt. Gereksiz iş açma; hedefe odaklan.
- Her durumda "ozet" alanına Çağan döndüğünde okuyacağı bir iki cümlelik Türkçe özet yaz.

Yalnızca şu JSON'u döndür: {{"bitti": true/false, "talimat": "...", "ozet": "..."}}"""

DIGEST_PROMPT = """Sen Cuba'sın: Çağan'ın takım liderisin. Çağan yokken ekibi sen yönettin; aşağıda o sürede
olanların kısa notları var. Çağan döndü: ona "hoş geldin patron" diye başlayıp olanları üç dört
cümleyle sesli anlat. Ne bitti, hangi kararları sen verdin, yarım kalan ya da dikkat etmesi gereken
ne var. Madde işareti kullanma. Yalnızca söyleyeceğin metni yaz."""

Ask = Callable[[str, str, bool], Awaitable[str]]


def is_brief(text: str) -> bool:
    """A plain short answer rather than a work report: no code, a few lines at most."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if DOC_PATH.search(text):
        return False
    return "```" not in text and len(lines) <= BRIEF_LINES and len(text.strip()) <= BRIEF_CHARS


def for_live(report: str) -> str:
    """A report cut to what Cuba is told: its opening and its end, never just the end."""
    if len(report) <= LIVE_CHARS:
        return report
    return f"{report[:LIVE_HEAD]}\n…\n{report[-(LIVE_CHARS - LIVE_HEAD):]}"


DOC_LINE = re.compile(r"^\W*Belge:\s*`?([^`\n]+?)`?\s*$", re.M)


def check_documents(report: str, folder: str | Path) -> list[dict]:
    """The documents a report names on its `Belge:` lines, and whether each is really on disk."""
    found = []
    for wanted in DOC_LINE.findall(report):
        path = Path(wanted.strip())
        full = path if path.is_absolute() else Path(folder) / path
        found.append({"name": wanted.strip(), "path": str(full), "ok": full.is_file(),
                      "kb": round(full.stat().st_size / 1024, 1) if full.is_file() else 0})
    return found


def documents_note(docs: list[dict]) -> str:
    """What Cuba is told about the named documents: checked by the server, not taken on trust."""
    lines = [f"{d['name']}: var ({d['kb']} KB)" if d["ok"] else
             f"{d['name']}: YOK, raporda adı geçiyor ama dosya bulunamadı; Çağan'a belge oluştu deme"
             for d in docs]
    return "\n[BELGE KONTROLÜ] " + "; ".join(lines) if lines else ""


class Supervisor:
    def __init__(
        self,
        ask: Ask | None,
        outputs_path: Path,
        max_turns: int = MAX_AWAY_TURNS,
        clock: Callable[[], datetime.datetime] = datetime.datetime.now,
    ) -> None:
        self._ask = ask
        self._path = outputs_path
        self._clock = clock
        self.max_turns = max_turns
        self.away = False
        self.turns = 0
        self._away_from = 0  # where the outputs written while away begin
        self.goals: dict[str, str] = {}  # each project terminal's goal, by its folder
        self.outputs: list[dict] = self._load()

    def state(self) -> dict:
        return {"type": "away", "on": self.away, "turns": self.turns, "max": self.max_turns}

    def set_away(self, on: bool) -> None:
        if on and not self.away:
            self._away_from = len(self.outputs)
        self.away = on
        self.turns = 0

    async def welcome_back(self) -> str:
        """What happened while the user was away, to say when they return; empty if nothing did."""
        notes = [o for o in self.outputs[self._away_from:] if o.get("away")]
        self._away_from = len(self.outputs)
        if not notes:
            return ""
        lines = "\n".join(f"{o['time']} {o.get('project', '')}: {o['summary']}" for o in notes)
        if self._ask is not None:
            try:
                text = (await self._ask(DIGEST_PROMPT, lines, False)).strip()
                if text:
                    return text
            except Exception:  # noqa: BLE001
                logger.exception("digest failed")
        return "Hoş geldin patron. " + " ".join(o["summary"] for o in notes)

    @property
    def goal(self) -> str:
        """The latest goal given to any terminal."""
        return next(reversed(self.goals.values()), "")

    def note_prompt(self, text: str, folder: str = "") -> None:
        """Whatever the user asks Claude for is the goal Cuba holds it to."""
        if text.strip():
            self.goals.pop(folder, None)
            self.goals[folder] = text.strip()
            self.turns = 0

    async def on_stop(self, report: str, folder: str = "") -> dict:
        """What to do with Claude's answer: {"speak": text} or {"continue_with": instruction}."""
        if not self.away:
            if is_brief(report):
                return {"speak": spoken(report)}
            summary = await self._summary(report)
            self._record(summary, report, away=False, folder=folder)
            return {"speak": summary}
        if self.turns >= self.max_turns:
            self._record(f"{self.max_turns} turluk sınıra ulaşıldı, iş yarıda bırakıldı.", report, away=True, folder=folder)
            return {}
        decision = await self._decide(report, self.goals.get(folder, ""))
        if decision is None:
            self._record("Karar verilemedi (Gemini'ye ulaşılamadı); ekip bekliyor.", report, away=True, folder=folder)
            return {}
        self._record(decision["ozet"], report, away=True, done=decision["bitti"], folder=folder)
        if decision["bitti"] or not decision["talimat"]:
            return {}
        self.turns += 1
        return {"continue_with": decision["talimat"]}

    def note_report(self, report: str, folder: str = "") -> None:
        """Keep a report Cuba relays live; the outputs list shows its opening."""
        if not is_brief(report):
            self._record(spoken(report), report, away=False, folder=folder)

    def note_meeting(self, summary: str, transcript: str, folder: str = "") -> None:
        """Keep what a team meeting decided, with all that was said."""
        self._record(f"Toplantı: {summary}", transcript, away=self.away, folder=folder, kind="meeting")

    async def _summary(self, report: str) -> str:
        if self._ask is not None and report.strip():
            try:
                text = (await self._ask(SUMMARY_PROMPT, report[-REPORT_CHARS:], False)).strip()
                if text:
                    return text
            except Exception:  # noqa: BLE001 - any failure falls back to reading the start
                logger.exception("summary failed")
        return spoken(report)

    async def _decide(self, report: str, goal: str = "") -> dict | None:
        if self._ask is None:
            return None
        try:
            raw = await self._ask(AWAY_PROMPT.format(goal=goal or self.goal or "(belirtilmedi)"), report[-REPORT_CHARS:], True)
            data = json.loads(raw)
            return {
                "bitti": bool(data.get("bitti")),
                "talimat": str(data.get("talimat") or "").strip(),
                "ozet": str(data.get("ozet") or "").strip() or spoken(report),
            }
        except Exception:  # noqa: BLE001
            logger.exception("away decision failed")
            return None

    def _record(
        self, summary: str, report: str, away: bool, done: bool = False, folder: str = "", kind: str = "report"
    ) -> None:
        self.outputs.append({
            "time": self._clock().strftime("%Y-%m-%d %H:%M"),
            "project": project_name(folder) if folder else "",
            "kind": kind,
            "goal": self.goals.get(folder, self.goal),
            "summary": summary,
            "report": report,
            "away": away,
            "done": done,
        })
        dropped = max(0, len(self.outputs) - KEPT_OUTPUTS)
        del self.outputs[:dropped]
        self._away_from = max(0, self._away_from - dropped)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self.outputs, ensure_ascii=False), encoding="utf-8")

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return []
        return data if isinstance(data, list) else []
