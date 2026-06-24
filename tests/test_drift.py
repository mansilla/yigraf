"""Drift detection + rename auto-re-anchor — the M3 done-test (docs/m3-notes.md)."""
from pathlib import Path

from typer.testing import CliRunner

from yigraf.cli import app
from yigraf.config import default_config
from yigraf.drift import compute_drift
from yigraf.extract import build_graph

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"
SRC = "auth/session.py"


def _linked_repo(tmp_path: Path) -> Path:
    """An initialized repo with one task linked (implements) to ``refresh``, anchored."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["plan", "auth", "--repo", str(tmp_path), "-t", "Auth",
                               "--task", "do it"]).exit_code == 0
    assert runner.invoke(app, ["link", "task:auth/1", SYM, "--repo", str(tmp_path)]).exit_code == 0
    return tmp_path


def _drift(root: Path):
    graph, _ = build_graph(root, default_config())  # build re-anchors renames in-memory first
    return compute_drift(graph)


def test_freshly_linked_repo_has_no_drift(tmp_path: Path):
    assert _drift(_linked_repo(tmp_path)) == []


def test_editing_the_body_surfaces_soft_drift(tmp_path: Path):
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")
    items = _drift(root)
    assert [i.kind for i in items] == ["soft"]
    assert items[0].task_id == "task:auth/1" and items[0].locator == SYM


def test_renaming_auto_reanchors_with_no_drift(tmp_path: Path):
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def renew(token):\n    return token\n")  # pure rename, body identical
    items = _drift(root)
    assert [i.kind for i in items] == ["renamed"]
    assert items[0].locator == SYM
    assert items[0].new_locator == "sym:auth/session.py#renew"


def test_renamed_edge_carries_into_the_graph(tmp_path: Path):
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def renew(token):\n    return token\n")
    graph, _ = build_graph(root, default_config())
    new = "sym:auth/session.py#renew"
    assert graph.has_edge("task:auth/1", new)
    assert graph["task:auth/1"][new]["renamed_from"] == SYM
    assert graph["task:auth/1"][new]["anchor"] == graph.nodes[new]["content_hash"]  # no drift


def test_deleting_the_symbol_surfaces_hard_drift(tmp_path: Path):
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def unrelated():\n    return 0\n")
    items = _drift(root)
    assert [i.kind for i in items] == ["hard"]
    assert items[0].locator == SYM


def test_rename_plus_body_edit_is_honest_hard_drift(tmp_path: Path):
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def renew(token):\n    return token + 1\n")  # renamed AND edited
    assert [i.kind for i in _drift(root)] == ["hard"]  # body-hash no longer matches → can't re-anchor


def test_drift_cli_clean_exits_zero(tmp_path: Path):
    result = runner.invoke(app, ["drift", str(_linked_repo(tmp_path))])
    assert result.exit_code == 0 and "No drift" in result.output


def test_drift_cli_soft_exits_nonzero(tmp_path: Path):
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def refresh(token):\n    return token + 9\n")
    result = runner.invoke(app, ["drift", str(root)])
    assert result.exit_code == 1 and "soft drift" in result.output


def test_drift_cli_rename_is_surfaced_but_not_a_failure(tmp_path: Path):
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def renew(token):\n    return token\n")
    result = runner.invoke(app, ["drift", str(root)])
    assert result.exit_code == 0 and "renamed" in result.output
