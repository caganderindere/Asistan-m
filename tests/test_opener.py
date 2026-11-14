import asyncio

from server import opener
from server.opener import Opener, find_document


def test_documents_are_found_by_their_words(tmp_path):
    (tmp_path / "asprubber").mkdir()
    report = tmp_path / "asprubber" / "firma-analizi.md"
    report.write_text("x", encoding="utf-8")
    assert find_document("asprubber firma analizi", tmp_path) == report
    assert find_document("yok", tmp_path) is None


def test_open_sends_each_kind_to_the_right_place(tmp_path, monkeypatch):
    opened, started = [], []
    (tmp_path / "sunum.pptx").write_bytes(b"x")

    async def video(query):
        return "https://www.youtube.com/watch?v=abcdefghijk"

    monkeypatch.setattr(opener, "first_video", video)
    tool = Opener(opened.append, started.append, tmp_path)
    run = asyncio.run
    assert run(tool.open("youtube", "Duman Bu Akşam"))["acildi"].endswith("abcdefghijk")
    assert run(tool.open("site", "balbalmedya.com"))["acildi"] == "https://balbalmedya.com"
    assert run(tool.open("site", "asp rubber"))["acildi"].startswith("https://www.google.com/search?q=")
    assert run(tool.open("dosya", "sunum"))["ok"] and started == [str(tmp_path / "sunum.pptx")]
    assert "error" in run(tool.open("dosya", "rapor"))
