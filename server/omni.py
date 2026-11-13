"""The office's free models: one OpenAI-compatible endpoint, OmniRoute, running on this machine.

OmniRoute routes each request through the `ofis` combo to whichever free provider still has quota,
so the office never needs to know which model answered.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from server.config import ROOT

BASE_URL = "http://127.0.0.1:20128/v1"
MODEL = "ofis"
KEY_FILE = ROOT / "data" / "omniroute_key.txt"


class OmniError(Exception):
    """The model could not be reached or refused; the message says why, in Turkish."""


class OmniLimit(OmniError):
    """Every free provider in the combo is out of quota for now."""


def load_key(path: Path = KEY_FILE) -> str:
    if key := os.environ.get("OMNIROUTE_API_KEY", "").strip():
        return key
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


class OmniClient:
    def __init__(
        self,
        key: str,
        base_url: str = BASE_URL,
        model: str = MODEL,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 60,
    ) -> None:
        self._key = key
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self.model = model
        self._transport = transport
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self._key)

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """The model's message: its `content` and, when it wants a tool, `tool_calls`."""
        if not self._key:
            raise OmniError("OmniRoute anahtarı yok (data/omniroute_key.txt).")
        body: dict = {"model": self.model, "stream": False, "messages": messages}
        if tools:
            body["tools"] = tools
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
                response = await client.post(self._url, json=body, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.TimeoutException as e:
            raise OmniError("Model zamanında cevap vermedi.") from e
        except httpx.HTTPError as e:
            raise OmniError("OmniRoute'a ulaşılamadı; çalışıyor mu?") from e
        if response.status_code == 429:
            raise OmniLimit("Ücretsiz modellerin limiti doldu; biraz sonra tekrar denenmeli.")
        if response.status_code in (401, 403):
            raise OmniError("OmniRoute anahtarı geçersiz.")
        try:
            data = response.json()
        except ValueError as e:
            raise OmniError(f"OmniRoute anlaşılmayan bir cevap verdi (HTTP {response.status_code}).") from e
        if response.status_code >= 400 or "choices" not in data:
            error = data.get("error") if isinstance(data.get("error"), dict) else data
            raise OmniError(f"Model hatası: {str(error.get('message') or data)[:200]}")
        return data["choices"][0]["message"]
