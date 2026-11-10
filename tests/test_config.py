from server.config import load_config


def test_defaults_when_missing(tmp_path):
    c = load_config(tmp_path / "config.json")
    assert (c.port, c.workdir, c.voice, c.whisper_model) == (8765, "D:\\", "tr-TR-AhmetNeural", "large-v3-turbo")
    assert "Çağan" in c.vocabulary


def test_overrides_and_ignores_unknown(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"voice": "tr-TR-EmelNeural", "vocabulary": ["Nevka"], "junk": 1}', encoding="utf-8")
    c = load_config(p)
    assert c.voice == "tr-TR-EmelNeural" and c.vocabulary == ("Nevka",) and c.port == 8765
