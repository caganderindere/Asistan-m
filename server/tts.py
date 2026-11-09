"""Text-to-speech through Microsoft Edge's online neural voices."""

from __future__ import annotations

import io

import edge_tts
import soundfile as sf


async def synthesize(text: str, voice: str) -> bytes:
    """Return *text* spoken by *voice* as WAV bytes (the service sends MP3)."""
    mp3 = bytearray()
    async for chunk in edge_tts.Communicate(text, voice).stream():
        if chunk["type"] == "audio":
            mp3.extend(chunk["data"])
    samples, rate = sf.read(io.BytesIO(bytes(mp3)), dtype="float32")
    wav = io.BytesIO()
    sf.write(wav, samples, rate, format="WAV")
    return wav.getvalue()
