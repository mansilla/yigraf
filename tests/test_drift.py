"""Drift detection + rename auto-re-anchor — the M3 done-test (docs/m3-notes.md)."""
from pathlib import Path

from typer.testing import CliRunner

from yigraf.cli import app
from yigraf.config import default_config
from yigraf import retrieval
from yigraf.drift import compute_drift, is_surfaced
from yigraf.extract import build_graph
from yigraf.status import compute_status

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


# --- int:drift-done-suppression: a done task's implements drift is provenance, not a re-verify nag --

def _mark_task_done(root: Path) -> None:
    plan = root / "yigraf" / "plans" / "active" / "auth.md"
    plan.write_text(plan.read_text().replace("- [ ] {#1}", "- [x] {#1}"))


def _drift_the_body(root: Path) -> None:
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")


def test_done_task_drift_is_computed_but_not_surfaced(tmp_path: Path):
    """compute_drift still emits it (the internal set _verified_reconcile relies on), but is_surfaced
    withholds it from what the agent sees."""
    root = _linked_repo(tmp_path)
    _mark_task_done(root)
    _drift_the_body(root)
    graph, _ = build_graph(root, default_config())
    items = compute_drift(graph)
    assert [i.kind for i in items] == ["soft"]           # still in the full set
    assert items[0].task_id == "task:auth/1"
    assert is_surfaced(graph, items[0]) is False          # but not surfaced


def test_open_task_drift_stays_surfaced(tmp_path: Path):
    """The other side: an OPEN task's implements drift is mid-change work — still worth seeing."""
    root = _linked_repo(tmp_path)  # task left todo
    _drift_the_body(root)
    graph, _ = build_graph(root, default_config())
    assert is_surfaced(graph, compute_drift(graph)[0]) is True


def test_drift_cli_hides_done_task_drift(tmp_path: Path):
    """A done task's soft drift must not print, and must not trip the exit-1 nag gate."""
    root = _linked_repo(tmp_path)
    _mark_task_done(root)
    _drift_the_body(root)
    result = runner.invoke(app, ["drift", str(root)])
    assert result.exit_code == 0 and "No drift" in result.output


def test_status_count_excludes_done_task_drift(tmp_path: Path):
    root = _linked_repo(tmp_path)
    _mark_task_done(root)
    _drift_the_body(root)
    graph, _ = build_graph(root, default_config())
    assert compute_status(graph, root, default_config()).drifting == 0


def test_satisfied_intent_still_flagged_when_only_done_link_drifts(tmp_path: Path):
    """The load-bearing split: the done-task drift LINE is suppressed, yet the satisfied intent it
    backs is still reported unverified — because compute_drift kept the edge in the internal set."""
    root = _linked_repo(tmp_path)
    assert runner.invoke(app, ["intent", "refresh-works", "--repo", str(root),
                               "-s", "yigraf SHALL refresh tokens."]).exit_code == 0
    assert runner.invoke(app, ["intent", "refresh-works", "--repo", str(root),
                               "--status", "satisfied"]).exit_code == 0
    assert runner.invoke(app, ["link", "task:auth/1", "int:refresh-works",
                               "--repo", str(root)]).exit_code == 0
    _mark_task_done(root)
    _drift_the_body(root)
    graph, _ = build_graph(root, default_config())
    text = retrieval.context(graph, "refresh", default_config(), root=root).text
    assert "task:auth/1 → " not in text                                  # drift line suppressed
    assert "int:refresh-works is satisfied but not verified" in text     # yet the intent is flagged
