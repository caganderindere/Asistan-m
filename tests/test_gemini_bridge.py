import asyncio
import datetime
import json

import httpx
import pytest

from server.claude_events import TextDelta, ToolUse, TurnResult
from server.gemini_bridge import GeminiBridge, MissingKey, trim
from server.session_store import SessionStore


def sse(*chunks: dict) -> bytes:
    return "".join(f"data: {json.dumps(c, ensure_ascii=False)}\r\n\r\n" for c in chunks).encode()


def reply(*parts: dict) -> dict:
    return {"candidates": [{"content": {"role": "model", "parts": list(parts)}}]}


class FakeGemini:
    def __init__(self, *responses: bytes) -> None:
        self.responses = list(responses)
        self.bodies: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        return httpx.Response(200, content=self.responses.pop(0))


def make(tmp_path, fake, runner=None, key="k") -> GeminiBridge:
    prompt = tmp_path / "lider.md"
    prompt.write_text("Sen Cuba'sın.", encoding="utf-8")
    memory = tmp_path / "asistan"
    memory.mkdir()
    (memory / "gorevler.md").write_text("- [ ] süt al", encoding="utf-8")
    return GeminiBridge(
        SessionStore(tmp_path / "lider.json"), prompt, key, "gemini-test",
        memory_dir=memory, runner=runner or (lambda p, a: None),
        clock=lambda: datetime.datetime(2026, 11, 11, 9, 30),
        transport=httpx.MockTransport(fake),
    )


async def turn(bridge: GeminiBridge) -> list:
    events = []
    async for event in bridge.events():
        events.append(event)
        if isinstance(event, TurnResult):
            return events


async def test_streams_text_and_sends_memory_and_date(tmp_path):
    fake = FakeGemini(sse(reply({"text": "Günaydın "}), reply({"text": "efendim."})))
    bridge = make(tmp_path, fake)
    await bridge.send("merhaba")
    events = await turn(bridge)

    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Günaydın ", "efendim."]
    assert events[-1] == TurnResult("", is_error=False)
    system = fake.bodies[0]["systemInstruction"]["parts"][0]["text"]
    assert "Sen Cuba'sın." in system and "süt al" in system and "2026-11-11 09:30 Çarşamba" in system
    assert fake.bodies[0]["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 0
    await bridge.close()


async def test_runs_team_command_and_answers_with_result(tmp_path):
    calls = []

    async def runner(program, args):
        calls.append((program, args))
        return {"exit_code": 0, "output": "Plan kaydedildi"}

    signed = {"functionCall": {"name": "komut", "args": {"program": "ekip", "args": ["durum"]}},
              "thoughtSignature": "abc"}
    fake = FakeGemini(sse(reply(signed)), sse(reply({"text": "Ekip boşta."})))
    bridge = make(tmp_path, fake, runner)
    await bridge.send("ekip ne yapıyor")
    events = await turn(bridge)

    assert calls == [("ekip", ["durum"])]
    assert ToolUse("komut", "ekip durum") in events
    second = fake.bodies[1]["contents"]
    assert second[1] == {"role": "model", "parts": [signed]}  # the signature goes back untouched
    assert second[2]["parts"][0]["functionResponse"]["response"]["output"] == "Plan kaydedildi"
    await bridge.close()


async def test_writes_only_memory_files(tmp_path):
    write = {"functionCall": {"name": "dosya_yaz", "args": {"ad": "notlar.md", "icerik": "kahve sade"}}}
    escape = {"functionCall": {"name": "dosya_yaz", "args": {"ad": "../x.md", "icerik": "x"}}}
    fake = FakeGemini(sse(reply(write, escape)), sse(reply({"text": "Kaydettim."})))
    bridge = make(tmp_path, fake)
    await bridge.send("kahvemi sade içerim")
    await turn(bridge)

    assert (tmp_path / "asistan" / "notlar.md").read_text(encoding="utf-8") == "kahve sade"
    assert not (tmp_path / "x.md").exists()
    assert "error" in fake.bodies[1]["contents"][2]["parts"][1]["functionResponse"]["response"]
    await bridge.close()


async def test_history_survives_restart_and_new_session_clears_it(tmp_path):
    fake = FakeGemini(sse(reply({"text": "Tamam."})), sse(reply({"text": "Evet."})), sse(reply({"text": "?"})))
    bridge = make(tmp_path, fake)
    await bridge.send("bir")
    await turn(bridge)
    await bridge.close()

    again = make_again(tmp_path, fake)
    await again.send("iki")
    await turn(again)
    assert [c["parts"][0]["text"] for c in fake.bodies[1]["contents"]] == ["bir", "Tamam.", "iki"]

    await again.new_session()
    await again.send("üç")
    await turn(again)
    assert len(fake.bodies[2]["contents"]) == 1
    await again.close()


def make_again(tmp_path, fake) -> GeminiBridge:
    return GeminiBridge(
        SessionStore(tmp_path / "lider.json"), tmp_path / "lider.md", "k", "gemini-test",
        memory_dir=tmp_path / "asistan", transport=httpx.MockTransport(fake),
    )


async def test_api_error_ends_turn_with_message(tmp_path):
    bridge = make(tmp_path, lambda request: httpx.Response(429, text="quota"))
    await bridge.send("merhaba")
    result = (await turn(bridge))[-1]
    assert result.is_error and "429" in result.message
    await bridge.close()


async def test_interrupt_ends_turn(tmp_path):
    async def slow(request):
        await asyncio.sleep(10)

    bridge = make(tmp_path, slow)
    await bridge.send("uzun anlat")
    await asyncio.sleep(0.05)
    await bridge.interrupt()
    assert (await turn(bridge))[-1] == TurnResult("", is_error=False)
    await bridge.close()


async def test_missing_key_refuses_to_start(tmp_path):
    with pytest.raises(MissingKey):
        await make(tmp_path, FakeGemini(), key="").start()


def test_trim_starts_at_users_own_words():
    text = lambda role, t: {"role": role, "parts": [{"text": t}]}
    tool_reply = {"role": "user", "parts": [{"functionResponse": {}}]}
    contents = [text("user", "a"), {"role": "model", "parts": [{"functionCall": {}}]}, tool_reply,
                text("model", "b"), text("user", "c"), text("model", "d")]
    assert trim(contents, keep=4) == contents[4:]
