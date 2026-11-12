import json

import pytest

from server.prompts import write_terminal_team
from server.roster import MAX_HIRES, Roster, slug
from server.terminal import TerminalCrew


def test_hiring_gives_an_id_a_free_voice_and_survives_a_restart(tmp_path):
    roster = Roster(tmp_path / "ekip.json")
    designer = roster.hire("Tasarımcı", "arayüz ve görsel tasarım", "opus")
    tester = roster.hire("Güvenlikçi", "güvenlik açıklarını arar", "yanlis")
    assert (designer.id, designer.model, tester.id, tester.model) == ("tasarimci", "opus", "guvenlikci", "sonnet")
    assert designer.voice != tester.voice
    assert [m.id for m in Roster(tmp_path / "ekip.json").hires] == ["tasarimci", "guvenlikci"]
    assert roster.find("TASARIMCI") == designer
    with pytest.raises(ValueError):
        roster.hire("Tasarımcı", "yine")
    with pytest.raises(ValueError):
        roster.fire("Testçi")  # the founders stay
    roster.fire("tasarımcı")
    assert [m.id for m in roster.hires] == ["guvenlikci"]


def test_the_office_has_room_for_four_hires(tmp_path):
    roster = Roster(tmp_path / "ekip.json")
    for i in range(MAX_HIRES):
        roster.hire(f"Uzman {i}", "iş")
    with pytest.raises(ValueError, match="boş masa"):
        roster.hire("Fazla", "iş")


def test_hires_become_subagents_and_leavers_do_not_stay(tmp_path):
    roster = Roster(tmp_path / "ekip.json")
    roster.hire("Tasarımcı", "arayüz tasarımı", "haiku")
    charter, plugin = write_terminal_team(tmp_path / "t", {}, roster.hires)
    agent = (plugin / "agents" / "tasarimci.md").read_text(encoding="utf-8")
    assert "name: tasarimci" in agent and "model: haiku" in agent and "arayüz tasarımı" in agent
    assert "`tasarimci`: Tasarımcı" in charter.read_text(encoding="utf-8")
    roster.fire("Tasarımcı")
    write_terminal_team(tmp_path / "t", {}, roster.hires)
    assert not (plugin / "agents" / "tasarimci.md").exists() and (plugin / "agents" / "testci.md").exists()


def test_a_hire_gets_a_desk_and_code_floats_over_it():
    crew = TerminalCrew(names=lambda: {"testci": "Testçi", "tasarimci": "Tasarımcı"})
    crew.tool("Agent", {"subagent_type": "cuba-ekip:tasarimci", "description": "Logo"}, "u1")
    crew.tool("Edit", {"file_path": r"D:\p\logo.svg", "new_string": "<svg>\n<circle/>\n</svg>"}, agent="a1")
    desks = {a["id"]: a for a in crew.snapshot()["agents"]}
    assert desks["tasarimci"]["name"] == "Tasarımcı" and desks["tasarimci"]["state"] == "working"
    assert desks["tasarimci"]["code"] == "<svg>\n<circle/>\n</svg>" and desks["tasarimci"]["file"] == "logo.svg"
    assert desks["lider"]["name"] == "Cuba"
    crew.tool_done("Agent", "u1", "Logo hazır.")
    desks = {a["id"]: a for a in crew.snapshot()["agents"]}
    assert desks["tasarimci"]["code"] == "" and crew.reports == [{"who": "tasarimci", "name": "Tasarımcı", "text": "Logo hazır."}]


def test_slug_reads_turkish():
    assert slug("Veri Bilimci Şükrü") == "veri-bilimci-sukru"
    assert json.dumps(slug("İçerik")) == '"icerik"'
