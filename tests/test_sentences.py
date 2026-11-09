from server.sentences import SentenceSplitter, speakable


def test_splits_streamed_chunks():
    s = SentenceSplitter()
    assert s.feed("Merhaba. Üç dosya") == ["Merhaba."]
    assert s.feed(" buldum! Sürüm 3.5 hazır") == ["Üç dosya buldum!"]
    assert s.flush() == ["Sürüm 3.5 hazır"]


def test_skips_code_block():
    s = SentenceSplitter()
    out = s.feed("Şunu çalıştır:\n```\nrm -rf x.\n```\nTamam.") + s.flush()
    assert out == ["Şunu çalıştır:", "Tamam."]


def test_code_fence_split_across_chunks():
    s = SentenceSplitter()
    out = s.feed("Bak:\n``") + s.feed("`\ngizli.\n`") + s.feed("``\nBitti.") + s.flush()
    assert out == ["Bak:", "Bitti."]


def test_flush_resets_state():
    s = SentenceSplitter()
    s.feed("```\nyarım")
    s.flush()
    assert s.feed("Yeni tur.\n") == ["Yeni tur."]


def test_speakable_strips_paths_and_code():
    assert speakable("Dosya `a.py` içinde, D:\\yazılım\\x.txt yolunda.") == "Dosya içinde, yolunda."


def test_speakable_strips_urls_and_markdown():
    assert speakable("## **Özet**: https://ornek.com adresine bak") == "Özet: adresine bak"
    assert speakable("- ilk madde") == "ilk madde"


def test_sentence_without_letters_is_dropped():
    s = SentenceSplitter()
    assert s.feed("`D:\\x` \n") == []
