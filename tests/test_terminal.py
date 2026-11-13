import json
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server.terminal import MORE_ON_SCREEN, PERMISSION_LINE, Terminal, hook_settings, powershell_command, spoken
from tests.test_app import TOKEN, FakeBridge, make_app, read_until
from tools.terminal_hook import last_reply


class FakePty:
    def __init__(self):
        self.written = []
        self.size = None
        self.output = ["PS D:\\> "]
        self.done = threading.Event()

    def isalive(self):
        return not self.done.is_set()

    def read(self, n):
        if self.output:
            return self.output.pop(0)
        self.done.wait()
        raise EOFError

    def write(self, data):
        self.written.append(data)

    def setwinsize(self, rows, cols):
        self.size = (rows, cols)

    def terminate(self, force=False):
        self.done.set()


@pytest.fixture
def pty():
    return FakePty()


@pytest.fixture
def terminal_client(tmp_path, pty):
    spawned = []

    def spawn(argv, cwd, env, dimensions):
        spawned.append(argv)
        return pty

    terminal = Terminal(["powershell.exe"], str(tmp_path), spawn=spawn)
    app = make_app(tmp_path, FakeBridge(), allowed_hosts=("127.0.0.1", "localhost", "testserver"),
                   terminal=terminal)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        client.spawned = spawned
        yield client


def test_spoken_reads_prose_only():
    text = "## Özet\n\nDosyayı düzelttim.\n\n```python\nprint(1)\n```\n| a | b |\n|---|---|\n- **Testler** geçti\n"
    assert spoken(text) == "Özet. Dosyayı düzelttim. Testler geçti."


def test_spoken_cuts_long_answers_at_a_sentence():
    text = "Bu bir cümle. " * 60
    said = spoken(text)
    assert said.endswith(MORE_ON_SCREEN) and len(said) < 450 and said.count("cümle.") > 5


def test_hook_settings_and_command(tmp_path):
    path = hook_settings("C:\\py.exe", tmp_path)
    hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]
    assert hooks["Stop"][0]["hooks"][0]["command"].endswith(" stop")
    assert hooks["Notification"][0]["matcher"] == "permission_prompt"
    init = powershell_command("C:\\claude.exe", path, "claude-opus-5-5")[-1]
    assert "--model 'claude-opus-5-5'" in init
    assert f"--settings '{path}'" in init and init.endswith("claude")


def test_last_reply_skips_tool_results(tmp_path):
    lines = [
        {"type": "user", "message": {"content": "eski soru"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "eski cevap"}]}},
        {"type": "user", "message": {"content": "yeni soru"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Bakıyorum."},
                                                       {"type": "tool_use", "name": "Read"}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "..."}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Bitti."}]}},
    ]
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join(json.dumps(l) for l in lines), encoding="utf-8")
    assert last_reply(str(transcript)) == "Bakıyorum.\nBitti."


def test_terminal_reply_is_spoken(terminal_client):
    with terminal_client.websocket_connect("/ws") as ws:
        r = terminal_client.post("/api/team/terminal", headers={"x-ekip-token": TOKEN},
                                 json={"kind": "stop", "text": "Kurdum. Testler geçti."})
        assert r.status_code == 200
        msgs = read_until(ws, "turn_end")
    assert [m["text"] for m in msgs if m["type"] == "sentence"] == ["Kurdum.", "Testler geçti."]


def test_permission_prompt_is_spoken(terminal_client):
    with terminal_client.websocket_connect("/ws") as ws:
        terminal_client.post("/api/team/terminal", headers={"x-ekip-token": TOKEN}, json={"kind": "permission"})
        msgs = read_until(ws, "turn_end")
    assert " ".join(m["text"] for m in msgs if m["type"] == "sentence") == PERMISSION_LINE


def test_terminal_reply_needs_token(terminal_client):
    r = terminal_client.post("/api/team/terminal", json={"kind": "stop", "text": "x"})
    assert r.status_code == 403


def test_terminal_socket_relays_both_ways(terminal_client, pty):
    with terminal_client.websocket_connect("/ws/terminal", headers={"origin": "http://127.0.0.1:8765"}) as ws:
        seen = ws.receive_text()
        if not seen:  # the replay may come before the first output
            seen = ws.receive_text()
        assert seen == "PS D:\\> "
        ws.send_json({"type": "input", "data": "claude\r"})
        ws.send_json({"type": "resize", "cols": 100, "rows": 40})
        ws.send_json({"type": "input", "data": ""})  # a round trip so the two above are handled
    assert pty.written[0] == "claude\r" and pty.size == (40, 100)
    assert terminal_client.spawned == [["powershell.exe"]]


