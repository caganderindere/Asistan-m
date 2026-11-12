"""Cuba on Telegram: write or send a voice note from anywhere; reports and approvals come to the phone.

The bot answers one person only. Until it knows who, it shows a pairing code (in the server
window and the browser); sending "/esle <kod>" from Telegram makes that account Çağan's. Messages
go to Gemini with the same tools Cuba has on the voice line, and voice notes are sent to Gemini
as audio, so nothing needs transcribing here. Settings live in data/telegram.json:
{"token": "<BotFather token>", "chat_id": <filled in by pairing>}.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx

from server.chat import CubaChat
from server.live import CubaTools

logger = logging.getLogger(__name__)

BOT = "https://api.telegram.org/bot{token}/{method}"
FILE = "https://api.telegram.org/file/bot{token}/{path}"
MESSAGE_CHARS = 3900  # Telegram's limit is 4096
ADAPTER = """
# Şu an Telegram'dasın
Çağan sana Telegram'dan yazıyor ya da sesli mesaj atıyor; muhtemelen bilgisayarın başında değil.
Cevabın yazılı gidecek: kısa yaz, Markdown başlığı ya da tablo kullanma. Ses kaydında söyleneni anla ve
ona göre davran. Komutlar: /durum (projelerde ne oluyor), /uzak (uzak modu aç-kapa), /dur (terminali durdur).
"""

Status = Callable[[], str]
Toggle = Callable[[], Awaitable[str]]


class TelegramBot:
    def __init__(
        self,
        settings_path: Path,
        gemini_key: str,
        model: str,
        tools: CubaTools,
        status: Status,
        toggle_away: Toggle,
        stop: Callable[[], None],
        heard: Callable[[str, str, str], None] | None = None,
        diary: Callable[[], str] = str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._path = settings_path
        self._settings = self._load()
        self._status = status
        self._toggle_away = toggle_away
        self._stop = stop
        self._heard = heard
        self._client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(70, connect=10))
        self._chat = CubaChat(gemini_key, model, tools, diary, ADAPTER, self._client)
        self._pending: dict[str, Callable[[str], None]] = {}  # approval id → what a button press does
        self.pair_code = "" if self.paired else f"{secrets.randbelow(900000) + 100000}"

    @property
    def configured(self) -> bool:
        return bool(self._settings.get("token"))

    @property
    def paired(self) -> bool:
        return bool(self._settings.get("chat_id"))

    # ── Talking to Telegram ─────────────────────────────────────

    async def _call(self, method: str, **params) -> dict:
        response = await self._client.post(BOT.format(token=self._settings["token"], method=method), json=params)
        data = response.json()
        if not data.get("ok"):
            raise httpx.HTTPError(f"telegram {method}: {data.get('description')}")
        return data.get("result")

    async def send(self, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
        """Message Çağan; quietly does nothing until the bot is set up and paired."""
        if not (self.configured and self.paired):
            return
        params: dict = {"chat_id": self._settings["chat_id"], "text": text[:MESSAGE_CHARS]}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in buttons]]}
        try:
            await self._call("sendMessage", **params)
        except (httpx.HTTPError, ValueError):
            logger.exception("telegram message failed")

    async def ask_approval(self, text: str, answer: Callable[[str], None]) -> None:
        """Ask Çağan yes or no; *answer* gets "evet" or "hayir" when a button is pressed."""
        key = secrets.token_hex(4)
        self._pending = {key: answer}  # only the latest question can be answered
        await self.send(text, [("✅ Evet", f"{key}:evet"), ("⛔ Hayır", f"{key}:hayir")])

    async def run(self) -> None:
        """Long-poll for messages until cancelled."""
        if not self.configured:
            return
        if not self.paired:
            logger.warning("Telegram eşleme kodu: %s  (bota '/esle %s' yazın)", self.pair_code, self.pair_code)
        offset = 0
        while True:
            try:
                updates = await self._call("getUpdates", offset=offset, timeout=50,
                                           allowed_updates=["message", "callback_query"])
            except (httpx.HTTPError, ValueError):
                await asyncio.sleep(5)
                continue
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    await self.handle(update)
                except Exception:  # noqa: BLE001 - one bad message must not stop the bot
                    logger.exception("telegram update failed")

    async def close(self) -> None:
        await self._client.aclose()

    # ── One update ──────────────────────────────────────────────

    async def handle(self, update: dict) -> None:
        if query := update.get("callback_query"):
            await self._button(query)
            return
        message = update.get("message") or {}
        chat = (message.get("chat") or {}).get("id")
        text = (message.get("text") or "").strip()
        if not self.paired:
            if text.split()[:2] == ["/esle", self.pair_code] and self.pair_code:
                self._settings["chat_id"] = chat
                self._save()
                self.pair_code = ""
                await self.send("Eşleşme tamam patron. Artık buradan da benimleyiz.")
            return
        if chat != self._settings["chat_id"]:
            return  # a stranger: no answer at all
        if text == "/durum":
            await self.send(self._status())
        elif text == "/uzak":
            await self.send(await self._toggle_away())
        elif text == "/dur":
            self._stop()
            await self.send("Terminali durdurdum patron.")
        elif text.startswith("/start"):
            await self.send("Buradayım patron. Yaz ya da sesli mesaj at.")
        elif voice := message.get("voice") or message.get("audio"):
            audio = await self._download(voice["file_id"])
            mime = voice.get("mime_type") or "audio/ogg"
            await self._converse([{"inlineData": {"mimeType": mime, "data": base64.b64encode(audio).decode()}}],
                                 "(sesli mesaj)")
        elif text:
            await self._converse([{"text": text}], text)

    async def _button(self, query: dict) -> None:
        if (query.get("from") or {}).get("id") != self._settings.get("chat_id"):
            return
        key, _, choice = str(query.get("data", "")).partition(":")
        answer = self._pending.pop(key, None)
        with_text = "Onaylandı" if choice == "evet" else "Reddedildi"
        if answer is None:
            with_text = "Bu soru artık geçerli değil."
        else:
            answer(choice)
        try:
            await self._call("answerCallbackQuery", callback_query_id=query["id"], text=with_text)
        except (httpx.HTTPError, ValueError, KeyError):
            logger.exception("telegram button answer failed")

    async def _download(self, file_id: str) -> bytes:
        info = await self._call("getFile", file_id=file_id)
        response = await self._client.get(FILE.format(token=self._settings["token"], path=info["file_path"]))
        response.raise_for_status()
        return response.content

    async def _converse(self, parts: list[dict], logged: str) -> None:
        if self._heard is not None:
            self._heard("Çağan", logged, "telegram")
        try:
            reply = await self._chat.reply(parts) or "Tamam patron."
        except (httpx.HTTPError, ValueError, KeyError) as error:
            logger.exception("telegram conversation failed")
            await self.send(f"Gemini'ye ulaşamadım patron ({type(error).__name__}).")
            return
        if self._heard is not None:
            self._heard("Cuba", reply, "telegram")
        await self.send(reply)

    # ── Settings ────────────────────────────────────────────────

    def _load(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._settings), encoding="utf-8")
