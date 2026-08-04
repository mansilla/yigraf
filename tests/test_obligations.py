"""The principal's turn-boundary obligation notice (int:obligation-notice).

Covers the two properties that make this channel work rather than become furniture — it is
**edge-triggered** (announced once) and **session-scoped** (re-announced after /clear) — plus the two
it must never violate: it never blocks (no ``decision`` key, ever) and it never spends the agent's
context budget (no ``additionalContext``, ever).
"""
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from yigraf import obligations
from yigraf.cli import app

runner = CliRunner()
SYM = "sym:auth/session.py#refresh"


@pytest.fixture
def stale_repo(tmp_path: Path) -> Path:
    """A repo with exactly one obligation: a DONE task whose implementing symbol drifted.

    Stale (not plain drift) is the sharpest case — ``is_surfaced`` withholds it from the agent's edit
    hook by design (mem:056), so before this channel existed it reached a human only if they happened
    to run a query or read the statusline count.
    """
    runner.invoke(app, ["init", str(tmp_path)])
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    runner.invoke(app, ["build", str(tmp_path)])
    runner.invoke(app, ["plan", "auth", "--repo", str(tmp_path), "-t", "Auth", "--task", "idle expiry"])
    runner.invoke(app, ["link", "task:auth/1", SYM, "--repo", str(tmp_path)])
    plan = tmp_path / "yigraf" / "plans" / "active" / "auth.md"
    plan.write_text(plan.read_text().replace("- [ ] {#1}", "- [x] {#1}"))
    src.write_text("def refresh(token):\n    return token + 1\n")  # drift the done task's evidence
    runner.invoke(app, ["build", str(tmp_path)])
    return tmp_path


def _stop(root: Path, session: str = "s1"):
    payload = json.dumps({"cwd": str(root), "session_id": session, "hook_event_name": "Stop"})
    return runner.invoke(app, ["hook", "stop"], input=payload)


def _notice(result) -> dict:
    assert result.exit_code == 0
    return json.loads(result.output)


# --- The core contract: edge-triggered ------------------------------------------------------------


def test_a_new_obligation_is_announced_to_the_principal(stale_repo: Path):
    payload = _notice(_stop(stale_repo))
    msg = payload["systemMessage"]
    assert "stale" in msg and "task:auth/1" in msg and SYM in msg
    assert "yigraf link task:auth/1" in msg  # the resolving verb, not just the fact


def test_the_same_obligation_is_silent_on_the_next_turn(stale_repo: Path):
    assert _stop(stale_repo).output.strip()  # first turn announces
    assert _stop(stale_repo).output.strip() == ""  # second turn is silent — edge, not level


def test_a_clean_repo_says_nothing(tmp_path: Path):
    runner.invoke(app, ["init", str(tmp_path)])
    (tmp_path / "ok.py").write_text("def ok():\n    return 1\n")
    runner.invoke(app, ["build", str(tmp_path)])
    assert _stop(tmp_path).output.strip() == ""


# --- Session scope: /clear must re-announce -------------------------------------------------------


def test_a_new_session_re_announces_a_still_open_obligation(stale_repo: Path):
    assert _stop(stale_repo, session="s1").output.strip()
    # /clear wipes the context, not the obligation — a fresh session_id must hear about it again.
    assert "task:auth/1" in _notice(_stop(stale_repo, session="s2"))["systemMessage"]


# --- The two fields that must never appear --------------------------------------------------------


def test_the_notice_never_blocks_and_never_touches_the_agents_context(stale_repo: Path):
    payload = _notice(_stop(stale_repo))
    assert "decision" not in payload  # design law #5 — informs, never gates
    assert "hookSpecificOutput" not in payload  # mem:012 — human concern, not the agent's budget
    assert set(payload) == {"systemMessage"}


# --- Fail-open ------------------------------------------------------------------------------------


def test_no_workspace_is_silent_and_exits_zero(tmp_path: Path):
    result = _stop(tmp_path)
    assert result.exit_code == 0 and result.output.strip() == ""


def test_a_corrupt_latch_falls_open_to_announcing(stale_repo: Path):
    _stop(stale_repo)  # latch now holds the key
    obligations.latch_path(stale_repo).write_text("{not json")
    # Fail-open in the SAFE direction: re-announce (recoverable) rather than go silent on a real one.
    assert "task:auth/1" in _notice(_stop(stale_repo))["systemMessage"]


def test_the_notice_can_be_switched_off(stale_repo: Path):
    config = stale_repo / "yigraf" / "config.yaml"
    config.write_text(config.read_text() + "\nstatus:\n  obligation_notice: false\n")
    assert _stop(stale_repo).output.strip() == ""


# --- Rendering ------------------------------------------------------------------------------------


def test_overflow_is_stated_rather_than_silently_truncated():
    items = [obligations.Obligation("drift", f"k{i}", f"task:p/{i}", "sym:a.py#f", "changed", "verb")
             for i in range(8)]
    notice = obligations.render_notice(items, total=8, max_lines=3)
    assert "5 more not shown" in notice
    assert notice.count("task:p/") == 3


def test_a_resolved_obligation_that_recurs_announces_again(tmp_path: Path, stale_repo: Path):
    _stop(stale_repo)
    latch = json.loads(obligations.latch_path(stale_repo).read_text())
    assert latch["s1"]["keys"], "the announced key is latched"
    # Resolution is silent, and the key drops out of the session set so a recurrence is a new event.
    fresh = obligations.new_obligations(stale_repo, [], "s1", fingerprint="x")
    assert fresh == []
    assert json.loads(obligations.latch_path(stale_repo).read_text())["s1"]["keys"] == []
