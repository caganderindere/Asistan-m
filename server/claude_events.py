"""Translate `claude --output-format stream-json` lines into a few typed events."""

from __future__ import annotations

import json
from dataclasses import dataclass

SUMMARY_LIMIT = 80
_SUMMARY_KEYS = ("command", "file_path", "pattern")


@dataclass
class SessionInit:
    session_id: str


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolUse:
    name: str
    summary: str


@dataclass
class TurnResult:
    session_id: str
    is_error: bool


Event = SessionInit | TextDelta | ToolUse | TurnResult


def _summary(tool_input: dict) -> str:
    for key in _SUMMARY_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            first_line = value.strip().splitlines()[0] if value.strip() else ""
            return first_line[:SUMMARY_LIMIT]
    return ""


def parse_line(line: str) -> list[Event]:
    """Return the events carried by one stdout line; unknown or broken lines yield none."""
    try:
        data = json.loads(line)
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []

    kind = data.get("type")
    if kind == "system" and data.get("subtype") == "init":
        return [SessionInit(data.get("session_id", ""))]
    if kind == "stream_event":
        # Text arrives here as it streams; the later `assistant` snapshot repeats
        # it, so only this path is read for text.
        delta = data.get("event", {}).get("delta", {})
        if delta.get("type") == "text_delta" and delta.get("text"):
            return [TextDelta(delta["text"])]
        return []
    if kind == "assistant":
        # Tool input is complete only in the snapshot; the stream starts it empty.
        content = data.get("message", {}).get("content", [])
        return [
            ToolUse(block.get("name", ""), _summary(block.get("input") or {}))
            for block in content
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]
    if kind == "result":
        is_error = bool(data.get("is_error")) or data.get("subtype") != "success"
        return [TurnResult(data.get("session_id", ""), is_error)]
    return []


def user_message(text: str) -> str:
    """One stdin line that sends *text* as the user's next message."""
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}}, ensure_ascii=False) + "\n"


def interrupt_request(request_id: str) -> str:
    """One stdin line asking Claude to stop the current turn."""
    return json.dumps(
        {"type": "control_request", "request_id": request_id, "request": {"subtype": "interrupt"}}
    ) + "\n"
