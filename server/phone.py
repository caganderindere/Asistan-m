"""Ringing Çağan's phone when Cuba truly needs him: a Telegram voice call through CallMeBot.

Free and keyless: Çağan once sends /start to @CallMeBot_txtbot, then data/arama.json names him:
    {"telegram": "@kullanici_adi"}
The call reads the message aloud and a written copy lands in Telegram too (on an iPhone the call
rings but its audio may stay silent, a Telegram bug, so the copy is what he reads).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

URL = "https://api.callmebot.com/start.php"
VOICE = "tr-TR-Standard-A"
TEXT_LIMIT = 256
GAP_S = 120  # one call per two minutes at most: a stuck team must not ring all night


class Phone:
    def __init__(self, path: Path, transport: httpx.AsyncBaseTransport | None = None, clock=time.monotonic) -> None:
        self._path = path
        self._transport = transport
        self._clock = clock
        self._last = -GAP_S

    @property
    def user(self) -> str:
        try:
            return str(json.loads(self._path.read_text(encoding="utf-8")).get("telegram", "")).strip()
        except (OSError, ValueError, AttributeError):
            return ""

    async def call(self, text: str) -> dict:
        """Ring Çağan with *text*; says why not when it cannot."""
        user = self.user
        if not user:
            return {"error": f"Arama kurulmamış: {self._path.name} içinde telegram kullanıcı adı yok."}
        if self._clock() - self._last < GAP_S:
            return {"error": "Az önce arandı; iki dakika dolmadan tekrar aranmaz."}
        self._last = self._clock()
        params = {"user": user, "text": " ".join(text.split())[:TEXT_LIMIT], "lang": VOICE, "rpt": "2", "cc": "yes"}
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=60) as client:
                response = await client.get(URL, params=params)
        except httpx.HTTPError as e:
            logger.warning("phone call failed: %s", e)
            return {"error": "Arama servisine ulaşılamadı."}
        if response.status_code >= 400 or "error" in response.text.lower()[:300]:
            return {"error": f"Arama başarısız: {response.text[:200]}"}
        return {"ok": True, "not": "Telefonu çalıyor; yazılı kopyası Telegram'a da gitti."}
