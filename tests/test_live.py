import asyncio
import base64
import json

from server.live import LiveHub, live_prompt


class FakeGoogle:
    """A Live session: answers setup, then replays *script* and waits."""

    def __init__(self, script):
        self.script = script
        self.sent = []
        self.closed = asyncio.Event()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        return json.dumps({"setupComplete": {}})

    def __aiter__(self):
        return self._messages()

    async def _messages(self):
        for message in self.script:
            yield json.dumps(message)
        await self.closed.wait()


class FakeBrowser:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.audio = []
        self.events = []

    async def receive(self):
        return await self.incoming.get()

    async def send_bytes(self, data):
        self.audio.append(data)

    async def send_json(self, data):
        self.events.append(data)

    async def close(self):
        pass

    def leave(self):
        self.incoming.put_nowait({"type": "websocket.disconnect"})


def make_hub(google, **kwargs):
    handed, pressed = [], []

    async def hand_over(text):
        handed.append(text)

    hub = LiveHub("key", "gemini-live-test", "Charon", hand_over, pressed.append,
                  connect=lambda url, **kw: google, **kwargs)
    hub.handed, hub.pressed = handed, pressed
    return hub


async def wait_for(condition, timeout=2.0):
    for _ in range(int(timeout / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never held")


async def test_setup_carries_daim_voice_tools_and_prompt(tmp_path):
    google = FakeGoogle([])
    hub = make_hub(google, memory_dir=tmp_path)
    browser = FakeBrowser()
    serving = asyncio.create_task(hub.serve(browser))
    await wait_for(lambda: {"type": "ready"} in browser.events)
    setup = google.sent[0]["setup"]
    assert setup["model"] == "models/gemini-live-test"
    assert setup["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Charon"
    names = [f["name"] for f in setup["tools"][0]["functionDeclarations"]]
    assert {"komut", "dosya_yaz", "terminale_ver", "terminal_tus"} <= set(names)
    assert "Sen Daim'sin" in setup["systemInstruction"]["parts"][0]["text"]
    assert hub.active
    browser.leave()
    await asyncio.wait_for(serving, 2)
    assert not hub.active


async def test_audio_and_words_flow_both_ways(tmp_path):
    pcm = b"\x01\x00\x02\x00"
    google = FakeGoogle([
        {"serverContent": {"inputTranscription": {"text": "Merhaba"}}},
        {"serverContent": {"modelTurn": {"parts": [{"inlineData": {
            "mimeType": "audio/pcm;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}},
        {"serverContent": {"outputTranscription": {"text": "Buyurun efendim."}}},
        {"serverContent": {"turnComplete": True}},
    ])
    hub = make_hub(google, memory_dir=tmp_path)
    browser = FakeBrowser()
    serving = asyncio.create_task(hub.serve(browser))
    browser.incoming.put_nowait({"type": "websocket.receive", "bytes": b"\x10\x00"})
    browser.incoming.put_nowait({"type": "websocket.receive", "text": json.dumps({"type": "text", "text": "Saat kaç?"})})
    await wait_for(lambda: {"type": "turn_complete"} in browser.events and len(google.sent) >= 3)
    assert browser.audio == [pcm]
    assert {"type": "user", "text": "Merhaba"} in browser.events
    assert {"type": "daim", "text": "Buyurun efendim."} in browser.events
    assert google.sent[1]["realtimeInput"]["audio"] == {"data": base64.b64encode(b"\x10\x00").decode(),
                                                      "mimeType": "audio/pcm;rate=16000"}
    assert google.sent[2] == {"realtimeInput": {"text": "Saat kaç?"}}
    browser.leave()
    await asyncio.wait_for(serving, 2)


async def test_work_goes_to_the_terminal_and_tools_answer(tmp_path):
    google = FakeGoogle([{"toolCall": {"functionCalls": [
        {"id": "1", "name": "terminale_ver", "args": {"talimat": "Giriş sayfasını yap."}},
        {"id": "2", "name": "terminal_tus", "args": {"tus": "evet"}},
        {"id": "3", "name": "dosya_yaz", "args": {"ad": "notlar.md", "icerik": "kahve sade"}},
        {"id": "4", "name": "dosya_yaz", "args": {"ad": "../x.md", "icerik": "x"}},
    ]}}])
    hub = make_hub(google, memory_dir=tmp_path)
    browser = FakeBrowser()
    serving = asyncio.create_task(hub.serve(browser))
    await wait_for(lambda: any("toolResponse" in m for m in google.sent))
    replies = next(m for m in google.sent if "toolResponse" in m)["toolResponse"]["functionResponses"]
    assert [r["id"] for r in replies] == ["1", "2", "3", "4"]
    assert replies[0]["response"]["ok"] and "error" in replies[3]["response"]
    assert hub.handed == ["Giriş sayfasını yap."] and hub.pressed == ["\r"]
    assert (tmp_path / "notlar.md").read_text(encoding="utf-8") == "kahve sade"
    assert any(e["type"] == "tool" and e["name"] == "terminale_ver" for e in browser.events)
    browser.leave()
    await asyncio.wait_for(serving, 2)


async def test_team_report_is_told_to_daim(tmp_path):
    google = FakeGoogle([])
    hub = make_hub(google, memory_dir=tmp_path)
    browser = FakeBrowser()
    serving = asyncio.create_task(hub.serve(browser))
    await wait_for(lambda: hub.active)
    await hub.tell("[EKİP RAPORU] Bitti.")
    assert google.sent[-1] == {"clientContent": {
        "turns": [{"role": "user", "parts": [{"text": "[EKİP RAPORU] Bitti."}]}], "turnComplete": True}}
    browser.leave()
    await asyncio.wait_for(serving, 2)


async def test_session_resumes_after_go_away(tmp_path):
    first = FakeGoogle([{"sessionResumptionUpdate": {"newHandle": "h1", "resumable": True}}, {"goAway": {}}])
    second = FakeGoogle([])
    sessions = iter([first, second])
    hub = LiveHub("key", "m", "Charon", None, None, connect=lambda url, **kw: next(sessions), memory_dir=tmp_path)
    browser = FakeBrowser()
    serving = asyncio.create_task(hub.serve(browser))
    await wait_for(lambda: second.sent)
    assert second.sent[0]["setup"]["sessionResumption"] == {"handle": "h1"}
    browser.leave()
    await asyncio.wait_for(serving, 2)


def test_prompt_has_memory_and_date(tmp_path):
    (tmp_path / "takvim.md").write_text("## 2026-11-11\n10:00 — diş", encoding="utf-8")
    text = live_prompt(tmp_path)
    assert "10:00 — diş" in text and "Şu an:" in text and "terminale_ver" in text
