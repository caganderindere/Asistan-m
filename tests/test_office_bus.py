import datetime
import json

from server.office_bus import Message, OfficeBus

NOW = datetime.datetime(2026, 11, 13, 15, 30)


def bus(tmp_path) -> OfficeBus:
    return OfficeBus(tmp_path, clock=lambda: NOW)


def test_post_logs_and_notifies(tmp_path):
    office = bus(tmp_path)
    heard = []
    office.subscribe(heard.append)
    sent = office.post(Message("pazarlama", "icerik", "Ton ne olsun?"))
    assert sent.time == "15:30" and heard == [sent]
    lines = (tmp_path / "2026-11-13.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"sender": "pazarlama", "to": "icerik", "text": "Ton ne olsun?",
                                    "channel": "birebir", "time": "15:30"}


def test_recent_filters_by_person(tmp_path):
    office = bus(tmp_path)
    office.post(Message("pazarlama", "icerik", "bir"))
    office.post(Message("sosyal", "icerik", "iki"))
    office.post(Message("icerik", "pazarlama", "üç"))
    assert [m.text for m in office.recent("pazarlama")] == ["bir", "üç"]


def test_listener_error_does_not_stop_post(tmp_path):
    office = bus(tmp_path)
    heard = []

    def broken(message):
        raise RuntimeError("tarayıcı yok")

    office.subscribe(broken)
    office.subscribe(heard.append)
    sent = office.post(Message("sosyal", "pazarlama", "selam"))
    assert heard == [sent]
