"""`yigraf conflicts` — the listing surface for the third re-verify signal (feedback-v3 #1).

The field report's sharpest finding: `status` read `⚠ 1 conflict` while `drift`, `show`, and `context`
printed nothing, and every resolving verb takes two ids that nothing handed over. These tests pin the
fix: the count now has a command that names the pair and the verbs, `show` reports a conflict its node
is a side of, and the empty case is honest about what the sweep could and could not see.

Nominated disputes are used as the conflict source because they are index-free (the suite disables
embeddings for determinism) — the rendering path is identical for swept pairs.
"""
import re
from pathlib import Path

from typer.testing import CliRunner

from yigraf.cli import app

runner = CliRunner()


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _remember(root: Path, statement: str) -> str:
    result = runner.invoke(app, ["remember", statement, "--repo", str(root),
                                 "--concerns", "sym:auth/session.py#refresh"])
    assert result.exit_code == 0, result.output
    match = re.search(r"mem:[0-9a-f]+", result.output)
    assert match, result.output
    return match.group(0)


def test_conflicts_is_silent_and_green_when_clean(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["conflicts", str(root)])
    assert result.exit_code == 0, result.output
    assert "No open conflicts" in result.output


def test_conflicts_lists_the_pair_and_the_resolving_verbs(tmp_path: Path):
    """The integer in `status` now has a command behind it: pair, anchor, verbs, non-zero exit."""
    root = _repo(tmp_path)
    a = _remember(root, "Sessions expire after 30 minutes idle.")
    b = _remember(root, "Sessions never expire while a download is active.")
    assert runner.invoke(app, ["dispute", a, b, "--repo", str(root),
                               "--why", "these contradict"]).exit_code == 0
    result = runner.invoke(app, ["conflicts", str(root)])
    assert result.exit_code == 1, result.output          # CI-gateable, exactly like `drift`
    assert a in result.output and b in result.output     # the two ids the verbs need
    assert "reconcile" in result.output                  # a resolving verb is named, not just a count


def test_show_names_a_conflict_its_node_is_a_side_of(tmp_path: Path):
    """feedback-v3 #1: six `show`s on candidate memories printed no conflict line. Now the node's own
    read reports the pair — a reader holding an id is the one most able to resolve it."""
    root = _repo(tmp_path)
    a = _remember(root, "Sessions expire after 30 minutes idle.")
    b = _remember(root, "Sessions never expire while a download is active.")
    assert runner.invoke(app, ["dispute", a, b, "--repo", str(root),
                               "--why", "these contradict"]).exit_code == 0
    result = runner.invoke(app, ["show", a, "--repo", str(root)])
    assert result.exit_code == 0, result.output
    assert "⚠ Conflict" in result.output and b in result.output


def test_show_stays_quiet_on_an_unconflicted_node(tmp_path: Path):
    root = _repo(tmp_path)
    a = _remember(root, "Sessions expire after 30 minutes idle.")
    result = runner.invoke(app, ["show", a, "--repo", str(root)])
    assert result.exit_code == 0, result.output
    assert "⚠ Conflict" not in result.output
