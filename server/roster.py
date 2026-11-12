"""Who is on the team: the founding four, and whoever Cuba has hired since.

Hires are kept in data/ekip.json. Each becomes a Claude Code subagent (written into the
cuba-ekip plugin), gets a desk in the office and a voice for meetings. A fresh terminal
knows a hire at once; a running one learns of it when it is next opened.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_HIRES = 4  # the office has four empty desks
MODELS = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}


@dataclass(frozen=True)
class Member:
    id: str
    name: str
    duty: str
    model: str  # opus | sonnet | haiku
    voice: str  # Edge voice for meetings
    pitch: str = "+0Hz"
    rate: str = "+0%"
    hired: bool = False


# The meeting voices: Turkish voices, and multilingual ones that speak Turkish with their own colour.
LEAD_VOICE = Member("lider", "Cuba", "takım lideri", "opus", "tr-TR-AhmetNeural", "-14Hz", "-6%")
FOUNDERS = (
    Member("kidemli", "Kıdemli", "zor mimari ve kritik kod", "opus", "en-US-AndrewMultilingualNeural", "-4Hz"),
    Member("gelistirici", "Geliştirici", "kodu yazar", "sonnet", "en-US-BrianMultilingualNeural", "+0Hz", "+6%"),
    Member("testci", "Testçi", "test eder ve doğrular", "sonnet", "tr-TR-EmelNeural"),
    Member("asistan", "Asistan", "belge, araştırma ve küçük işler", "haiku", "en-US-AvaMultilingualNeural"),
)
HIRE_VOICES = (
    ("de-DE-FlorianMultilingualNeural", "-2Hz"), ("en-US-EmmaMultilingualNeural", "+0Hz"),
    ("it-IT-GiuseppeMultilingualNeural", "-6Hz"), ("fr-FR-VivienneMultilingualNeural", "+2Hz"),
)


def slug(name: str) -> str:
    """An id from a Turkish name: "Tasarımcı" → "tasarimci"."""
    plain = unicodedata.normalize("NFKD", name.replace("ı", "i").replace("İ", "i")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:24]


class Roster:
    def __init__(self, path: Path) -> None:
        self._path = path
        self.hires: list[Member] = self._load()

    @property
    def members(self) -> list[Member]:
        return [*FOUNDERS, *self.hires]

    def find(self, wanted: str) -> Member | None:
        key = slug(wanted)
        return next((m for m in self.members if m.id == key or slug(m.name) == key), None)

    def voice(self, member_id: str) -> Member:
        if member_id == LEAD_VOICE.id:
            return LEAD_VOICE
        return next((m for m in self.members if m.id == member_id), LEAD_VOICE)

    def hire(self, name: str, duty: str, model: str = "sonnet") -> Member:
        name, duty = " ".join(name.split()), " ".join(duty.split())
        if not name or not duty:
            raise ValueError("İşe almak için bir ad ve görev gerekli.")
        if self.find(name) is not None or slug(name) in ("lider", "cuba", "cagan", ""):
            raise ValueError(f"Ekipte zaten {name} var.")
        if len(self.hires) >= MAX_HIRES:
            raise ValueError(f"Ofiste boş masa yok: en fazla {MAX_HIRES} kişi işe alınabilir.")
        used = {m.voice for m in self.hires}
        voice, pitch = next((v for v in HIRE_VOICES if v[0] not in used), HIRE_VOICES[0])
        member = Member(slug(name), name, duty, model if model in MODELS else "sonnet", voice, pitch, hired=True)
        self.hires.append(member)
        self._save()
        return member

    def fire(self, wanted: str) -> Member:
        member = self.find(wanted)
        if member is None or not member.hired:
            raise ValueError("Yalnızca sonradan işe alınan biri çıkarılabilir.")
        self.hires = [m for m in self.hires if m.id != member.id]
        self._save()
        return member

    def _load(self) -> list[Member]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return [Member(**{**m, "hired": True}) for m in data][:MAX_HIRES]
        except (FileNotFoundError, ValueError, TypeError):
            return []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps([asdict(m) for m in self.hires], ensure_ascii=False, indent=1), encoding="utf-8")
