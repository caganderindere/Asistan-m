import datetime
import json

from server.memory import SECTIONS, ConversationLog, Diary, add_facts, blank_profile, ensure_profile


def test_facts_go_under_their_section_once(tmp_path):
    profile = tmp_path / "cagan.md"
    profile.write_text(blank_profile(), encoding="utf-8")
    added = add_facts(profile, [
        {"bolum": "Tercihler", "bilgi": "Kahveyi sade içer."},
        {"bolum": "Tercihler", "bilgi": "Kısa cevap sever."},
        {"bolum": "Projeler", "bilgi": "BalBal Medya önemli."},
        {"bolum": "Tercihler", "bilgi": "kahveyi sade içer."},  # already known
        {"bolum": "Uydurma", "bilgi": "İstanbul'da yaşar."},  # unknown section: Kimlik
    ])
    text = profile.read_text(encoding="utf-8")
    assert added == ["Kahveyi sade içer.", "Kısa cevap sever.", "BalBal Medya önemli.", "İstanbul'da yaşar."]
    prefs = text.split("## Tercihler\n")[1].split("\n## ")[0]
    assert prefs.strip().splitlines() == ["- Kahveyi sade içer.", "- Kısa cevap sever."]
    assert "## Projeler\n- BalBal Medya önemli.\n" in text
    assert "## Kimlik\n- İstanbul'da yaşar.\n" in text
    assert all(f"## {s}" in text for s in SECTIONS)


def test_an_old_notebook_gets_sections_and_keeps_its_lines(tmp_path):
    profile = tmp_path / "cagan.md"
    profile.write_text("# Çağan\n\n- Token harcamasına duyarlı.\n", encoding="utf-8")
    ensure_profile(profile)
    text = profile.read_text(encoding="utf-8")
    assert "## Kimlik\n- Token harcamasına duyarlı.\n" in text and "## Hedefler" in text
    ensure_profile(profile)
    assert profile.read_text(encoding="utf-8") == text


async def test_diary_is_written_from_the_day_and_teaches_cuba(tmp_path):
    day = datetime.datetime(2026, 11, 11, 9, 30)
    log = ConversationLog(tmp_path / "talk", clock=lambda: day)
    log.add("Çağan", "Bundan sonra   bana kısa cevap ver.")
    log.add("Cuba", "Peki efendim.")
    asked = {}

    async def ask(system, prompt, as_json):
        asked["system"], asked["prompt"] = system, prompt
        return json.dumps({"gunluk": "- Kısa cevap istedi.", "ogrenilenler": [{"bolum": "Tercihler", "bilgi": "Kısa cevap ister."}]})

    diary = Diary(tmp_path / "asistan", log, ask)
    assert diary.missing("2026-11-12") == ["2026-11-11"]
    written = await diary.write("2026-11-11", [{"time": "2026-11-11 10:00", "project": "ClaudeSes", "summary": "Testler geçti."}])
    assert written == {"page": "- Kısa cevap istedi.", "learned": ["Kısa cevap ister."]}
    assert "09:30 Çağan: Bundan sonra bana kısa cevap ver." in asked["prompt"] and "Testler geçti." in asked["prompt"]
    assert diary.missing("2026-11-12") == []
    assert diary.latest("2026-11-12").startswith("2026-11-11")
    assert diary.latest("2026-11-11") == ""
    assert "- Kısa cevap ister." in (tmp_path / "asistan" / "cagan.md").read_text(encoding="utf-8")


async def test_a_quiet_day_gets_no_page(tmp_path):
    async def ask(*_):
        raise AssertionError("nothing to write about")

    diary = Diary(tmp_path, ConversationLog(tmp_path / "talk"), ask)
    assert await diary.write("2026-11-11", []) is None
