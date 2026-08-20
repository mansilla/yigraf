"""`--governs` — the policy anchor (feedback-v3 #5): surfaces at the edit hook, never drifts.

The field's case: "status.md holds ONLY status" drifted three times in one session, once per commit
touching the file, while every one of those edits OBEYED it. A whole-file hash is right for a claim
about contents and wrong for a claim about use — and a recurring never-real ⚠ trains the reader to
clear the badge without reading it.
"""
import re
from pathlib import Path

from typer.testing import CliRunner

from yigraf import graphdb, memory, retrieval
from yigraf.cli import app
from yigraf.config import load_config
from yigraf.drift import compute_drift

runner = CliRunner()

POLICY_FILE = "planning/status.md"


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    doc = tmp_path / POLICY_FILE
    doc.parent.mkdir(parents=True)
    doc.write_text("# Status\n\n- all green\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _governed(root: Path) -> str:
    result = runner.invoke(app, ["note-constraint", "status.md holds ONLY status.",
                                 "--repo", str(root), "--governs", f"file:{POLICY_FILE}"])
    assert result.exit_code == 0, result.output
    return re.search(r"mem:[0-9a-f]+", result.output).group(0)


def test_a_governs_anchor_never_drifts(tmp_path: Path):
    root = _repo(tmp_path)
    mem_id = _governed(root)
    (root / POLICY_FILE).write_text("# Status\n\n- all green\n- one more line\n")  # an edit that obeys it
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    graph = graphdb.load_workspace(root)
    assert not [i for i in compute_drift(graph) if i.task_id == mem_id]
    result = runner.invoke(app, ["drift", str(root)])
    assert mem_id not in result.output


def test_a_governs_anchor_still_surfaces_at_the_edit_hook(tmp_path: Path):
    """Never-drifts must not mean never-surfaces — the surfacing is the whole point of the anchor."""
    root = _repo(tmp_path)
    mem_id = _governed(root)
    graph = graphdb.load_workspace(root)
    config = load_config(root / "yigraf" / "config.yaml")
    result = retrieval.context_for_locus(graph, POLICY_FILE, config, root=root)
    assert result is not None and "holds ONLY status" in result.text, (
        result.text if result else "hook stayed silent")


def test_reaffirm_leaves_a_governs_anchor_alone(tmp_path: Path):
    """Re-stamping a policy anchor would convert it into a drifting content hash — the exact rot the
    tier exists to avoid."""
    root = _repo(tmp_path)
    mem_id = _governed(root)
    assert runner.invoke(app, ["reaffirm", f"file:{POLICY_FILE}", "--repo", str(root)]).exit_code == 0
    node = memory.read_memory(memory.find_memory(root, mem_id))
    assert node.concerns[0].anchor is None
    assert node.concerns[0].anchor_algo == memory.GOVERNS_ALGO


def test_supersede_inherits_a_governs_anchor_as_governs(tmp_path: Path):
    root = _repo(tmp_path)
    old = _governed(root)
    result = runner.invoke(app, ["supersede", old, "status.md holds status and open risks.",
                                 "--repo", str(root)])
    assert result.exit_code == 0, result.output
    new_id = re.search(r"Captured (mem:[0-9a-f]+)", result.output).group(1)
    node = memory.read_memory(memory.find_memory(root, new_id))
    assert [c.sym for c in node.concerns] == [f"file:{POLICY_FILE}"]
    assert node.concerns[0].anchor is None and node.concerns[0].anchor_algo == memory.GOVERNS_ALGO


def test_governs_refuses_a_missing_locus(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["remember", "Ghost policy.", "--repo", str(root),
                                 "--governs", "file:docs/nope.md"])
    assert result.exit_code == 0
    assert "no such file" in result.output and "Captured" not in result.output
