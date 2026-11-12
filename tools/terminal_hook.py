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


def main() -> None:
    kind = sys.argv[1] if len(sys.argv) > 1 else "stop"
    if kind == "session_start":
        sys.stdout.reconfigure(encoding="utf-8")
        with open(sys.argv[2], encoding="utf-8") as f:
            print(f.read())
        return
    sys.stdout.reconfigure(encoding="utf-8")
    data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    body = {"kind": kind}
    if kind == "prompt":
        body["text"] = data.get("prompt", "")
    elif kind == "stop":
        body["text"] = data.get("last_assistant_message") or last_reply(data.get("transcript_path", ""))
    elif kind in ("pre", "post"):
        body.update(
            tool=data.get("tool_name", ""), use_id=data.get("tool_use_id", ""), agent=data.get("agent_id", ""),
            # Only the short fields the office shows; a file being written can be large.
            input={k: v for k, v in (data.get("tool_input") or {}).items() if isinstance(v, str) and len(v) < 500},
        )
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
