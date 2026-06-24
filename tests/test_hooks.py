"""The post-commit git hook: installation safety + a real-git rebuild-at-commit integration test."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from yigraf.cli import app
from yigraf.hooks import _MARKER, git_dir, install_post_commit_hook
from yigraf.scaffold import init_workspace

runner = CliRunner()


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def test_install_writes_an_executable_hook(tmp_path: Path):
    _git_init(tmp_path)
    result = install_post_commit_hook(tmp_path)
    assert result.installed and result.path.exists()
    assert result.path.stat().st_mode & 0o100  # owner-executable
    body = result.path.read_text()
    assert _MARKER in body and "-m yigraf build" in body


def test_install_is_idempotent_for_its_own_hook(tmp_path: Path):
    _git_init(tmp_path)
    install_post_commit_hook(tmp_path)
    second = install_post_commit_hook(tmp_path)
    assert second.installed  # ours → refreshed, still reported installed


def test_install_does_not_clobber_a_foreign_hook(tmp_path: Path):
    _git_init(tmp_path)
    hook = tmp_path / ".git" / "hooks" / "post-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho mine\n")
    result = install_post_commit_hook(tmp_path)
    assert not result.installed
    assert hook.read_text() == "#!/bin/sh\necho mine\n"


def test_install_on_a_non_git_dir_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        install_post_commit_hook(tmp_path)


def test_git_dir_follows_the_gitdir_indirection(tmp_path: Path):
    real = tmp_path / "real-git"
    real.mkdir()
    (tmp_path / ".git").write_text(f"gitdir: {real}\n")
    assert git_dir(tmp_path) == real.resolve()


def test_install_hooks_cli_requires_a_git_repo(tmp_path: Path):
    init_workspace(tmp_path)  # workspace present, but no git
    result = runner.invoke(app, ["install-hooks", str(tmp_path)])
    assert result.exit_code == 1 and "not a git repository" in result.output


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_commit_triggers_a_rebuild(tmp_path: Path):
    _git_init(tmp_path)
    init_workspace(tmp_path)
    (tmp_path / "m.py").write_text("def f():\n    return 1\n")
    assert runner.invoke(app, ["install-hooks", str(tmp_path)]).exit_code == 0

    before = json.loads((tmp_path / "yigraf" / "graph.json").read_text())
    assert before["nodes"] == []  # the init stub, untouched until a commit

    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.co", "-c", "user.name=t", "commit", "-q", "-m", "src"],
        cwd=tmp_path, check=True,
    )

    after = json.loads((tmp_path / "yigraf" / "graph.json").read_text())
    ids = {n["id"] for n in after["nodes"]}
    assert "sym:m.py#f" in ids  # the post-commit hook rebuilt the graph from HEAD
