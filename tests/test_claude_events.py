import json
from pathlib import Path

from server.claude_events import (
    SessionInit,
    TextDelta,
    ToolUse,
    TurnResult,
    interrupt_request,
    parse_line,
    user_message,
)

FIX = Path(__file__).parent / "fixtures"


def events(name):
    return [e for line in (FIX / name).read_text(encoding="utf-8").splitlines() for e in parse_line(line)]


def text_of(evs):
    return "".join(e.text for e in evs if isinstance(e, TextDelta))


def test_text_fixture():
    ev = events("claude_text.jsonl")
    assert isinstance(ev[0], SessionInit) and ev[0].session_id
    assert "Merhaba" in text_of(ev)
    assert isinstance(ev[-1], TurnResult) and not ev[-1].is_error


def test_text_is_not_duplicated_from_assistant_snapshot():
    assert text_of(events("claude_text.jsonl")) == "Merhaba!"


def test_tool_fixture_has_summary():
    tools = [e for e in events("claude_tool.jsonl") if isinstance(e, ToolUse)]
    assert tools and all(len(t.summary) <= 80 for t in tools)
    assert all(t.summary for t in tools if t.name in ("Bash", "PowerShell"))


def test_interrupted_turn_is_error_result():
    ev = events("claude_interrupt.jsonl")
    assert ToolUse("PowerShell", "Start-Sleep 20") in ev
    assert isinstance(ev[-1], TurnResult) and ev[-1].is_error


def test_garbage_lines():
    assert parse_line("") == [] and parse_line("{bozuk") == [] and parse_line('{"type":"x"}') == []


def test_user_message_roundtrip_turkish():
    line = user_message("ğüşıöç İĞÜŞ")
    assert line.endswith("\n") and json.loads(line)["message"]["content"] == "ğüşıöç İĞÜŞ"


def test_interrupt_request_shape():
    req = json.loads(interrupt_request("int-1"))
    assert req == {"type": "control_request", "request_id": "int-1", "request": {"subtype": "interrupt"}}
