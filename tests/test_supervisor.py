import json

from server.supervisor import Supervisor, check_documents, documents_note, for_live, is_brief


def fake_ask(*answers):
    asked = []

    async def ask(system, prompt, as_json):
        asked.append((system, prompt, as_json))
        return answers[len(asked) - 1]

    ask.asked = asked
    return ask


async def test_present_user_hears_a_short_summary(tmp_path):
    ask = fake_ask("Ekip giriş sayfasını bitirdi, testler geçti. Ayrıntılar terminalde.")
    boss = Supervisor(ask, tmp_path / "out.json")
    answer = await boss.on_stop("## Rapor\n" + "Bir satır daha.\n" * 8)
    assert answer == {"speak": "Ekip giriş sayfasını bitirdi, testler geçti. Ayrıntılar terminalde."}
    assert boss.outputs[-1]["away"] is False and ask.asked[0][2] is False


async def test_summary_falls_back_without_gemini(tmp_path):
    boss = Supervisor(None, tmp_path / "out.json")
    assert (await boss.on_stop("Kurdum. Testler geçti."))["speak"] == "Kurdum. Testler geçti."


async def test_away_cuba_answers_claude_in_the_users_place(tmp_path):
    ask = fake_ask(json.dumps({"bitti": False, "talimat": "A seçeneğiyle devam et.", "ozet": "Ekip A'yı seçti."}))
    boss = Supervisor(ask, tmp_path / "out.json")
    boss.note_prompt("Giriş sayfasını yap")
    boss.set_away(True)
    assert await boss.on_stop("A mı B mi yapayım?") == {"continue_with": "A seçeneğiyle devam et."}
    assert "Giriş sayfasını yap" in ask.asked[0][0] and ask.asked[0][2] is True
    assert boss.turns == 1 and boss.outputs[-1]["summary"] == "Ekip A'yı seçti."


async def test_away_stops_when_done_and_at_the_limit(tmp_path):
    done = json.dumps({"bitti": True, "talimat": "", "ozet": "Bitti."})
    boss = Supervisor(fake_ask(done), tmp_path / "out.json", max_turns=1)
    boss.set_away(True)
    assert await boss.on_stop("Hepsi tamam.") == {}
    assert boss.outputs[-1]["done"] is True

    more = json.dumps({"bitti": False, "talimat": "devam", "ozet": "."})
    boss = Supervisor(fake_ask(more, more), tmp_path / "out2.json", max_turns=1)
    boss.set_away(True)
    assert await boss.on_stop("x") == {"continue_with": "devam"}
    assert await boss.on_stop("y") == {}
    assert "sınır" in boss.outputs[-1]["summary"]


async def test_outputs_survive_restart(tmp_path):
    report = "Rapor.\n" * 6
    await Supervisor(None, tmp_path / "out.json").on_stop(report)
    assert Supervisor(None, tmp_path / "out.json").outputs[0]["report"] == report


async def test_a_short_answer_is_said_as_written(tmp_path):
    ask = fake_ask("Testler geçemedi, onayınızı bekliyorlar.")  # what Gemini once made up
    boss = Supervisor(ask, tmp_path / "out.json")
    said = await boss.on_stop("Ekibi dinlenme alanına gönderdim efendim. Ben toplantı odasında, sizin yanınızdayım.")
    assert said == {"speak": "Ekibi dinlenme alanına gönderdim efendim. Ben toplantı odasında, sizin yanınızdayım."}
    assert ask.asked == [] and boss.outputs == []


async def test_a_short_report_naming_a_document_is_kept(tmp_path):
    boss = Supervisor(None, tmp_path / "out.json")
    boss.note_report("Belge: pazarlama/rakip-analizi.md\nÜç rakip incelendi.")
    boss.note_report("Tamam patron.")
    assert len(boss.outputs) == 1 and "rakip-analizi.md" in boss.outputs[0]["report"]
    assert is_brief("Tamam patron.") and not is_brief("Belge: docs/ekip/2026-11-14-arastirma.md")


def test_cuba_hears_a_long_reports_opening_and_end():
    report = "Belge: docs/ekip/x.md\n" + "orta " * 2000 + "SON"
    told = for_live(report)
    assert told.startswith("Belge: docs/ekip/x.md") and told.endswith("SON") and len(told) < 4100
    assert for_live("kısa") == "kısa"


def test_named_documents_are_checked_on_disk(tmp_path):
    (tmp_path / "pazarlama").mkdir()
    (tmp_path / "pazarlama" / "var.md").write_text("x" * 2048, encoding="utf-8")
    report = "Belge: `pazarlama/var.md`\nBir şey yapıldı.\n- Belge: docs/ekip/yok.md"
    docs = check_documents(report, tmp_path)
    assert [(d["name"], d["ok"]) for d in docs] == [("pazarlama/var.md", True), ("docs/ekip/yok.md", False)]
    note = documents_note(docs)
    assert "pazarlama/var.md: var (2.0 KB)" in note and "docs/ekip/yok.md: YOK" in note
    assert documents_note(check_documents("Belgesiz rapor.", tmp_path)) == ""
