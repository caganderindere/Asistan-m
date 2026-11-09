"""Stand-in for `claude -p` stream-json, driven by message content.

  "öl"    -> exit(1) mid-turn
  "yavaş" -> wait for an interrupt request (or ignore it with --ignore-interrupt)
  "uzun"  -> one 200 KB line before the reply
  other   -> echo the message as text, then a success result
"""

import json
import os
import sys
import time
import uuid

args = sys.argv[1:]
if os.environ.get("FAKE_ARGS_LOG"):
    with open(os.environ["FAKE_ARGS_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps(args) + "\n")

session = args[args.index("--resume") + 1] if "--resume" in args else str(uuid.uuid4())
ignore_interrupt = "--ignore-interrupt" in args
stdin = open(sys.stdin.fileno(), encoding="utf-8")
stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", buffering=1)


def emit(obj):
    stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    stdout.flush()


def text(t):
    emit({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": t}}})


def result(ok):
    emit({"type": "result", "subtype": "success" if ok else "error_during_execution",
          "is_error": not ok, "session_id": session})


emit({"type": "system", "subtype": "init", "session_id": session})
for line in stdin:
    msg = json.loads(line)
    if msg.get("type") != "user":
        continue
    content = msg["message"]["content"]
    if content == "öl":
        sys.exit(1)
    if content == "yavaş":
        emit({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "sleep 60"}}]}})
        if ignore_interrupt:
            time.sleep(60)
        for req in stdin:
            if json.loads(req).get("type") == "control_request":
                result(False)
                break
        continue
    if content == "uzun":
        emit({"type": "user", "message": {"content": "x" * 200_000}})
    text(content)
    result(True)
