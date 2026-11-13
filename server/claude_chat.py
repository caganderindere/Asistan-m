"""Short toolless answers from Claude: what a marketing member says in a meeting, and its summary.

Runs the Claude Code CLI headless with everything stripped (no tools, hooks, MCP, skills), so one
answer costs a few hundred tokens on Çağan's own Claude plan. Same face as OmniClient.chat.
"""

from __future__ import annotations

import asyncio
import json
import shutil

from server.omni import OmniError, OmniLimit

LEAN = ["--tools", "", "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands",
        "--settings", '{"disableAllHooks":true}', "--output-format", "json"]


class ClaudeChat:
    def __init__(self, model: str = "haiku", exe: str | None = None, timeout: float = 90) -> None:
        self.model = model
        self._exe = exe or shutil.which("claude") or ""
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self._exe)

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """The answer as `{"content": ...}`; *tools* are not offered, meetings need none."""
        if not self._exe:
            raise OmniError("Claude Code bulunamadı.")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        prompt = "\n\n".join(str(m.get("content") or "") for m in messages if m["role"] != "system")
        proc = await asyncio.create_subprocess_exec(
            self._exe, "-p", "--model", self.model, "--system-prompt", system or "Türkçe, kısa cevap ver.", *LEAN,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(prompt.encode("utf-8")), self._timeout)
        except TimeoutError as e:
            proc.kill()
            raise OmniError("Claude zamanında cevap vermedi.") from e
        try:
            data = json.loads(out.decode("utf-8", errors="replace"))
        except ValueError as e:
            raise OmniError(f"Claude hatası: {err.decode('utf-8', errors='replace')[:200]}") from e
        if data.get("is_error"):
            text = str(data.get("result") or "")
            raise (OmniLimit if "limit" in text.lower() else OmniError)(f"Claude hatası: {text[:200]}")
        return {"content": str(data.get("result") or "")}
