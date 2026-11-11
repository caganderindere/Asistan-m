"""Let Daim talk on Gemini, so everyday conversation costs no Claude tokens.

Speaks the same interface as ClaudeBridge (start, send, events, interrupt,
new_session, close), so the team cannot tell the two apart. Coding work still
goes to the Claude workers through tools/ekip.py, called as a Gemini function.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import json
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx

from server.claude_events import Event, TextDelta, ToolUse, TurnResult
from server.config import ROOT
from server.session_store import SessionStore

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
ONE_SHOT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MEMORY_DIR = ROOT / "asistan"
MEMORY_FILES = ("gorevler.md", "takvim.md", "notlar.md")
PROGRAMS = {
    "ekip": ROOT / "tools" / "ekip.py",
    "hatirlatma": ROOT / "tools" / "reminder.py",
    "ofis": ROOT / "tools" / "ofis.py",
}
# Only the latest turns are sent back; the memory files carry what must last.
KEPT_CONTENTS = 24
MAX_TOOL_ROUNDS = 6
OUTPUT_LIMIT = 4000
DAYS = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")

ADAPTER = """
# Bu oturumda araçlar
Kabuğun yok; işleri şu fonksiyonlarla yap:
- `komut(program, args)`: program "ekip", "hatirlatma" ya da "ofis". Ofis komutu için
  komut(program="ofis", args=["git", "toplanti", "daim", "kidemli"]) gibi çağır. Yukarıda `{ekip} plan --gorev "..."` yazan yerde
  komut(program="ekip", args=["plan", "--gorev", "..."]) çağır. Hatırlatma için `reminder.py add --at ... --text ...`
  yerine komut(program="hatirlatma", args=["add", "--at", "YYYY-MM-DD HH:MM", "--text", "metin"]).
- `dosya_yaz(ad, icerik)`: gorevler.md, takvim.md ya da notlar.md dosyasının tamamını yazar.
Dosyaların güncel hâli ve şu anki tarih aşağıda; okumak ya da Get-Date çalıştırmak gerekmez.
Projeyi okuyamazsın: proje hakkındaki her soruyu ve işi ekibe ver.
"""

TOOLS = [{
    "functionDeclarations": [
        {
            "name": "komut",
            "description": "Ekip ya da hatırlatma aracını çalıştırır, çıktısını ve çıkış kodunu döner.",
            "parameters": {
                "type": "object",
                "properties": {
                    "program": {"type": "string", "enum": list(PROGRAMS)},
                    "args": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["program", "args"],
            },
        },
        {
            "name": "dosya_yaz",
            "description": "Bir hafıza dosyasının tüm içeriğini yazar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ad": {"type": "string", "enum": list(MEMORY_FILES)},
                    "icerik": {"type": "string"},
                },
                "required": ["ad", "icerik"],
            },
        },
    ]
}]


def now_line(now: datetime.datetime) -> str:
    return f"Şu an: {now:%Y-%m-%d %H:%M} {DAYS[now.weekday()]}"


def memory_block(memory_dir: Path) -> str:
    parts = []
    for name in MEMORY_FILES:
        try:
            text = (memory_dir / name).read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            text = ""
        parts.append(f"## {name}\n{text or '(boş)'}")
    return "\n\n".join(parts)


def trim(contents: list[dict], keep: int = KEPT_CONTENTS) -> list[dict]:
    """The last *keep* contents, starting at a user's own words so no tool reply is orphaned."""
    tail = contents[-keep:]
    for i, content in enumerate(tail):
        if content["role"] == "user" and any("text" in p for p in content["parts"]):
            return tail[i:]
    return []


async def run_program(program: str, args: list[str]) -> dict:
    script = PROGRAMS.get(program)
    if script is None:
        return {"exit_code": 2, "output": f"Bilinmeyen program: {program}"}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(script), *map(str, args),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return {"exit_code": proc.returncode, "output": out.decode("utf-8", errors="replace")[-OUTPUT_LIMIT:]}


async def ask_gemini(
    api_key: str,
    model: str,
    system: str,
    prompt: str,
    as_json: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """One question, one answer: for summaries and decisions, not conversation."""
    body: dict = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }
    if as_json:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(60, connect=10)) as client:
        response = await client.post(ONE_SHOT.format(model=model), json=body, headers={"x-goog-api-key": api_key})
    response.raise_for_status()
    parts = response.json()["candidates"][0]["content"].get("parts", [])
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


class MissingKey(OSError):
    """No Gemini API key was given."""


