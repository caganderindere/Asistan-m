"""Turkish speech-to-text with faster-whisper, on the GPU when it can be used."""

from __future__ import annotations

import io
import logging
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from server.config import ROOT

logger = logging.getLogger(__name__)

MODELS_DIR = ROOT / "models"
MIN_CHARS = 2
# Whisper invents these from silence and noise; they come from subtitled
# training data, never from the speaker.
_HALLUCINATIONS = (
    "altyazı m.k.",
    "izlediğiniz için teşekkürler",
    "abone olmayı unutmayın",
)


def _normalize(text: str) -> str:
    text = text.replace("İ", "i").replace("I", "ı").lower()
    return " ".join(re.sub(r"[^\w\s]", "", text).split())


_HALLUCINATION_KEYS = {_normalize(h) for h in _HALLUCINATIONS}


def is_meaningful(text: str) -> bool:
    stripped = text.strip()
    return len(stripped) >= MIN_CHARS and _normalize(stripped) not in _HALLUCINATION_KEYS


def load_cuda_dlls() -> None:
    """Expose the pip-installed CUDA 12 runtime (nvidia-*-cu12) to CTranslate2."""
    nvidia = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for bin_dir in sorted(nvidia.glob("*/bin")):
        os.add_dll_directory(str(bin_dir))
        # CTranslate2 loads cuBLAS/cuDNN by name, which searches PATH.
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


class Transcriber:
    def __init__(self, model: str, vocabulary: Sequence[str]) -> None:
        from faster_whisper import WhisperModel

        self._prompt = ", ".join(vocabulary) or None
        load_cuda_dlls()
        try:
            self._model = WhisperModel(
                model, device="cuda", compute_type="int8_float16", download_root=str(MODELS_DIR)
            )
            # A missing CUDA library only surfaces on the first real inference.
            self._probe()
            self.device = "cuda"
        except Exception as exc:  # noqa: BLE001 - any GPU failure means CPU
            logger.warning("GPU unavailable for Whisper, using CPU: %s", exc)
            self._model = WhisperModel(model, device="cpu", compute_type="int8", download_root=str(MODELS_DIR))
            self.device = "cpu"

    def _probe(self) -> None:
        import numpy as np

        segments, _ = self._model.transcribe(np.zeros(16000, dtype=np.float32), language="tr")
        list(segments)

    def transcribe(self, audio: bytes) -> str:
        segments, _ = self._model.transcribe(
            io.BytesIO(audio), language="tr", vad_filter=True, initial_prompt=self._prompt
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


# Scripts Çağan does not speak: when the Live transcript is mostly these, it heard the room, not him.
_FOREIGN = re.compile(r"[Ͱ-ϿЀ-ӿ֐-ۿ฀-๿぀-ヿ㐀-鿿가-힯]")


def is_noise(text: str) -> bool:
    """True for a heard line that is mostly a foreign script (Korean, Japanese, Chinese, Arabic…)."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(bool(_FOREIGN.match(c)) for c in letters) > len(letters) / 2
