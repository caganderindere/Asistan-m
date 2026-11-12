"""Application settings, read from config.json with built-in defaults."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_VOCABULARY: tuple[str, ...] = (
    "Çağan",
    "Cuba",
    "Claude",
    "WordPress",
    "Nevka Kağıt",
    "Telsiz Mağaza",
    "BalBal Medya",
)


# Which model each team member runs on: hard work on the strong model,
# routine work on the cheap one.
DEFAULT_MODELS: dict[str, str] = {
    "lider": "claude-opus-5-5",
    "kidemli": "claude-opus-5-5",
    "gelistirici": "claude-sonnet-5-5",
    "testci": "claude-sonnet-5-5",
    "asistan": "claude-haiku-5-5",
}


@dataclass(frozen=True)
class Config:
    port: int = 8765
    workdir: str = "D:\\"
    # Cuba: the male voice, a touch deeper than it comes.
    voice: str = "tr-TR-AhmetNeural"
    voice_rate: str = "+0%"
    voice_pitch: str = "-6Hz"
    whisper_model: str = "large-v3-turbo"
    vocabulary: tuple[str, ...] = DEFAULT_VOCABULARY
    models: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MODELS))
    # "gemini": Cuba talks on Gemini and only coding work spends Claude tokens.
    # "claude": Cuba runs on models["lider"] like the rest of the team.
    lead_backend: str = "gemini"
    # Cuba's voice: "live" talks over Gemini Live (speech to speech, about half a second);
    # "classic" goes through Whisper, a text model and Edge TTS.
    voice_engine: str = "live"
    live_model: str = "gemini-3.1-flash-live-preview"
    live_voice: str = "Charon"
    # The model the embedded terminal's Claude Code starts on.
    terminal_model: str = "claude-opus-5-5"
    gemini_model: str = "gemini-3.5-flash-lite"
    # Gemini 2.5 takes 0 to turn thinking off; 3.x models reject the setting, so None sends nothing.
    gemini_thinking_budget: int | None = None


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
