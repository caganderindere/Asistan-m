import datetime
import json
import os
import time

from server.usage import ClaudeMeter, GeminiMeter


def entry(msg_id, request, output, when=None):
    when = when or datetime.datetime.now(datetime.timezone.utc)
    return json.dumps({
        "type": "assistant", "requestId": request, "timestamp": when.isoformat().replace("+00:00", "Z"),
        "message": {"id": msg_id, "usage": {"input_tokens": 10, "output_tokens": output,
                                            "cache_read_input_tokens": 100, "cache_creation_input_tokens": 5}},
    }) + "\n"


def test_claude_meter_counts_today_once_per_reply_and_reads_only_what_is_new(tmp_path):
    session = tmp_path / "proj" / "a.jsonl"
    session.parent.mkdir()
    yesterday = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)
    session.write_text(
        entry("m1", "r1", 7) + entry("m1", "r1", 7)  # a streamed reply written twice
        + entry("m0", "r0", 50, yesterday) + '{"type": "user"}\n',
        encoding="utf-8",
    )
    meter = ClaudeMeter(tmp_path)
    assert meter.today() == {"input": 10, "output": 7, "cache": 105}
    with session.open("a", encoding="utf-8") as f:
        f.write(entry("m2", "r2", 3) + '{"type": "assistant", "message": {"id": "half')  # still being written
    assert meter.today() == {"input": 20, "output": 10, "cache": 210}


def test_old_session_files_are_not_read(tmp_path):
    old = tmp_path / "proj" / "old.jsonl"
    old.parent.mkdir()
    old.write_text(entry("m1", "r1", 7), encoding="utf-8")
    two_days = time.time() - 2 * 86400
    os.utime(old, (two_days, two_days))
    assert ClaudeMeter(tmp_path).today()["output"] == 0


def test_gemini_meter_adds_up_and_survives_a_restart(tmp_path):
    meter = GeminiMeter(tmp_path / "usage.json")
    meter.add({"promptTokenCount": 100, "candidatesTokenCount": 20, "thoughtsTokenCount": 5})
    meter.add(None)
    meter.add({"promptTokenCount": 1})
    assert GeminiMeter(tmp_path / "usage.json").today() == {"input": 101, "output": 25}