def test_terminal_socket_from_another_site_is_refused(terminal_client, pty):
    with pytest.raises(WebSocketDisconnect):
        with terminal_client.websocket_connect("/ws/terminal", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_text()
    assert terminal_client.spawned == []


def test_crew_puts_subagents_at_desks_and_frees_them():
    from server.terminal import TerminalCrew

    clock = iter(range(100)).__next__
    crew = TerminalCrew(clock=lambda: 0)
    crew.prompt()
    crew.tool("Agent", {"description": "Testleri incele", "subagent_type": "Explore"}, "t1")
    crew.tool("Grep", {"pattern": "def main"}, agent="a1")
    crew.tool("Bash", {"command": "pytest -q"})
    agents = {a["id"]: a for a in crew.snapshot()["agents"]}
    assert agents["kidemli"]["name"] == "Explore" and agents["kidemli"]["activity"] == "Grep: def main"
    assert agents["lider"]["activity"] == "Bash: pytest -q"
    assert crew.snapshot()["phase"] == "working"

    crew.tool_done("Agent", "t1")
    assert {a["id"]: a for a in crew.snapshot()["agents"]}["kidemli"]["state"] == "idle"
    crew.permission()
    assert crew.snapshot()["question"]
    crew.stop()
    assert crew.snapshot()["phase"] == "idle" and not crew.snapshot()["question"]


def test_tool_events_reach_the_office_silently(terminal_client):
    with terminal_client.websocket_connect("/ws") as ws:
        terminal_client.post("/api/team/terminal", headers={"x-ekip-token": TOKEN},
                             json={"kind": "pre", "tool": "Bash", "input": {"command": "ls"}})
        msgs = read_until(ws, "chat")  # the greeting snapshots end with the chat
        while (msg := ws.receive_json())["type"] != "terminal_team":
            assert msg["type"] != "sentence"
    lead = next(a for a in msg["agents"] if a["id"] == "lider")
    assert lead["state"] == "working" and lead["activity"] == "Bash: ls"


def test_permission_is_granted_only_while_away(terminal_client):
    ask = lambda: terminal_client.post("/api/team/terminal", headers={"x-ekip-token": TOKEN},
                                       json={"kind": "permission_request"}).json()
    assert ask() == {}
    with terminal_client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "away", "on": True})
        while (msg := ws.receive_json())["type"] != "away" or not msg["on"]:
            pass
    assert ask() == {"behavior": "allow"}


def test_project_summary(terminal_client, tmp_path):
    (tmp_path / "README.md").write_text("# Deneme", encoding="utf-8")
    info = terminal_client.get("/api/project").json()
    assert info["readme"] == "# Deneme" and info["path"] == str(tmp_path)


def test_terminal_team_files(tmp_path):
    from server.config import DEFAULT_MODELS
    from server.prompts import write_terminal_team

    charter, plugin = write_terminal_team(tmp_path, DEFAULT_MODELS)
    text = charter.read_text(encoding="utf-8")
    assert "Sen Cuba'sın" in text and "`testci`" in text and "{{roster}}" not in text
    kidemli = (plugin / "agents" / "kidemli.md").read_text(encoding="utf-8")
    assert kidemli.startswith("---\nname: kidemli\n") and "model: opus" in kidemli
    assert "model: haiku" in (plugin / "agents" / "asistan.md").read_text(encoding="utf-8")
    settings = json.loads(hook_settings("py", tmp_path, charter).read_text(encoding="utf-8"))
    assert str(charter) in settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert f"--plugin-dir '{plugin}'" in powershell_command("c.exe", tmp_path, "", plugin)[-1]


def test_team_member_sits_at_its_own_desk():
    from server.terminal import TerminalCrew

    crew = TerminalCrew(clock=lambda: 0)
    crew.tool("Agent", {"description": "Testleri çalıştır", "subagent_type": "cuba-ekip:testci"}, "t1")
    testci = next(a for a in crew.snapshot()["agents"] if a["id"] == "testci")
    assert testci["state"] == "working" and testci["name"] == "Testçi"


def test_people_are_sent_around_the_office(terminal_client):
    auth = {"x-ekip-token": TOKEN}
    with terminal_client.websocket_connect("/ws") as ws:
        r = terminal_client.post("/api/team/move", headers=auth,
                                 json={"who": ["lider", "gelistirici", "cagan"], "where": "meeting"})
        assert r.status_code == 200
        while (msg := ws.receive_json())["type"] != "team" or not msg["places"]:
            pass
    assert msg["places"] == {"lider": "meeting", "gelistirici": "meeting", "cagan": "meeting"}
    terminal_client.post("/api/team/move", headers=auth, json={"who": ["gelistirici"], "where": ""})
    assert terminal_client.get("/api/team/places", headers=auth).json()["places"] == {"lider": "meeting", "cagan": "meeting"}
    bad = terminal_client.post("/api/team/move", headers=auth, json={"who": ["hacker"], "where": "meeting"})
    assert bad.status_code == 400


