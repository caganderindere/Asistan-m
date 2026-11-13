"""What the office's members say to each other: kept for the day, logged, and shown as it happens."""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import json
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

KEPT = 200


@dataclass
class Message:
    sender: str
    to: str
    text: str
    channel: str = "birebir"  # birebir | toplanti
    time: str = ""


class OfficeBus:
    def __init__(self, log_dir: Path, clock: Callable[[], datetime.datetime] = datetime.datetime.now) -> None:
        self._dir = log_dir
        self._clock = clock
        self._messages: deque[Message] = deque(maxlen=KEPT)
        self._listeners: list[Callable[[Message], None]] = []

    def subscribe(self, listener: Callable[[Message], None]) -> None:
        self._listeners.append(listener)

    def post(self, message: Message) -> Message:
        now = self._clock()
        message.time = message.time or now.strftime("%H:%M")
        self._messages.append(message)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with open(self._dir / f"{now:%Y-%m-%d}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(dataclasses.asdict(message), ensure_ascii=False) + "\n")
        except OSError:
            logger.exception("office log not written")
        for listener in self._listeners:
            with contextlib.suppress(Exception):  # one broken listener must not silence the rest
                listener(message)
        return message

    def recent(self, who: str, limit: int = 10) -> list[Message]:
        """What *who* said or heard lately, oldest first."""
        return [m for m in self._messages if who in (m.sender, m.to)][-limit:]
