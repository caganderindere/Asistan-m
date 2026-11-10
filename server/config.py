"""Application settings, read from config.json with built-in defaults."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_VOCABULARY: tuple[str, ...] = (
    "Çağan",
    "Jarvis",
    "Claude",
    "WordPress",
    "Nevka Kağıt",
    "Telsiz Mağaza",
    "BalBal Medya",
)


# Which model each team member runs on: hard work on the strong model,
# routine work on the cheap one.
DEFAULT_MODELS: dict[str, str] = {
    "lider": "claude-fable-5-2",
    "kidemli": "claude-fable-5-2",
    "gelistirici": "claude-sonnet-5-5",
    "testci": "claude-sonnet-5-5",
    "asistan": "claude-haiku-5-5",
}


@dataclass(frozen=True)
class Config:
    port: int = 8765
    workdir: str = "D:\\"
    # Jarvis: the male voice, a touch deeper than it comes.
    voice: str = "tr-TR-AhmetNeural"
    voice_rate: str = "+0%"
    voice_pitch: str = "-6Hz"
    whisper_model: str = "large-v3-turbo"
    vocabulary: tuple[str, ...] = DEFAULT_VOCABULARY
    models: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MODELS))


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
    if "models" in values:
        values["models"] = {**DEFAULT_MODELS, **values["models"]}
    return Config(**values)
