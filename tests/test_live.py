import asyncio
import base64
import json

from server.live import LiveHub, find_project, live_prompt


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


PROJECTS = {"current": r"D:\ClaudeSes", "projects": [
    {"name": "ClaudeSes", "path": r"D:\ClaudeSes"},
    {"name": "balbalmedya", "path": r"D:\web\balbalmedya"},
    {"name": "balbal-eski", "path": r"D:\web\balbal-eski"},
]}


def make_hub(google, **kwargs):
    handed, pressed = [], []

    async def hand_over(text, folder):
        handed.append((folder, text))

    hub = LiveHub("key", "gemini-live-test", "Charon", hand_over, pressed.append,
                  connect=lambda url, **kw: google, projects=lambda: PROJECTS, **kwargs)
    hub.handed, hub.pressed = handed, pressed
    return hub


async def wait_for(condition, timeout=2.0):
    for _ in range(int(timeout / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never held")


async def test_setup_carries_cuba_voice_tools_and_prompt(tmp_path):
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
    assert "Sen Cuba'sın" in setup["systemInstruction"]["parts"][0]["text"]
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
    assert {"type": "cuba", "text": "Buyurun efendim."} in browser.events
    assert google.sent[1]["realtimeInput"]["audio"] == {"data": base64.b64encode(b"\x10\x00").decode(),
                                                      "mimeType": "audio/pcm;rate=16000"}
    assert google.sent[2] == {"realtimeInput": {"text": "Saat kaç?"}}
    browser.leave()
    await asyncio.wait_for(serving, 2)


async def test_work_goes_to_the_terminal_and_tools_answer(tmp_path):
    google = FakeGoogle([{"toolCall": {"functionCalls": [
        {"id": "1", "name": "terminale_ver", "args": {"proje": "BalBalMedya", "talimat": "Giriş sayfasını yap."}},
        {"id": "2", "name": "terminal_tus", "args": {"tus": "evet"}},
        {"id": "3", "name": "dosya_yaz", "args": {"ad": "notlar.md", "icerik": "kahve sade"}},
        {"id": "4", "name": "dosya_yaz", "args": {"ad": "../x.md", "icerik": "x"}},
        {"id": "5", "name": "terminale_ver", "args": {"proje": "balbal", "talimat": "Hangisi?"}},
    ]}}])
    hub = make_hub(google, memory_dir=tmp_path)
    browser = FakeBrowser()
    serving = asyncio.create_task(hub.serve(browser))
    await wait_for(lambda: any("toolResponse" in m for m in google.sent))
    replies = next(m for m in google.sent if "toolResponse" in m)["toolResponse"]["functionResponses"]
    assert [r["id"] for r in replies] == ["1", "2", "3", "4", "5"]
    assert replies[0]["response"]["ok"] and "error" in replies[3]["response"]
    # The handover says nothing exists yet, so Cuba does not claim a report or a document.
    assert "Henüz hiçbir şey oluşmadı" in replies[0]["response"]["not"]
    # Two projects answer to "balbal": Cuba is told to ask, nothing is handed over.
    assert "Çağan'a sor" in replies[4]["response"]["error"]
    assert hub.handed == [(r"D:\web\balbalmedya", "Giriş sayfasını yap.")] and hub.pressed == ["\r"]
    assert (tmp_path / "notlar.md").read_text(encoding="utf-8") == "kahve sade"
    assert any(e["type"] == "tool" and e["name"] == "terminale_ver" for e in browser.events)
    browser.leave()
    await asyncio.wait_for(serving, 2)


async def test_team_report_is_told_to_cuba(tmp_path):
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


def test_prompt_lists_projects_with_the_open_one_marked(tmp_path):
    text = live_prompt(tmp_path, projects=PROJECTS)
    assert "- ClaudeSes: D:\\ClaudeSes (şu an açık)" in text and "- balbalmedya: D:\\web\\balbalmedya\n" in text


def test_projects_are_found_by_path_name_or_the_one_name_containing_it():
    assert find_project(PROJECTS, "d:\\web\\balbalmedya\\") == r"D:\web\balbalmedya"
    assert find_project(PROJECTS, "claudeses") == r"D:\ClaudeSes"
    assert find_project(PROJECTS, "eski") == r"D:\web\balbal-eski"
    assert find_project(PROJECTS, "balbal") is None and find_project(PROJECTS, "") is None


async def test_marketing_work_goes_to_the_terminal_subagent(tmp_path):
    from server.live import CubaTools

    handed: list[tuple[str, str]] = []

    async def hand_over(text: str, folder: str) -> None:
        handed.append((text, folder))

    async def press(*_):
        return None

    tools = CubaTools(hand_over, press, tmp_path, projects=lambda: {"projects": [{"name": "site", "path": "D:/site"}]})
    result = await tools.run("ekibe_ver", {"kim": "pazarlama", "proje": "site", "talimat": "balbalmedya.com'u analiz et"})
    assert result["ok"]
    assert handed[0][1] == "D:/site"
    assert "cuba-ekip:pazarlama" in handed[0][0] and "balbalmedya.com" in handed[0][0]


async def test_research_writes_the_document_before_cuba_hears_of_it(tmp_path, monkeypatch):
    from server import live
    from server.live import CubaTools
    monkeypatch.setattr(live, "doc_folder", lambda folder: tmp_path / "belgeler")

    async def nothing(*_):
        return None

    async def research(topic):
        return {"cevap": "Özet: üç rakip var.", "adresler": [{"baslik": "a.com", "adres": "https://a.com"}]}

    told, page = [], []

    async def tell(text):
        told.append(text)

    tools = CubaTools(nothing, nothing, tmp_path, projects=lambda: {"projects": [{"name": "site", "path": str(tmp_path)}]},
                      research=research, tell=tell, notify=page.append)
    result = await tools.run("arastir", {"konu": "Çiçekçi rakipleri", "proje": "site"})
    assert result["ok"] and "henüz belge yok" in result["not"]
    assert page[0] == {"type": "job", "project": tmp_path.name, "state": "working", "text": "Çiçekçi rakipleri"}
    for _ in range(50):
        if told:
            break
        await asyncio.sleep(0.01)
    [doc] = list((tmp_path / "belgeler").glob("arastirma-*-cicekci-rakipleri.md"))
    text = doc.read_text(encoding="utf-8")
    assert text.startswith("# Çiçekçi rakipleri") and "[a.com](https://a.com)" in text
    assert "[ARAŞTIRMA BİTTİ" in told[0] and f"Belge: {doc}" in told[0]
    assert page[1]["state"] == "done" and page[1]["docs"][0]["ok"]


async def test_failed_research_says_there_is_no_document(tmp_path):
    from server.live import CubaTools

    async def nothing(*_):
        return None

    async def research(topic):
        return {"error": "Arama yapılamadı (ConnectError)."}

    told = []

    async def tell(text):
        told.append(text)

    tools = CubaTools(nothing, nothing, tmp_path, projects=lambda: {"projects": [{"name": "site", "path": str(tmp_path)}]},
                      research=research, tell=tell)
    await tools.run("arastir", {"konu": "x", "proje": "site"})
    for _ in range(50):
        if told:
            break
        await asyncio.sleep(0.01)
    assert "[ARAŞTIRMA OLMADI" in told[0] and "Belge yok" in told[0]
    assert not (tmp_path / "pazarlama").exists()


def test_noise_lines_are_foreign_scripts_only():
    from server.stt import is_noise
    assert is_noise("요요, 소리 높아져 기봐.")
    assert is_noise("麻酔 、 麻酔 に 関し て")
    assert not is_noise("ASP Rubber için iki gönderi lazım.")
    assert not is_noise("Yo, I'll get it.")


def test_names_line_lists_topics_and_projects(tmp_path):
    from server.live import names_line
    from server.memory import learn
    learn(tmp_path, "ASP Rubber", "Kauçuk parça üretir.")
    line = names_line(tmp_path, {"projects": [{"name": "asprubberT", "path": "D:/a"}]})
    assert line.startswith("Cuba, Çağan, ASP Rubber, asprubberT.")


def test_research_goes_to_the_desktop_folder(tmp_path):
    import datetime
    from server.live import research_path
    path = research_path("D:/projeler/magaza", "Çiçek fiyatları", datetime.date(2026, 11, 15))
    assert path.parent.name == "magaza" and path.parent.parent.name == "belgeler"
    assert path.name == "arastirma-2026-11-15-cicek-fiyatlari.md"
