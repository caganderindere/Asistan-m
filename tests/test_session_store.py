from server.session_store import SessionStore


def test_roundtrip_and_clear(tmp_path):
    s = SessionStore(tmp_path / "data" / "session.json")
    assert s.load() is None
    s.save("abc-123")
    assert s.load() == "abc-123"
    s.clear()
    assert s.load() is None


def test_corrupt_file_is_none(tmp_path):
    p = tmp_path / "session.json"
    p.write_text("{bozuk", encoding="utf-8")
    assert SessionStore(p).load() is None
