import json

import httpx
import pytest

from server.omni import OmniClient, OmniError, OmniLimit, load_key


def client(handler) -> OmniClient:
    return OmniClient("k", transport=httpx.MockTransport(handler))


async def test_chat_returns_message():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Merhaba"}}]})

    msg = await client(handler).chat([{"role": "user", "content": "selam"}])
    assert msg["content"] == "Merhaba"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "ofis" and seen["body"]["stream"] is False
    assert "tools" not in seen["body"]


async def test_tools_are_sent_and_tool_calls_returned():
    calls = [{"id": "c1", "type": "function", "function": {"name": "mesaj_at", "arguments": "{}"}}]

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["tools"] == [{"type": "function"}]
        return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": calls}}]})

    msg = await client(handler).chat([], tools=[{"type": "function"}])
    assert msg["tool_calls"] == calls


async def test_limit_raises_omnilimit():
    with pytest.raises(OmniLimit):
        await client(lambda r: httpx.Response(429, json={"error": {"message": "slow down"}})).chat([])


async def test_unreachable_raises_omnierror():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(OmniError, match="OmniRoute'a ulaşılamadı"):
        await client(handler).chat([])


async def test_no_key_raises():
    omni = OmniClient("")
    assert omni.available is False
    with pytest.raises(OmniError):
        await omni.chat([])


def test_load_key_prefers_env(monkeypatch, tmp_path):
    path = tmp_path / "key.txt"
    path.write_text(" dosya \n", encoding="utf-8")
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    assert load_key(path) == "dosya"
    monkeypatch.setenv("OMNIROUTE_API_KEY", "ortam")
    assert load_key(path) == "ortam"
    monkeypatch.delenv("OMNIROUTE_API_KEY")
    assert load_key(tmp_path / "yok.txt") == ""
