"""`reaffirm` never exits clean while leaving a ⚠ standing, and never re-verifies a retired belief.

feedback-v3 #6: `reaffirm mem:<id> --grounding empirical` (the skill's own recipe, minus --evidence)
passed the empirical gate whenever the node already HAD stored evidence — exiting 0, looking
successful, and clearing nothing. feedback-v3 #14: the locus batch form re-stamped SUPERSEDED
memories, counted them in its total, and credited them maturity upholds.
"""
import re
from pathlib import Path

from typer.testing import CliRunner

from yigraf import memory
from yigraf.cli import app

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"
EVIDENCE = "sym:tests/test_session.py#test_refresh"


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    test = tmp_path / "tests" / "test_session.py"
    test.parent.mkdir(parents=True)
    test.write_text("def test_refresh():\n    assert True\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _grounded_memory(root: Path) -> str:
    result = runner.invoke(app, ["remember", "Refresh keeps the token stable.", "--repo", str(root),
                                 "--concerns", SYM, "--grounding", "empirical",
                                 "--evidence", EVIDENCE])
    assert result.exit_code == 0, result.output
    return re.search(r"mem:[0-9a-f]+", result.output).group(0)


def _drift_evidence(root: Path) -> None:
    (root / "tests" / "test_session.py").write_text(
        "def test_refresh():\n    assert 1 + 1 == 2\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0


def test_empirical_restamp_with_stale_grounds_is_refused_not_silently_passed(tmp_path: Path):
    root = _repo(tmp_path)
    mem_id = _grounded_memory(root)
    _drift_evidence(root)
    result = runner.invoke(app, ["reaffirm", mem_id, "--repo", str(root),
                                 "--grounding", "empirical"])
    assert result.exit_code == 0                       # guidance, not a crash
    assert EVIDENCE in result.output                   # names the stale ref
    assert "--evidence" in result.output               # and the working incantation
    assert "Reaffirmed" not in result.output           # no claim of success


def test_bare_reaffirm_says_the_grounds_drift_it_cannot_clear_still_stands(tmp_path: Path):
    """feedback-v3 #9's kernel: two 'successes' left the ⚠ in place with nothing saying why."""
    root = _repo(tmp_path)
    mem_id = _grounded_memory(root)
    _drift_evidence(root)
    result = runner.invoke(app, ["reaffirm", mem_id, "--repo", str(root)])
    assert result.exit_code == 0, result.output
    assert "grounds-drift still stands" in result.output and EVIDENCE in result.output


def test_evidence_restamp_clears_and_stays_quiet(tmp_path: Path):
    root = _repo(tmp_path)
    mem_id = _grounded_memory(root)
    _drift_evidence(root)
    result = runner.invoke(app, ["reaffirm", mem_id, "--repo", str(root),
                                 "--grounding", "empirical", "--evidence", EVIDENCE])
    assert result.exit_code == 0, result.output
    assert "grounded by" in result.output              # the re-observation is recorded
    assert "still stands" not in result.output         # and nothing is left dangling


def test_locus_reaffirm_skips_superseded_memories_and_says_so(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["remember", "Refresh is optimistic.", "--repo", str(root),
                                 "--concerns", SYM])
    old = re.search(r"mem:[0-9a-f]+", result.output).group(0)
    result = runner.invoke(app, ["supersede", old, "Refresh is pessimistic.", "--repo", str(root)])
    new_id = re.search(r"Captured (mem:[0-9a-f]+)", result.output).group(1)
    # Drift the shared locus, then batch-reaffirm it.
    (root / "auth" / "session.py").write_text("def refresh(token):\n    return token + 'x'\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    result = runner.invoke(app, ["reaffirm", SYM, "--repo", str(root)])
    assert result.exit_code == 0, result.output
    assert "Reaffirmed 1 memory(ies)" in result.output          # only the live successor counted
    assert new_id in result.output
    assert "skipped 1 superseded" in result.output and old in result.output
    # The retired belief's artifact was not re-stamped.
    demoted = memory.read_memory(memory.find_memory(root, old))
    assert demoted.status == "superseded"
