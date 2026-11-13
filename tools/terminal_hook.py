"""Claude Code hook for the embedded terminal: hand the answer to the voice.

`session_start <file>`: prints the charter that makes the terminal's Claude act as Cuba.
`stop`: posts Claude's last reply so it is read aloud.
`permission`: posts that Claude is waiting for approval.
`prompt`, `pre`, `post`: post what Claude and its subagents are doing, for the office.
`permission_request`: while the user is away, Cuba grants it.
With the user away, `stop` may come back with Cuba's next instruction, which keeps Claude going.
Never fails Claude: any problem is ignored and the hook exits 0.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request


def last_reply(transcript: str) -> str:
    """The text Claude wrote after the user's last message."""
    parts: list[str] = []
    with open(transcript, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            content = (entry.get("message") or {}).get("content")
            if entry.get("type") == "user":
                # Tool results come back as user entries; only real words start a new reply.
                if isinstance(content, str) or any(
                    isinstance(b, dict) and b.get("type") == "text" for b in content or []
                ):
                    parts = []
            elif entry.get("type") == "assistant" and isinstance(content, list):
                parts += [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(parts)


def result_text(response) -> str:
    """The words in a tool's response, however Claude Code shaped it."""
    if isinstance(response, str):
        return response
    if isinstance(response, list):
        return "\n".join(result_text(item) for item in response)
    if isinstance(response, dict):
        if isinstance(response.get("text"), str):
            return response["text"]
        for key in ("content", "result", "output"):
            if key in response:
                return result_text(response[key])
    return ""


def main() -> None:
    kind = sys.argv[1] if len(sys.argv) > 1 else "stop"
    if kind == "session_start":
        sys.stdout.reconfigure(encoding="utf-8")
        with open(sys.argv[2], encoding="utf-8") as f:
            print(f.read())
        return
    sys.stdout.reconfigure(encoding="utf-8")
    data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    # Which project's terminal this Claude runs in: each project has its own.
    body = {"kind": kind, "terminal": os.environ.get("CLAUDE_SES_TERMINAL", "")}
    if kind == "prompt":
        body["text"] = data.get("prompt", "")
    elif kind == "stop":
        body["text"] = data.get("last_assistant_message") or last_reply(data.get("transcript_path", ""))
    elif kind == "subagent_stop":
        body.update(agent=data.get("agent_id", ""), agent_type=data.get("agent_type", ""),
                    result=str(data.get("last_assistant_message") or "")[-3000:])
    elif kind in ("pre", "post"):
        body.update(
            tool=data.get("tool_name", ""), use_id=data.get("tool_use_id", ""), agent=data.get("agent_id", ""),
            # Only the short fields the office shows; a file being written can be large.
            input={k: v for k, v in (data.get("tool_input") or {}).items() if isinstance(v, str) and len(v) < 500},
        )
        raw = data.get("tool_input") or {}
        edits = raw.get("edits") if isinstance(raw.get("edits"), list) else []
        written = raw.get("new_string") or raw.get("content") or raw.get("new_source") or (
            edits[0].get("new_string") if edits and isinstance(edits[0], dict) else "")
        if raw.get("run_in_background") is True:
            body["input"]["run_in_background"] = "true"
        if kind == "pre" and isinstance(written, str) and written:
            # The start of the code being written, to float over the writer's desk.
            body["input"]["new_string"] = written[:1500]
        if kind == "post":
            # A subagent's final report: the team talks it over once the work is done.
            body["result"] = result_text(data.get("tool_response"))[-3000:]
    request = urllib.request.Request(
        f"http://127.0.0.1:{os.environ.get('CLAUDE_SES_PORT', '8765')}/api/team/terminal",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Ekip-Token": os.environ.get("CLAUDE_SES_TOKEN", "")},
    )
    with urllib.request.urlopen(request, timeout=85) as response:
        answer = json.load(response)
    if answer.get("continue_with"):
        print(json.dumps({"decision": "block", "reason": answer["continue_with"]}, ensure_ascii=False))
    elif answer.get("behavior"):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PermissionRequest", "decision": {"behavior": answer["behavior"]},
        }}))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - a broken hook must never stop Claude
        pass
