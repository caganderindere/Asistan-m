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
import re
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


# The terminal runs with every permission; these are the lock on that. A block is never run,
# whoever asks; an ask stops for Çağan (away, Cuba answers for him as with any permission).
_ROOTS = r"""(?:/|~|\$HOME|\$env:USERPROFILE|[a-z]:[\\/]?|/[a-z]/?|\*|\.\.?/?)(?:\s|$|["'])"""
BLOCK = [
    (rf"\brm\s+(?:-\w+\s+)*-\w*[rR]\w*\s+(?:-\w+\s+)*[\"']?{_ROOTS}", "diskin ya da ev klasörünün tamamını silmek"),
    (rf"Remove-Item\b.*-Recurse.*\s[\"']?{_ROOTS}|Remove-Item\s+[\"']?{_ROOTS}.*-Recurse", "diskin ya da ev klasörünün tamamını silmek"),
    (r"\bformat\s+[a-z]:|\bdiskpart\b|\bmkfs\b|\bdd\s+if=.*\bof=/dev/|Format-Volume|Clear-Disk", "diski biçimlendirmek"),
    (r"\bgit\s+push\b.*(?:\s--force\b|\s-f\b|\s--force-with-lease\b|\s\+\S)", "git geçmişini zorla ezmek (force push)"),
    (r"\b(?:shutdown|Stop-Computer|Restart-Computer)\b|\bbcdedit\b|\breg\s+delete\s+HKLM", "bilgisayarı ya da sistemi kurcalamak"),
    (r"\bDROP\s+DATABASE\b", "veritabanını silmek"),
]
ASK = [
    (r"\bgit\s+push\b", "git push"),
    (r"\bgit\s+(?:reset\s+--hard|clean\s+-\w*f|checkout\s+--\s|restore\s+\.|branch\s+-D|stash\s+(?:drop|clear))", "kaydedilmemiş işi ya da dalı silebilecek git komutu"),
    (r"\brm\s+(?:-\w+\s+)*-\w*[rR]|\bRemove-Item\b.*-Recurse|\brmdir\s+/s|\brd\s+/s|\bdel\s+/s", "klasör silmek"),
    (r"\b(?:npm|pnpm|yarn)\s+publish\b|\btwine\s+upload\b|\bgh\s+(?:release\s+create|pr\s+merge|repo\s+delete)", "yayınlamak"),
    (r"\b(?:vercel\b.*--prod|firebase\s+deploy|wrangler\s+deploy|netlify\s+deploy|terraform\s+(?:apply|destroy)|kubectl\s+delete|docker\s+system\s+prune)", "canlıya dağıtmak ya da altyapıyı değiştirmek"),
    (r"\b(?:ssh|scp|sftp)\s", "uzak sunucuya bağlanmak"),
    (r"\bDROP\s+TABLE\b|\bTRUNCATE\b|\bDELETE\s+FROM\s+\w+\s*(?:;|$)", "veritabanından veri silmek"),
    (r"\b(?:pip|npm|winget|choco)\s+uninstall\b", "paket kaldırmak"),
    (r"\b(?:curl|wget|iwr|Invoke-WebRequest)\b.*\|\s*(?:sh|bash|iex|Invoke-Expression)\b", "internetten indirilen betiği doğrudan çalıştırmak"),
]
WRITERS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


def _inside(path: str, project: str) -> bool:
    """Writing is free in the project, its work branches, Claude's own folders and temp."""
    full = os.path.normcase(os.path.abspath(os.path.join(project or ".", path)))
    homes = [project, f"{project.rstrip(os.sep + '/')}-isler", os.path.expanduser("~/.claude"),
             os.environ.get("TEMP", ""), os.environ.get("TMP", "")]
    for home in filter(None, homes):
        home = os.path.normcase(os.path.abspath(home))
        if full == home or full.startswith(home.rstrip(os.sep) + os.sep):
            return True
    return False


def judge(tool: str, tool_input: dict, project: str) -> tuple[str, str]:
    """("deny" | "ask" | "", why) for one tool call of the terminal's Claude or its team."""
    if tool in ("Bash", "PowerShell"):
        command = str(tool_input.get("command", ""))
        for pattern, what in BLOCK:
            if re.search(pattern, command, re.IGNORECASE):
                return "deny", f"Kilitli: {what}. Bu komut hiçbir koşulda çalıştırılmaz; başka yol bul ya da Çağan'a raporla."
        for pattern, what in ASK:
            if re.search(pattern, command, re.IGNORECASE):
                return "ask", f"Riskli: {what}. Çağan'ın onayı gerekiyor."
    if tool in WRITERS and project:
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if path and not _inside(path, project):
            return "ask", f"Proje dışına yazma: {path}. Çağan'ın onayı gerekiyor."
    return "", ""


def main() -> None:
    kind = sys.argv[1] if len(sys.argv) > 1 else "stop"
    if kind == "session_start":
        sys.stdout.reconfigure(encoding="utf-8")
        with open(sys.argv[2], encoding="utf-8") as f:
            print(f.read())
        return
    sys.stdout.reconfigure(encoding="utf-8")
    data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    if kind == "pre":
        decision, reason = judge(data.get("tool_name", ""), data.get("tool_input") or {},
                                 os.environ.get("CLAUDE_SES_TERMINAL", "") or data.get("cwd", ""))
        if decision:
            # Decided here, without the server: the lock must hold even when the server is down.
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                                     "permissionDecisionReason": reason}}, ensure_ascii=False))
            return
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