class GeminiBridge:
    def __init__(
        self,
        store: SessionStore,
        prompt_file: Path,
        api_key: str,
        model: str,
        thinking_budget: int | None = 0,
        memory_dir: Path = MEMORY_DIR,
        runner: Callable = run_program,
        clock: Callable[[], datetime.datetime] = datetime.datetime.now,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._history_path = store.path.with_suffix(".gemini.json")
        self._prompt_file = prompt_file
        self._api_key = api_key
        self._model = model
        self._thinking_budget = thinking_budget
        self._memory_dir = memory_dir
        self._runner = runner
        self._clock = clock
        self._transport = transport
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._turn: asyncio.Task | None = None
        self._contents: list[dict] = []
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if not self._api_key:
            raise MissingKey(
                "Gemini anahtarı yok. GEMINI_API_KEY ortam değişkenini ya da data klasöründeki gemini_key.txt dosyasını ayarlayın."
            )
        if self._client is None:
            self._client = httpx.AsyncClient(transport=self._transport, timeout=httpx.Timeout(60, connect=10))
            self._contents = self._load()

    async def send(self, text: str) -> None:
        await self.start()
        self._turn = asyncio.create_task(self._run(text))

    async def events(self) -> AsyncIterator[Event]:
        while True:
            yield await self._queue.get()

    async def interrupt(self, timeout: float = 3.0) -> None:
        turn = self._turn
        if turn is None or turn.done():
            return
        turn.cancel()
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(turn, timeout)

    async def new_session(self) -> None:
        await self.interrupt()
        self._contents = []
        self._history_path.unlink(missing_ok=True)

    async def close(self) -> None:
        await self.interrupt()
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── One turn ───────────────────────────────────────────────

    async def _run(self, text: str) -> None:
        contents = trim(self._contents) + [{"role": "user", "parts": [{"text": text}]}]
        try:
            for _ in range(MAX_TOOL_ROUNDS):
                parts = await self._generate(contents)
                contents.append({"role": "model", "parts": parts})
                calls = [p["functionCall"] for p in parts if "functionCall" in p]
                if not calls:
                    break
                replies = []
                for call in calls:
                    self._queue.put_nowait(ToolUse(call.get("name", ""), _summary(call.get("args") or {})))
                    replies.append({"functionResponse": {
                        "name": call.get("name", ""), "response": await self._call(call),
                    }})
                contents.append({"role": "user", "parts": replies})
        except asyncio.CancelledError:
            self._queue.put_nowait(TurnResult("", is_error=False))
            raise
        except (httpx.HTTPError, ValueError) as e:
            self._queue.put_nowait(TurnResult("", is_error=True, message=_reason(e)))
            return
        self._contents = contents
        self._save()
        self._queue.put_nowait(TurnResult("", is_error=False))

    async def _generate(self, contents: list[dict]) -> list[dict]:
        """Stream one model reply, passing its text on as it comes; return all its parts."""
        assert self._client is not None
        system = f"{self._prompt_file.read_text(encoding='utf-8')}\n{ADAPTER}\n{now_line(self._clock())}\n\n" \
                 f"# Hafıza dosyaları\n{memory_block(self._memory_dir)}"
        body: dict = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "tools": TOOLS,
        }
        if self._thinking_budget is not None:
            body["generationConfig"] = {"thinkingConfig": {"thinkingBudget": self._thinking_budget}}
        parts: list[dict] = []
        async with self._client.stream(
            "POST", API.format(model=self._model), json=body, headers={"x-goog-api-key": self._api_key},
        ) as response:
            if response.status_code != 200:
                raise ValueError(f"Gemini {response.status_code}: {(await response.aread()).decode()[:300]}")
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                chunk = json.loads(line[5:])
                for candidate in chunk.get("candidates", [])[:1]:
                    for part in candidate.get("content", {}).get("parts", []):
                        if part.get("text") and not part.get("thought"):
                            self._queue.put_nowait(TextDelta(part["text"]))
                        parts.append(part)
        return _merge_text(parts) or [{"text": ""}]

    async def _call(self, call: dict) -> dict:
        name, args = call.get("name"), call.get("args") or {}
        if name == "komut":
            return await self._runner(args.get("program", ""), list(args.get("args", [])))
        if name == "dosya_yaz" and args.get("ad") in MEMORY_FILES:
            self._memory_dir.mkdir(parents=True, exist_ok=True)
            (self._memory_dir / args["ad"]).write_text(args.get("icerik", ""), encoding="utf-8")
            return {"ok": True}
        return {"error": f"Bilinmeyen fonksiyon ya da dosya: {name}"}

    # ── History on disk ────────────────────────────────────────

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self._history_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return []
        return data if isinstance(data, list) else []

    def _save(self) -> None:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        self._history_path.write_text(json.dumps(trim(self._contents), ensure_ascii=False), encoding="utf-8")


def _merge_text(parts: list[dict]) -> list[dict]:
    """Join streamed plain-text pieces; keep calls, thoughts and signatures as sent."""
    merged: list[dict] = []
    for part in parts:
        plain = set(part) == {"text"}
        if plain and merged and set(merged[-1]) == {"text"}:
            merged[-1] = {"text": merged[-1]["text"] + part["text"]}
        else:
            merged.append(dict(part))
    return merged


def _summary(args: dict) -> str:
    if "args" in args:
        return " ".join([args.get("program", ""), *map(str, args["args"])])[:80]
    return str(args.get("ad", ""))


def _reason(error: Exception) -> str:
    if isinstance(error, httpx.HTTPError):
        return "Gemini'ye ulaşılamadı; internet bağlantısını kontrol edin."
    return str(error)
