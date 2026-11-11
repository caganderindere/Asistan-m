import json

from server.supervisor import Supervisor


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


async def test_away_daim_answers_claude_in_the_users_place(tmp_path):
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
