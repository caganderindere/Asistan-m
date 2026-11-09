import asyncio
from pathlib import Path

import pytest

from server import tts
from server.config import DEFAULT_VOCABULARY

MP3 = (Path(__file__).parent / "fixtures" / "merhaba.mp3").read_bytes()


class FakeCommunicate:
    def __init__(self, text, voice):
        self.args = (text, voice)

    async def stream(self):
        yield {"type": "WordBoundary"}
        for i in range(0, len(MP3), 4096):
            yield {"type": "audio", "data": MP3[i:i + 4096]}


async def test_synthesize_returns_wav(monkeypatch):
    monkeypatch.setattr(tts.edge_tts, "Communicate", FakeCommunicate)
    wav = await tts.synthesize("Merhaba", "tr-TR-EmelNeural")
    assert wav[:4] == b"RIFF" and len(wav) > 1000


@pytest.mark.network
async def test_real_edge_voice():
    wav = await tts.synthesize("Merhaba, ben asistanın.", "tr-TR-EmelNeural")
    assert wav[:4] == b"RIFF"


@pytest.mark.gpu
async def test_turbo_understands_turkish_on_gpu():
    from server.stt import Transcriber

    transcriber = Transcriber("large-v3-turbo", DEFAULT_VOCABULARY)
    wav = await tts.synthesize("Yarın saat üçte Nevka Kağıt ile toplantım var.", "tr-TR-EmelNeural")
    text = (await asyncio.to_thread(transcriber.transcribe, wav)).lower()
    print("device:", transcriber.device, "text:", text)
    assert "nevka kağıt" in text and "toplantı" in text
    if transcriber.device != "cuda":
        pytest.xfail(f"CUDA unavailable, ran on {transcriber.device}")
