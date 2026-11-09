"""Application settings, read from config.json with built-in defaults."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_VOCABULARY: tuple[str, ...] = (
    "Çağan",
    "Claude",
    "WordPress",
    "Nevka Kağıt",
    "Telsiz Mağaza",
    "BalBal Medya",
)


@dataclass(frozen=True)
class Config:
    port: int = 8765
    workdir: str = "D:\\"
    voice: str = "tr-TR-EmelNeural"
    whisper_model: str = "large-v3-turbo"
    vocabulary: tuple[str, ...] = DEFAULT_VOCABULARY


def load_config(path: Path) -> Config:
    """Return the settings in *path*, falling back to defaults for anything missing."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Config()
    known = {f.name for f in fields(Config)}
    values = {k: v for k, v in raw.items() if k in known}
    if "vocabulary" in values:
        values["vocabulary"] = tuple(values["vocabulary"])
    return Config(**values)
