"""Cuba's searchable memory: everything said, learned and written, found by meaning rather than by word.

Talks (data/konusmalar), topic files (asistan/bilgi), diary pages (asistan/gunluk) and the documents on
the desktop (belgeler/**.md) are cut into pieces and embedded with Gemini. The vectors are kept in
data/anlam.json keyed by a hash of each piece, so only new or changed pieces are ever embedded again.
Indexing runs in the background and is saved batch by batch; a search uses whatever is indexed so far.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Iterator
from pathlib import Path

import httpx
import numpy as np

logger = logging.getLogger(__name__)

EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
EMBED_MODEL = "gemini-embedding-001"
DIMENSIONS = 768
BATCH = 20  # the free tier counts every piece as a request: small batches, paced
RATE_WAIT = 30  # seconds to wait when Gemini says too many requests
RETRIES = 4
TALK_LINES = 12  # lines of talk per piece
PIECE_CHARS = 1500
DOC_PIECES = 20  # pieces kept from one document
MIN_SCORE = 0.55
SHOWN_CHARS = 700


def _split(text: str) -> list[str]:
    """Pieces of about PIECE_CHARS, cut at paragraph breaks where possible."""
    pieces, current = [], ""
    for para in text.split("\n\n"):
        if current and len(current) + len(para) > PIECE_CHARS:
            pieces.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
        while len(current) > PIECE_CHARS * 1.5:
            pieces.append(current[:PIECE_CHARS])
            current = current[PIECE_CHARS:]
    if current.strip():
        pieces.append(current)
    return pieces


def pieces(data_dir: Path, memory_dir: Path, docs_root: Path) -> Iterator[dict]:
    """Every piece Cuba can remember, with where and when it comes from."""
    for day in sorted((data_dir / "konusmalar").glob("*.jsonl")):
        lines = []
        for raw in day.read_text(encoding="utf-8").splitlines():
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            lines.append(f"{str(line.get('time', ''))[-8:-3]} {line.get('who', '')}: {line.get('text', '')}")
        for i in range(0, len(lines), TALK_LINES):
            yield {"kaynak": f"konuşma {day.stem}", "tarih": day.stem, "metin": "\n".join(lines[i:i + TALK_LINES])}
    for folder, label in ((memory_dir / "bilgi", "bilgi"), (memory_dir / "gunluk", "günlük")):
        for page in sorted(folder.glob("*.md")):
            for text in _split(page.read_text(encoding="utf-8", errors="replace")):
                yield {"kaynak": f"{label}: {page.stem}", "tarih": "", "metin": text}
    for doc in sorted(docs_root.rglob("*.md")) if docs_root.is_dir() else []:
        for text in _split(doc.read_text(encoding="utf-8", errors="replace"))[:DOC_PIECES]:
            yield {"kaynak": f"belge: {doc}", "tarih": "", "metin": text}


def _key(piece: dict) -> str:
    return hashlib.sha1(f"{piece['kaynak']}\n{piece['metin']}".encode()).hexdigest()


class SemanticMemory:
    def __init__(self, api_key: str, data_dir: Path, memory_dir: Path, docs_root: Path,
                 client: httpx.AsyncClient | None = None) -> None:
        self._key = api_key
        self._data_dir = data_dir
        self._memory_dir = memory_dir
        self._docs_root = docs_root
        self._path = data_dir / "anlam.json"
        self._client = client
        self._lock = asyncio.Lock()
        self._index: dict[str, dict] | None = None
        self._indexing: asyncio.Task | None = None
        self._sleep = asyncio.sleep

    async def _embed(self, texts: list[str], task: str) -> list[list[float]]:
        for attempt in range(RETRIES):
            try:
                return await self._embed_once(texts, task)
            except httpx.HTTPStatusError as error:
                if error.response.status_code != 429 or attempt == RETRIES - 1:
                    raise
                await self._sleep(RATE_WAIT)
        return []

    async def _embed_once(self, texts: list[str], task: str) -> list[list[float]]:
        body = {"requests": [{"model": f"models/{EMBED_MODEL}", "content": {"parts": [{"text": t}]},
                              "taskType": task, "outputDimensionality": DIMENSIONS} for t in texts]}
        client = self._client or httpx.AsyncClient(timeout=httpx.Timeout(60, connect=8))
        try:
            response = await client.post(EMBED_URL.format(model=EMBED_MODEL), json=body,
                                         headers={"x-goog-api-key": self._key})
            response.raise_for_status()
            return [e["values"] for e in response.json()["embeddings"]]
        finally:
            if self._client is None:
                await client.aclose()

    def _load(self) -> dict[str, dict]:
        if self._index is None:
            try:
                self._index = json.loads(self._path.read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError):
                self._index = {}
        return self._index

    async def refresh(self) -> int:
        """Embed what is new, forget what is gone; returns how many pieces were embedded."""
        async with self._lock:
            index = self._load()
            current = {_key(p): p for p in pieces(self._data_dir, self._memory_dir, self._docs_root)}
            missing = [k for k in current if k not in index]
            for i in range(0, len(missing), BATCH):
                keys = missing[i:i + BATCH]
                vectors = await self._embed([current[k]["metin"] for k in keys], "RETRIEVAL_DOCUMENT")
                for k, v in zip(keys, vectors):
                    index[k] = {**current[k], "v": [round(x, 5) for x in v]}
                self._save()
            gone = [k for k in index if k not in current]
            for k in gone:
                del index[k]
            if gone:
                self._save()
            return len(missing)

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._index, ensure_ascii=False), encoding="utf-8")

    def start_indexing(self) -> None:
        """Bring the index up to date in the background, unless that is already happening."""
        if self._indexing is None or self._indexing.done():
            self._indexing = asyncio.create_task(self._index_quietly())

    async def _index_quietly(self) -> None:
        try:
            await self.refresh()
        except Exception:  # noqa: BLE001 - the next search tries again
            logger.exception("semantic indexing failed")

    async def search(self, question: str, limit: int = 5) -> dict:
        """The pieces closest in meaning to *question*, best first."""
        self.start_indexing()
        try:
            index = self._load()
            if not index:
                return {"bulunamadi": True, "not": "Hafıza ilk kez hazırlanıyor, bir iki dakika sonra tekrar sor."}
            [query] = await self._embed([question], "RETRIEVAL_QUERY")
        except (httpx.HTTPError, KeyError, ValueError) as error:
            logger.exception("semantic search failed")
            return {"error": f"Hafızada arama yapılamadı ({type(error).__name__})."}
        keys = list(index)
        matrix = np.array([index[k]["v"] for k in keys], dtype=np.float32)
        matrix /= np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
        q = np.array(query, dtype=np.float32)
        scores = matrix @ (q / (np.linalg.norm(q) + 1e-9))
        best = [i for i in np.argsort(-scores)[:limit] if scores[i] >= MIN_SCORE]
        if not best:
            return {"bulunamadi": True, "not": "Bununla ilgili bir şey hatırlamıyorum."}
        return {"hatirladiklarim": [
            {"kaynak": index[keys[i]]["kaynak"], "tarih": index[keys[i]]["tarih"],
             "metin": index[keys[i]]["metin"][:SHOWN_CHARS], "benzerlik": round(float(scores[i]), 2)}
            for i in best]}
