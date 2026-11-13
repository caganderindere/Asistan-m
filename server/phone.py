"""Ringing Çağan's phone when Cuba truly needs him: a "Cuba arıyor" push to the home-screen app.

Free: Web Push through Apple's or Google's push service, no account needed. The page subscribes
once (Hafıza pane, "Telefonda bildirimleri aç"); the subscriptions live in data/push.json and the
server's VAPID key in data/push_vapid.pem. A call rings up to RINGS times, a minute apart, until
Çağan opens it; opening it starts a live talk where Cuba says why it called.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

RINGS = 5
RING_GAP_S = 60
CALL_GAP_S = 120  # one new call per two minutes at most: a stuck team must not ring all night
CONTACT = "mailto:cuba@localhost"


def _send_push(subscription: dict, payload: str, key_file: str) -> int:
    """One push; the push service's HTTP status (404/410: the subscription is gone)."""
    from pywebpush import WebPushException, webpush

    try:
        response = webpush(subscription, payload, vapid_private_key=key_file, vapid_claims={"sub": CONTACT}, ttl=120,
                           headers={"Urgency": "high"})
        return response.status_code
    except WebPushException as e:
        return e.response.status_code if e.response is not None else 0


class Phone:
    def __init__(
        self,
        data_dir: Path,
        send: Callable[[dict, str, str], int] = _send_push,
        sleep: Callable[[float], object] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._subs_path = data_dir / "push.json"
        self._key_path = data_dir / "push_vapid.pem"
        self._send = send
        self._sleep = sleep
        self._clock = clock
        self._last = -CALL_GAP_S
        self._calls: dict[str, dict] = {}  # call id → {text, answered}
        self._tasks: set[asyncio.Task] = set()

    # ── Keys and subscriptions ──────────────────────────────────
    def public_key(self) -> str:
        """The key the page subscribes with, made on first use."""
        from cryptography.hazmat.primitives import serialization
        from py_vapid import Vapid

        if self._key_path.exists():
            vapid = Vapid.from_file(str(self._key_path))
        else:
            vapid = Vapid()
            vapid.generate_keys()
            self._key_path.parent.mkdir(parents=True, exist_ok=True)
            vapid.save_key(str(self._key_path))
        raw = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    def _subs(self) -> list[dict]:
        try:
            return json.loads(self._subs_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save(self, subs: list[dict]) -> None:
        self._subs_path.parent.mkdir(parents=True, exist_ok=True)
        self._subs_path.write_text(json.dumps(subs), encoding="utf-8")

    def subscribe(self, subscription: dict) -> int:
        """Remember one device; the number of devices that will ring."""
        if not str(subscription.get("endpoint", "")).startswith("https://") or "keys" not in subscription:
            raise ValueError("Geçersiz abonelik.")
        subs = [s for s in self._subs() if s.get("endpoint") != subscription["endpoint"]] + [subscription]
        self._save(subs)
        return len(subs)

    @property
    def devices(self) -> int:
        return len(self._subs())

    # ── Calls ───────────────────────────────────────────────────
    async def call(self, text: str) -> dict:
        """Ring Çağan with *text*; says why not when it cannot."""
        text = " ".join(text.split())[:300]
        if not self._subs():
            return {"error": "Telefonda bildirim açılmamış: telefondaki Cuba uygulamasında Hafıza sekmesinden açılmalı."}
        if self._clock() - self._last < CALL_GAP_S:
            return {"error": "Az önce arandı; iki dakika dolmadan tekrar aranmaz."}
        self._last = self._clock()
        call_id = secrets.token_hex(6)
        self._calls[call_id] = {"text": text, "answered": False}
        task = asyncio.create_task(self._ring(call_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return {"ok": True, "not": f"Telefonu çalıyor; açılana kadar dakikada bir, en çok {RINGS} kez."}

    async def _ring(self, call_id: str) -> None:
        call = self._calls[call_id]
        for ring in range(RINGS):
            if call["answered"]:
                return
            payload = json.dumps({"id": call_id, "title": "📞 Cuba arıyor", "body": call["text"], "ring": ring + 1},
                                 ensure_ascii=False)
            await self._push_all(payload)
            await self._sleep(RING_GAP_S)

    async def _push_all(self, payload: str) -> None:
        self.public_key()  # makes sure the key file exists
        kept = []
        for sub in self._subs():
            status = await asyncio.to_thread(self._send, sub, payload, str(self._key_path))
            if status in (404, 410):
                continue  # the phone dropped this subscription: forget it
            if status >= 400 or status == 0:
                logger.warning("push failed with %s", status)
            kept.append(sub)
        self._save(kept)

    def answer(self, call_id: str) -> str:
        """Çağan opened the call: stop ringing and return what Cuba wanted to say."""
        call = self._calls.get(call_id)
        if call is None:
            return ""
        call["answered"] = True
        return call["text"]

    async def idle(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
