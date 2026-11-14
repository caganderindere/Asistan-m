import asyncio
import json

import httpx

from server.semantic import SemanticMemory, pieces
from server.screen import look


def _embedder(calls):
    words = ["rubber", "rabia", "müzik"]

    def handler(request):
        body = json.loads(request.content)
        calls.append(len(body["requests"]))
        vectors = []
        for r in body["requests"]:
            text = r["content"]["parts"][0]["text"].casefold()
            vectors.append({"values": [1.0 if w in text else 0.0 for w in words] + [0.1]})
        return httpx.Response(200, json={"embeddings": vectors})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_search_finds_by_meaning_and_embeds_only_new_pieces(tmp_path):
    (tmp_path / "konusmalar").mkdir()
    (tmp_path / "konusmalar" / "2026-11-14.jsonl").write_text(
        json.dumps({"time": "2026-11-14 10:00:00", "who": "Çağan", "text": "ASP Rubber gönderileri"}) + "\n", encoding="utf-8")
    (tmp_path / "asistan" / "bilgi").mkdir(parents=True)
    (tmp_path / "asistan" / "bilgi" / "rabia.md").write_text("# Rabia\n- Rabia sevgilisi.\n", encoding="utf-8")
    calls = []
    memory = SemanticMemory("k", tmp_path, tmp_path / "asistan", tmp_path / "yok", _embedder(calls))
    assert asyncio.run(memory.refresh()) == 2

    async def search(question):
        found = await memory.search(question)
        await memory._indexing
        return found
    found = asyncio.run(search("rubber"))["hatirladiklarim"]
    assert found[0]["kaynak"] == "konuşma 2026-11-14" and found[0]["tarih"] == "2026-11-14"
    assert calls == [2, 1]  # two pieces, then the question; nothing new to embed after
    asyncio.run(search("rabia"))
    assert calls == [2, 1, 1]
    assert len(list(pieces(tmp_path, tmp_path / "asistan", tmp_path / "yok"))) == 2


def test_look_sends_the_screenshot_with_the_question():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Bir hata var."}]}}]})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    answer = asyncio.run(look("k", "m", "Bu ne?", grab=lambda: b"jpeg", client=client))
    assert answer == {"gordugum": "Bir hata var."}
    parts = seen["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "image/jpeg" and parts[1]["text"] == "Bu ne?"


def test_mcp_server_lists_and_calls_tools():
    import sys
    sys.path.insert(0, "tools")
    import cuba_mcp
    init = asyncio.run(cuba_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}))
    assert init["result"]["serverInfo"]["name"] == "cuba"
    names = [t["name"] for t in asyncio.run(cuba_mcp.handle({"id": 2, "method": "tools/list"}))["result"]["tools"]]
    assert {"bilgi_oku", "ogren", "hatirla", "konular"} <= set(names)
    missing = asyncio.run(cuba_mcp.handle({"id": 3, "method": "tools/call", "params": {"name": "bilgi_oku", "arguments": {}}}))
    assert missing["result"]["isError"]
    assert asyncio.run(cuba_mcp.handle({"method": "notifications/initialized"})) is None


def test_too_many_requests_waits_and_tries_again(tmp_path):
    answers = [429, 200]

    def handler(request):
        status = answers.pop(0)
        return httpx.Response(status, json={"embeddings": [{"values": [1.0]}]} if status == 200 else {})
    memory = SemanticMemory("k", tmp_path, tmp_path, tmp_path, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    waits = []

    async def wait(seconds):
        waits.append(seconds)
    memory._sleep = wait
    assert asyncio.run(memory._embed(["x"], "RETRIEVAL_QUERY")) == [[1.0]] and waits == [30]
