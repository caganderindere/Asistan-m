"""Cut streamed reply text into speakable sentences."""

from __future__ import annotations

import re

FENCE = "```"
# A sentence ends at terminal punctuation followed by whitespace (so "3.5"
# stays whole) or at a line break.
_BOUNDARY = re.compile(r"(?<=[.!?…])\s+|\n")
_INLINE_CODE = re.compile(r"`[^`]*`")
_URL = re.compile(r"https?://\S+")
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\\S*")
_UNIX_PATH = re.compile(r"(?<!\S)/(?:[\w.\-]+/)*[\w.\-]+")
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")
_MARKUP = re.compile(r"[#*_>|]+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")
_LETTER = re.compile(r"[^\W\d_]")


def speakable(sentence: str) -> str:
    """Drop what should be read, not heard: code, paths, URLs and markdown marks."""
    text = _INLINE_CODE.sub(" ", sentence)
    text = _URL.sub(" ", text)
    text = _WINDOWS_PATH.sub(" ", text)
    text = _UNIX_PATH.sub(" ", text)
    text = _BULLET.sub("", text)
    text = _MARKUP.sub("", text)
    text = " ".join(text.split())
    return _SPACE_BEFORE_PUNCT.sub(r"\1", text)


class SentenceSplitter:
    def __init__(self) -> None:
        self._buf = ""
        self._in_code = False

    def feed(self, text: str) -> list[str]:
        self._buf += text
        out: list[str] = []
        while True:
            if self._in_code:
                end = self._buf.find(FENCE)
                if end < 0:
                    # Keep a possible half-received closing fence.
                    self._buf = self._buf[-(len(FENCE) - 1):]
                    return out
                self._buf = self._buf[end + len(FENCE):]
                self._in_code = False
                continue
            fence = self._buf.find(FENCE)
            boundary = _BOUNDARY.search(self._buf)
            if fence >= 0 and (boundary is None or fence < boundary.start()):
                out += self._emit(self._buf[:fence])
                self._buf = self._buf[fence + len(FENCE):]
                self._in_code = True
                continue
            if boundary is None:
                return out
            out += self._emit(self._buf[:boundary.start()])
            self._buf = self._buf[boundary.end():]

    def flush(self) -> list[str]:
        out = [] if self._in_code else self._emit(self._buf)
        self._buf = ""
        self._in_code = False
        return out

    @staticmethod
    def _emit(chunk: str) -> list[str]:
        text = speakable(chunk.strip())
        return [text] if _LETTER.search(text) else []
