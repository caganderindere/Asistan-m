"""Cuba in writing: the same Cuba as on the voice line, with the same tools and memory.

The page's message box and Telegram both talk to Cuba through this; only how the answer is
shown differs, which each caller says in *adapter*.
"""

from __future__ import annotations

import httpx

from server.live import LIVE_TOOLS, CubaTools
from server.usage import GEMINI

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
KEPT_CONTENTS = 20
MAX_TOOL_ROUNDS = 6


class CubaChat:
    def __init__(
        self,
        gemini_key: str,
        model: str,
        tools: CubaTools,
        diary=str,
        adapter: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._key = gemini_key
        self._model = model
        self._tools = tools
        self._diary = diary
        self._adapter = adapter
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(70, connect=10))
        self._contents: list[dict] = []

    async def reply(self, parts: list[dict], on_tool=None) -> str:
        """Answer one message (text or audio parts), running Cuba's tools as asked.

        *on_tool(name, args)* hears each tool call. Raises httpx.HTTPError, ValueError or KeyError
        when Gemini cannot be reached or answers oddly.
        """
        contents = self._contents[-KEPT_CONTENTS:] + [{"role": "user", "parts": parts}]
        # A history must start at the user's own words, not a tool reply.
        while contents and not any("text" in p or "inlineData" in p for p in contents[0]["parts"]):
            contents.pop(0)
        reply = ""
        for _ in range(MAX_TOOL_ROUNDS):
            answer = await self._generate(contents)
            contents.append({"role": "model", "parts": answer})
            calls = [p["functionCall"] for p in answer if "functionCall" in p]
            reply += "".join(p.get("text", "") for p in answer if not p.get("thought"))
            if not calls:
                break
            results = []
            for call in calls:
                if on_tool is not None:
                    await on_tool(call.get("name", ""), call.get("args") or {})
                results.append({"functionResponse": {
                    "name": call.get("name", ""), "response": await self._tools.run(call.get("name", ""), call.get("args") or {}),
                }})
            contents.append({"role": "user", "parts": results})
        # Audio is not kept: it is large, and what it said is in the reply.
        self._contents = [c for c in contents if not any("inlineData" in p for p in c["parts"])][-KEPT_CONTENTS:]
        return reply.strip()

    async def _generate(self, contents: list[dict]) -> list[dict]:
        body = {
            "systemInstruction": {"parts": [{"text": self._tools.prompt(self._diary()) + self._adapter}]},
            "contents": contents,
            "tools": LIVE_TOOLS,
        }
        response = await self._client.post(GEMINI_URL.format(model=self._model), json=body,
                                           headers={"x-goog-api-key": self._key})
        response.raise_for_status()
        data = response.json()
        GEMINI.add(data.get("usageMetadata"))
        return data["candidates"][0]["content"].get("parts", []) or [{"text": ""}]

    async def close(self) -> None:
        await self._client.aclose()