def test_background_member_keeps_working_until_it_stops():
    from server.terminal import TerminalCrew

    crew = TerminalCrew(clock=lambda: 0)
    crew.tool("Agent", {"description": "Pazar araştırması", "subagent_type": "cuba-ekip:pazarlama",
                        "run_in_background": "true"}, "t1")
    crew.tool_done("Agent", "t1", "Async agent launched successfully.")
    crew.stop()  # Cuba's turn ends while the member is still at work
    crew.tool("WebSearch", {"query": "Bagger Ersatzteile"}, agent="a9")
    desk = lambda: next(a for a in crew.snapshot()["agents"] if a["id"] == "pazarlama")
    assert desk()["state"] == "working" and desk()["activity"].startswith("WebSearch")
    assert crew.reports == []

    crew.subagent_done("a9", "cuba-ekip:pazarlama", "Müşteri bulundu.")
    assert desk()["state"] == "idle"
    assert crew.reports == [{"who": "pazarlama", "name": "Pazarlamacı", "text": "Müşteri bulundu."}]


def test_given_work_a_member_returns_to_the_desk(terminal_client):
    auth = {"x-ekip-token": TOKEN}
    terminal_client.post("/api/team/move", headers=auth, json={"who": ["testci"], "where": "sofa"})
    terminal_client.post("/api/team/terminal", headers=auth, json={
        "kind": "pre", "tool": "Agent", "use_id": "t1", "input": {"subagent_type": "cuba-ekip:testci"}})
    assert "testci" not in terminal_client.get("/api/team/places", headers=auth).json()["places"]


def test_project_summary_lists_team_papers(terminal_client, tmp_path):
    papers = tmp_path / "docs" / "ekip"
    papers.mkdir(parents=True)
    (papers / "2026-11-10-giris.md").write_text("## İstek\neski", encoding="utf-8")
    (papers / "2026-11-11-odeme.md").write_text("## İstek\nyeni", encoding="utf-8")
    docs = terminal_client.get("/api/project").json()["docs"]
    assert [d["name"] for d in docs] == ["2026-11-11-odeme", "2026-11-10-giris"]


async def test_moving_to_another_project_closes_claude_and_restarts_there(tmp_path):
    cwds, ptys = [], []

    def spawn(argv, cwd, env, dimensions):
        cwds.append(cwd)
        ptys.append(FakePty())
        return ptys[-1]

    terminal = Terminal(["powershell.exe"], str(tmp_path / "a"), spawn=spawn)
    terminal.start()
    assert not terminal.move_to(str(tmp_path / "a" / "."))  # the same folder: nothing happens
    assert terminal.alive
    assert terminal.move_to(str(tmp_path / "b"))
    assert not terminal.alive and terminal.cwd == str(tmp_path / "b")
    terminal.start()
    assert cwds == [str(tmp_path / "a"), str(tmp_path / "b")]
    terminal.close()


def test_each_project_has_its_own_terminal(tmp_path):
    from server.terminal import TerminalPool

    made = []
    pool = TerminalPool(lambda cwd: made.append(cwd) or Terminal(["x"], cwd))
    a = pool.get(str(tmp_path / "A"))
    assert pool.get(str(tmp_path / "a") + "\\") is a  # same folder, other spelling
    assert pool.get(str(tmp_path / "b")) is not a
    assert made == [str(tmp_path / "A"), str(tmp_path / "b")] and pool.alive() == []


