"""run_ab.py harness helpers that don't need `claude`.

The working-tree snapshot/restore is what keeps enforceable runs independent: when the WITH arm enforces
it re-anchors the link (rewriting yigraf/ artifacts), and that mutation must NOT survive into the next
run — else run-0 reconciles the drift and every later run falsely reads "edited blind" (a real bug found
live). Restore must also preserve unrelated uncommitted WIP, which `git checkout` would clobber.
"""
import os
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


# ── three-arm isolation (with / ambient / off) ────────────────────────────────────────────────────

def test_arms_separate_the_hook_claim_from_the_install_claim():
    """Two arms conflated two questions. `ambient` (docs, no hooks) is the baseline for "does the HOOK
    help"; `off` (no yigraf affordance at all) is the baseline for "does INSTALLING yigraf help"."""
    assert run_ab.ARMS == ("with", "ambient", "off")


def test_only_the_off_arm_hides_the_instruction_files():
    """Regression for the confound that made every yigraf-self delta ~0: AGENTS.md/CLAUDE.md tell any
    agent to run `yigraf context`, so a hookless arm that can still read them is not a real baseline."""
    settings = set(run_ab._SETTINGS_CHANNELS)
    for arm in ("with", "ambient"):
        assert set(run_ab._arm_channels(arm, True)) == settings      # settings only
    off = set(run_ab._arm_channels("off", True))
    assert settings < off                                            # strict superset
    assert {"AGENTS.md", "CLAUDE.md", ".claude/skills"} <= off
    assert run_ab._arm_channels("off", False) == ()                  # --isolate off ⇒ hide nothing


def test_isolate_moves_aside_and_restores_only_existing_channels(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    agents = repo / "AGENTS.md"
    agents.write_text("run yigraf context\n")
    restore = run_ab._isolate(repo, (".claude/settings.json", "AGENTS.md"))
    assert not agents.exists()                                       # hidden during the arm
    assert (repo / "AGENTS.md.eval-bak").exists()
    restore()
    assert agents.read_text() == "run yigraf context\n"              # put back verbatim
    assert not (repo / "AGENTS.md.eval-bak").exists()


def test_pull_shim_pins_the_agents_bare_yigraf_to_the_hooks_own_build(tmp_path: Path):
    """AGENTS.md says `yigraf context`, so without this shim the PULL arm resolves whatever yigraf is on
    the developer's PATH — a different build from the one --hook-cmd PUSHES from (live: a released 1.3.0
    uv tool vs the working tree's 1.3.1). The Q1 delta would then include the version diff."""
    d = run_ab._pull_shim(tmp_path, "/abs/py -m yigraf")
    shim = d / "yigraf"
    assert shim.read_text() == '#!/bin/sh\nexec /abs/py -m yigraf "$@"\n'
    assert os.access(shim, os.X_OK)                                  # PATH lookup needs it executable
