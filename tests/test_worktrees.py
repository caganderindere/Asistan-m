import subprocess

import pytest

from server import worktrees
from server.worktrees import DalError


def git(folder, *args):
    subprocess.run(["git", *args], cwd=folder, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    project = tmp_path / "site"
    project.mkdir()
    git(project, "init", "-q", "-b", "main")
    git(project, "config", "user.email", "t@t")
    git(project, "config", "user.name", "t")
    (project / "a.txt").write_text("bir\n", encoding="utf-8")
    git(project, "add", ".")
    git(project, "commit", "-qm", "ilk")
    return project


def work(branch: dict, text: str) -> None:
    folder = branch["klasor"]
    (worktrees.Path(folder) / "a.txt").write_text(text, encoding="utf-8")
    git(folder, "commit", "-qam", "iş")


def test_open_list_and_merge(repo):
    branch = worktrees.open_branch(repo, "Giriş Sayfası")
    assert branch["dal"] == "cuba/giris-sayfasi"
    assert worktrees.Path(branch["klasor"]).parent.name == "site-isler"
    work(branch, "iki\n")
    [listed] = worktrees.branches(repo)
    assert listed["dal"] == "cuba/giris-sayfasi" and "1 file changed" in listed["degisiklik"]
    assert "a.txt" in worktrees.diff(repo, "giris")["ozet"]
    assert worktrees.merge(repo, "giris")["ok"]
    assert (repo / "a.txt").read_text(encoding="utf-8") == "iki\n"
    assert worktrees.branches(repo) == []


def test_conflict_leaves_project_untouched(repo):
    branch = worktrees.open_branch(repo, "renk")
    work(branch, "dal\n")
    (repo / "a.txt").write_text("ana\n", encoding="utf-8")
    git(repo, "commit", "-qam", "ana değişti")
    with pytest.raises(DalError, match="Çakışma"):
        worktrees.merge(repo, "renk")
    assert (repo / "a.txt").read_text(encoding="utf-8") == "ana\n"
    assert worktrees.branches(repo)  # the branch is still there to fix


def test_uncommitted_work_is_not_merged_and_discard_throws_away(repo):
    branch = worktrees.open_branch(repo, "deneme")
    (worktrees.Path(branch["klasor"]) / "yeni.txt").write_text("x", encoding="utf-8")
    with pytest.raises(DalError, match="commit edilmemiş"):
        worktrees.merge(repo, "deneme")
    assert worktrees.discard(repo, "deneme")["ok"]
    assert not worktrees.Path(branch["klasor"]).exists() and worktrees.branches(repo) == []


def test_unknown_branch_and_non_repo(repo, tmp_path):
    with pytest.raises(DalError, match="açık iş dalı yok"):
        worktrees.diff(repo, "yok")
    assert not worktrees.is_repo(tmp_path)


async def test_cuba_branch_tools(repo):
    from server.live import CubaTools

    async def hand_over(*_):
        return None

    tools = CubaTools(hand_over, lambda keys: None, repo,
                      projects=lambda: {"projects": [{"name": "site", "path": str(repo)}], "current": str(repo)})
    work(worktrees.open_branch(repo, "menü"), "üç\n")
    assert (await tools.run("is_dallari", {}))["dallar"][0]["dal"] == "cuba/menu"
    assert (await tools.run("dal_birlestir", {"dal": "menu"}))["ok"]
    assert "error" in await tools.run("dal_at", {"dal": "menu"})