def test_two_subagent_reports_bring_the_team_to_a_meeting(tmp_path, pty, monkeypatch):
    from server.terminal import TerminalPool

    lines = {"lines": [{"who": "gelistirici", "text": "Testçi, girişi denedin mi?"},
                       {"who": "testci", "text": "Denedim, geçti."}],
             "kararlar": ["Giriş tamam."], "gorevler": [{"kim": "testci", "is": "Çıkışı da dene."}]}

    async def ask(system, prompt, as_json):
        assert "Geliştirici:\nkodu yazdım" in prompt and "Testçi:\ntest ettim" in prompt
        return json.dumps(lines)

    monkeypatch.setattr("server.app.MEETING_PACE_S", 0)
    pool = TerminalPool(lambda cwd: Terminal(["x"], cwd, spawn=lambda *a, **k: pty))
    app = make_app(tmp_path, FakeBridge(), allowed_hosts=("127.0.0.1", "localhost", "testserver"),
                   terminals=pool, ask=ask)
    other = str(tmp_path / "baska")

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        def post(body):
            client.post("/api/team/terminal", json={"terminal": other, **body}, headers={"X-Ekip-Token": TOKEN})

        with client.websocket_connect("/ws") as ws:
            post({"kind": "prompt", "text": "giriş sayfası"})
            for role, use in (("gelistirici", "u1"), ("testci", "u2")):
                post({"kind": "pre", "tool": "Agent", "use_id": use, "input": {"subagent_type": f"cuba-ekip:{role}"}})
            post({"kind": "post", "tool": "Agent", "use_id": "u1", "result": "kodu yazdım"})
            post({"kind": "post", "tool": "Agent", "use_id": "u2", "result": "test ettim"})
            post({"kind": "stop", "text": "Bitti."})
            seen = read_until(ws, "meeting")
    meeting = seen[-1]
    assert meeting["project"] == other and meeting["decisions"] == ["Giriş tamam."]
    assert meeting["names"]["testci"] == "Testçi" and len(meeting["lines"]) == 2
    crews = [m for m in seen if m["type"] == "terminal_team" and m["project"] == other]
    assert any(m["phase"] == "review" for m in crews)
    assert crews[-1]["phase"] != "review" and crews[-1]["tasks"][0]["text"] == "Çıkışı da dene."
    # The open project's office never showed the other project's work.
    assert not any(m["agents"][0]["state"] == "working" for m in seen
                   if m["type"] == "terminal_team" and m["project"] == str(tmp_path))


def test_marketing_is_a_claude_subagent_that_reads_context(tmp_path):
    from server.config import DEFAULT_MODELS
    from server.prompts import write_terminal_team

    _, plugin = write_terminal_team(tmp_path, DEFAULT_MODELS)
    pazarlama = (plugin / "agents" / "pazarlama.md").read_text(encoding="utf-8")
    assert "model: sonnet" in pazarlama
    assert "model: haiku" in (plugin / "agents" / "sosyal.md").read_text(encoding="utf-8")
    assert "/asistan/cagan.md" in pazarlama and "{{asistan}}" not in pazarlama
    assert (plugin / "agents" / "gelistirici.md").exists()


def test_office_work_and_meeting_show_on_crew():
    from server.terminal import TerminalCrew

    crew = TerminalCrew(clock=lambda: 0)
    crew.office_work("icerik", "Yazıyor")
    icerik = next(a for a in crew.snapshot()["agents"] if a["id"] == "icerik")
    assert icerik["state"] == "working" and icerik["activity"] == "Yazıyor"
    crew.office_rest("icerik")
    crew.show_meeting({"members": ["icerik"], "speaker": "", "lines": [], "names": {}})
    assert crew.snapshot()["phase"] == "review"
    crew.show_meeting(None)
    assert crew.review is None


async def test_deliver_waits_for_claude_trusts_the_folder_and_confirms(tmp_path):
    pty = FakePty()
    pty.output = ["\x1b[1mDo you trust the files in this folder?\x1b[0m 1. Yes, proceed"]
    terminal = Terminal(["x"], str(tmp_path), spawn=lambda *a, **k: pty)

    def write(data):
        pty.written.append(data)
        if data == "\r" and len(pty.written) == 1:  # trust answered: Claude's input box comes up
            terminal._publish("\x1b[2m? for shortcuts\x1b[0m")
        elif data == "\r":
            terminal.prompts += 1  # the UserPromptSubmit hook heard it

    pty.write = write
    assert await terminal.deliver("pazar araştırması yap", heard_timeout=2)
    assert pty.written == ["\r", "pazar araştırması yap", "\r"]
    pty.done.set()


async def test_deliver_reports_when_claude_never_takes_it(tmp_path):
    pty = FakePty()
    pty.output = ["? for shortcuts"]
    terminal = Terminal(["x"], str(tmp_path), spawn=lambda *a, **k: pty)
    assert not await terminal.deliver("iş", heard_timeout=0.3)
    assert pty.written == ["iş", "\r", "\r"]  # one more Enter before giving up
    pty.done.set()


def test_terminal_runs_with_full_permissions(tmp_path):
    settings = json.loads(hook_settings("python", tmp_path).read_text(encoding="utf-8"))
    assert settings["permissions"]["defaultMode"] == "bypassPermissions"
    assert settings["skipDangerousModePermissionPrompt"] is True
