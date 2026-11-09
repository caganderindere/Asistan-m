"""Record a real `claude` stream-json conversation turn for parser fixtures.

Usage: capture_claude.py OUT.jsonl MESSAGE [--interrupt-after-tool]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("message")
    parser.add_argument("--interrupt-after-tool", action="store_true")
    args = parser.parse_args()

    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    command = [
        shutil.which("claude") or "claude",
        "-p", "--input-format", "stream-json", "--output-format", "stream-json",
        "--verbose", "--include-partial-messages", "--permission-mode", "bypassPermissions",
    ]
    proc = subprocess.Popen(
        command, cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, encoding="utf-8", bufsize=1,
    )
    stderr_lines: list[str] = []
    threading.Thread(target=lambda: stderr_lines.extend(proc.stderr), daemon=True).start()

    proc.stdin.write(json.dumps(
        {"type": "user", "message": {"role": "user", "content": args.message}}, ensure_ascii=False
    ) + "\n")
    proc.stdin.flush()

    interrupted_at: float | None = None
    with args.out.open("w", encoding="utf-8") as out:
        for line in proc.stdout:
            out.write(line)
            event = json.loads(line) if line.strip().startswith("{") else {}
            if (
                args.interrupt_after_tool and interrupted_at is None
                and "tool_use" in json.dumps(event.get("message", {}))
            ):
                proc.stdin.write(json.dumps(
                    {"type": "control_request", "request_id": "int-1", "request": {"subtype": "interrupt"}}
                ) + "\n")
                proc.stdin.flush()
                interrupted_at = time.monotonic()
            if event.get("type") == "result":
                break

    if interrupted_at is not None:
        print(f"result {time.monotonic() - interrupted_at:.1f}s after interrupt")
    proc.stdin.close()
    proc.wait(timeout=30)
    if stderr_lines:
        print("stderr:", "".join(stderr_lines)[-2000:], file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
