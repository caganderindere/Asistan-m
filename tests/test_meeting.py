import json

from server.meeting import MAX_LINES, hold_meeting

MEMBERS = [{"id": "kidemli", "name": "Kıdemli", "duty": "mimari"}, {"id": "testci", "name": "Testçi", "duty": "test"}]
LEAD = {"id": "lider", "name": "Cuba", "duty": "lider"}


def answer(data):
    async def ask(system, prompt, as_json):
        assert as_json and "Kıdemli" in system and "Cuba" in system
        return json.dumps(data)

    return ask


async def test_meeting_keeps_known_speakers_and_their_proposals():
    result = await hold_meeting(answer({
        "lines": [{"who": "kidemli", "text": "Testçi, oturum testini atlamışsın."},
                  {"who": "testci", "text": "Haklısın Kıdemli, ekliyorum."},
                  {"who": "biri", "text": "Uydurma kişi."},
                  {"who": "lider", "text": "Anlaştık: oturum testi eklenecek."}],
        "kararlar": ["Oturum testi eklenecek.", " "],
        "gorevler": [{"kim": "testci", "is": "Oturum testini yaz."}, {"kim": "yok", "is": "x"}],
    }), MEMBERS, ["Kıdemli: kod", "Testçi: test"], LEAD)
    assert [line["who"] for line in result["lines"]] == ["kidemli", "testci", "lider"]
    assert result["decisions"] == ["Oturum testi eklenecek."]
    assert result["tasks"] == [{"to": "testci", "text": "Oturum testini yaz."}]


async def test_a_long_meeting_is_cut_and_a_broken_one_is_none():
    many = {"lines": [{"who": "kidemli", "text": f"söz {i}"} for i in range(30)]}
    assert len((await hold_meeting(answer(many), MEMBERS, ["r"], LEAD))["lines"]) == MAX_LINES
    assert await hold_meeting(answer({"lines": []}), MEMBERS, ["r"], LEAD) is None

    async def broken(*_):
        return "not json"

    assert await hold_meeting(broken, MEMBERS, ["r"], LEAD) is None
