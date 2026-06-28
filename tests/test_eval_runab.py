"""run_ab.py harness helpers that don't need `claude`.

The working-tree snapshot/restore is what keeps enforceable runs independent: when the WITH arm enforces
it re-anchors the link (rewriting yigraf/ artifacts), and that mutation must NOT survive into the next
run — else run-0 reconciles the drift and every later run falsely reads "edited blind" (a real bug found
live). Restore must also preserve unrelated uncommitted WIP, which `git checkout` would clobber.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "eval"))
import run_ab  # noqa: E402


def test_snapshot_restores_file_and_dir_and_removes_stray_files(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "ws").mkdir(parents=True)
    src, art = repo / "code.py", repo / "ws" / "anchor.md"
    src.write_text("original\n")
    art.write_text("anchor: AAAA\n")

    restore = run_ab._snapshot(["code.py", "ws"], repo, tmp_path / "snap")

    # Simulate a run that edits the code AND re-anchors (and creates a new memory node).
    src.write_text("edited\n")
    art.write_text("anchor: BBBB\n")
    (repo / "ws" / "new-memory.md").write_text("created during the run\n")

    restore()

    assert src.read_text() == "original\n"          # edited file reverted
    assert art.read_text() == "anchor: AAAA\n"       # re-anchor reverted (the poisoning fix)
    assert not (repo / "ws" / "new-memory.md").exists()  # dir restored wholesale → stray node gone


def test_snapshot_skips_absent_paths(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "present.py").write_text("x\n")
    # A declared path that doesn't exist must not crash snapshot or restore.
    restore = run_ab._snapshot(["present.py", "does-not-exist"], repo, tmp_path / "snap")
    (repo / "present.py").write_text("y\n")
    restore()
    assert (repo / "present.py").read_text() == "x\n"
