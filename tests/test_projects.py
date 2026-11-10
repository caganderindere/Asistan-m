import json
import os

from server.projects import ProjectList, discover, project_slug


def session(claude, folder, cwd, mtime):
    d = claude / folder
    d.mkdir(parents=True)
    f = d / "s.jsonl"
    f.write_text('{"type":"mode"}\nbozuk satır\n' + json.dumps({"cwd": cwd}) + "\n", encoding="utf-8")
    os.utime(f, (mtime, mtime))


def test_discover_reads_real_paths_newest_first(tmp_path):
    claude = tmp_path / "claude"
    session(claude, "D--Eski", "D:\\Eski", 1000)
    session(claude, "C--Users--a-an", "C:\\Users\\çağan", 2000)
    session(claude, "bash", "/c/Users/x", 3000)  # not a Windows path: skipped
    (claude / "bos").mkdir()
    assert discover(claude) == ["C:\\Users\\çağan", "D:\\Eski"]


def test_listing_keeps_only_real_folders_once(tmp_path):
    claude = tmp_path / "claude"
    real = tmp_path / "Site"
    real.mkdir()
    session(claude, "a", str(real), 2000)
    session(claude, "b", str(real).upper(), 1500)
    session(claude, "c", str(tmp_path / "silinmis"), 1000)
    projects = ProjectList(tmp_path / "projects.json", str(tmp_path), claude)
    assert [p["path"] for p in projects.listing()["projects"]] == [str(real), str(tmp_path)]
    assert projects.listing()["projects"][0]["name"] == "Site"


def test_added_folder_comes_first_and_is_remembered(tmp_path):
    extra = tmp_path / "Yeni"
    extra.mkdir()
    projects = ProjectList(tmp_path / "projects.json", str(tmp_path), tmp_path / "yok")
    assert projects.add(f'"{extra}"') == str(extra)
    assert projects.add(str(tmp_path / "olmayan")) is None
    assert projects.add("göreli\\yol") is None
    again = ProjectList(tmp_path / "projects.json", str(tmp_path), tmp_path / "yok")
    assert again.paths() == [str(extra), str(tmp_path)]


def test_current_falls_back_when_folder_is_gone(tmp_path):
    gone = tmp_path / "gecici"
    gone.mkdir()
    projects = ProjectList(tmp_path / "projects.json", str(tmp_path), tmp_path / "yok")
    projects.select(str(gone))
    assert projects.current == str(gone)
    gone.rmdir()
    assert projects.current == str(tmp_path)


def test_slug_is_safe_and_distinct():
    a, b = project_slug("C:\\Users\\çağan\\Nevka Gıda"), project_slug("D:\\Nevka Gıda")
    assert a != b and a.startswith("Nevka-G-da-") and all(c.isalnum() or c == "-" for c in a)
    assert project_slug("D:\\")
