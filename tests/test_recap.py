import asyncio
import datetime
import json

from server.recap import claude_requests, period_start, recap


def _session(root, name, entries):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "s.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def _user(text, when, cwd="D:/magaza", **extra):
    return {"type": "user", "timestamp": when.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "cwd": cwd, "message": {"role": "user", "content": text}, **extra}


def test_only_cagans_own_requests_in_the_period_are_read(tmp_path):
    now = datetime.datetime.now()
    _session(tmp_path, "D--magaza", [
        _user("Kupon hatasını düzelt", now),
        _user("<command-name>/clear</command-name>", now),
        _user("alt ajanın işi", now, isSidechain=True),
        _user("Geçen haftaki iş", now - datetime.timedelta(days=9)),
        {"type": "user", "timestamp": now.isoformat(), "toolUseResult": {}, "message": {"content": "araç çıktısı"}},
        {"type": "assistant", "message": {"content": "tamam"}},
    ])
    _session(tmp_path, "x--claude-mem-observer-sessions", [_user("gözlemci", now)])
    found = claude_requests(period_start("hafta"), root=tmp_path)
    assert [r["text"] for r in found] == ["Kupon hatasını düzelt"]
    assert found[0]["folder"] == "D:/magaza"


def test_recap_hands_requests_to_gemini_and_says_when_nothing_happened(tmp_path):
    prompts = []

    async def ask(system, prompt, as_json):
        prompts.append((system, prompt))
        return "Bugün mağazada kupon hatasını düzelttik."

    assert "görünmüyor" in asyncio.run(recap(ask, "bugun", [], root=tmp_path))["ozet"]
    _session(tmp_path, "D--magaza", [_user("Kupon hatasını düzelt", datetime.datetime.now())])
    answer = asyncio.run(recap(ask, "bugun", [], root=tmp_path))
    assert answer["ozet"].startswith("Bugün mağazada") and answer["istek_sayisi"] == 1
    assert "bugün" in prompts[0][0] and "[magaza] Kupon hatasını düzelt" in prompts[0][1]
