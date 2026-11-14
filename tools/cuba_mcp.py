"""Cuba's memory as an MCP server, so Claude Code, Claude Desktop and other tools share one memory.

Runs over stdio: `python tools/cuba_mcp.py`. Register it once with
    claude mcp add cuba -s user -- <python> D:\\ClaudeSes\\tools\\cuba_mcp.py
It speaks the small part of MCP a tool server needs (initialize, tools/list, tools/call, ping) by hand,
so no extra package is required.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.config import BELGELER  # noqa: E402
from server.memory import confirm, learn, recall, topics_block, unconfirmed  # noqa: E402

MEMORY_DIR = ROOT / "asistan"
DATA_DIR = ROOT / "data"
DOC_TYPES = {".md", ".pptx", ".pdf", ".docx", ".xlsx", ".csv", ".html"}


def _text(name: str) -> str:
    try:
        return (MEMORY_DIR / name).read_text(encoding="utf-8")
    except FileNotFoundError:
        return "(boş)"


def _gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        try:
            key = (DATA_DIR / "gemini_key.txt").read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            pass
    return key


def documents(project: str = "") -> str:
    root = BELGELER / project if project else BELGELER
    if not root.is_dir():
        return f"{root} yok."
    files = sorted((f for f in root.rglob("*") if f.is_file() and f.suffix.lower() in DOC_TYPES),
                   key=lambda f: f.stat().st_mtime, reverse=True)[:40]
    return "\n".join(str(f) for f in files) or "Belge yok."


async def remember(question: str) -> str:
    from server.semantic import SemanticMemory

    key = _gemini_key()
    if not key:
        return "Gemini anahtarı yok (data/gemini_key.txt ya da GEMINI_API_KEY)."
    memory = SemanticMemory(key, DATA_DIR, MEMORY_DIR, BELGELER)
    await memory.refresh()  # its own short-lived process: index first, then search
    found = await memory.search(question)
    return json.dumps(found, ensure_ascii=False, indent=1)


TOOLS = {
    "cagan_profili": ("Çağan hakkında bilinenler (tercihler, çalışma biçimi, hedefler) ve bugünün planı.",
                      {}, lambda a: f"{_text('cagan.md')}\n\n# Bugün\n{_text('bugun.md')}"),
    "konular": ("Cuba'nın bilgi dosyası olan konular (projeler, firmalar, kişiler).",
                {}, lambda a: topics_block(MEMORY_DIR)),
    "bilgi_oku": ("Bir konu hakkında öğrenilenler (ör. bir proje ya da firma).",
                  {"konu": "Konu adı."}, lambda a: json.dumps(recall(MEMORY_DIR, a["konu"]), ensure_ascii=False)),
    "ogren": ("Bir konuya kalıcı, tek cümlelik bir bilgi ekler; Cuba da bunu bilir. Kaynak Çağan değilse teyitsiz yazılır.",
              {"konu": "Konu adı.", "bilgi": "Tek cümle.", "kaynak": "Nereden öğrenildi."},
              lambda a: json.dumps(learn(MEMORY_DIR, a["konu"], a["bilgi"], a.get("kaynak", "Claude")), ensure_ascii=False)),
    "teyit": ("Çağan bir bilgiyi doğruladıysa ya da yanlış dediyse o satırı işaretler (dogru: evet/hayır).",
              {"konu": "Konu adı.", "bilgi": "Satırdan ayırt edici bir parça.", "dogru": "evet ya da hayır"},
              lambda a: json.dumps(confirm(MEMORY_DIR, a["konu"], a["bilgi"], str(a.get("dogru", "")).casefold() in ("evet", "true", "doğru", "1")), ensure_ascii=False)),
    "teyit_bekleyenler": ("Kaynağı Çağan olmayan, henüz doğrulanmamış bilgiler.",
                          {}, lambda a: json.dumps(unconfirmed(MEMORY_DIR), ensure_ascii=False, indent=1)),
    "hatirla": ("Geçmiş konuşmalarda, bilgi dosyalarında, günlükte ve belgelerde anlamca arar.",
                {"soru": "Ne aranıyor."}, None),
    "belgeler": ("Masaüstündeki belgeler klasöründeki son belgeler; proje verilirse yalnızca onun.",
                 {"proje": "Proje klasörünün adı (isteğe bağlı)."}, lambda a: documents(a.get("proje", ""))),
}
REQUIRED = {"teyit": ["konu", "bilgi", "dogru"], "bilgi_oku": ["konu"], "ogren": ["konu", "bilgi"], "hatirla": ["soru"]}


def tool_list() -> list[dict]:
    return [{"name": name, "description": desc,
             "inputSchema": {"type": "object", "properties": {k: {"type": "string", "description": v}
                                                              for k, v in props.items()},
                             "required": REQUIRED.get(name, [])}}
            for name, (desc, props, _) in TOOLS.items()]


async def call(name: str, args: dict) -> dict:
    if name not in TOOLS:
        return {"content": [{"type": "text", "text": f"Bilinmeyen araç: {name}"}], "isError": True}
    missing = [k for k in REQUIRED.get(name, []) if not str(args.get(k, "")).strip()]
    if missing:
        return {"content": [{"type": "text", "text": f"Eksik: {', '.join(missing)}"}], "isError": True}
    try:
        text = await remember(args["soru"]) if name == "hatirla" else TOOLS[name][2](args)
    except Exception as error:  # noqa: BLE001 - reported to the caller
        return {"content": [{"type": "text", "text": f"Hata: {error}"}], "isError": True}
    return {"content": [{"type": "text", "text": text}]}


async def handle(message: dict) -> dict | None:
    method, params = message.get("method"), message.get("params") or {}
    if "id" not in message:
        return None  # a notification
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "cuba", "version": "1.0.0"}}
    elif method == "tools/list":
        result = {"tools": tool_list()}
    elif method == "tools/call":
        result = await call(params.get("name", ""), params.get("arguments") or {})
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": f"Bilinmeyen: {method}"}}
    return {"jsonrpc": "2.0", "id": message["id"], "result": result}


def main() -> None:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            reply = asyncio.run(handle(json.loads(line)))
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Bozuk JSON"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
