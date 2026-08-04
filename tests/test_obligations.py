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


# --- Conflict verbs: the notice must name the verb that actually closes THAT conflict --------------


def _conflict_notice(graph=None, **kw) -> str:
    from yigraf.contradiction import Conflict
    base = dict(anchor="sym:a.py#f", left="mem:aaa", right="mem:bbb", cosine=0.91)
    return obligations._conflict(Conflict(**{**base, **kw}), graph).render()


def _graph_with(**provenance_by_id):
    """A minimal graph whose nodes carry folded provenance (mem:063)."""
    import networkx as nx
    g = nx.DiGraph()
    for node_id, prov in provenance_by_id.items():
        g.add_node(node_id.replace("_", ":"), family="memory", provenance=prov)
    return g


def test_a_pending_conflict_routes_to_attest_because_the_agent_cannot_clear_it():
    line = _conflict_notice(pending=True)
    # mem:048: an agent supersede of a human-attested node is held pending. Offering `reconcile` here
    # would be telling the agent to do the one thing it structurally cannot.
    assert "yigraf attest" in line and "only a principal" in line
    assert "yigraf reconcile" not in line


def test_a_swept_conflict_also_offers_dispute_to_make_it_durable():
    line = _conflict_notice()
    # The cosine sweep is index-derived and fails open to silence, so an un-nominated pair is visible
    # only to whoever holds an index — `dispute` is what makes it visible to everyone.
    assert "yigraf reconcile" in line and "yigraf supersede" in line
    assert "yigraf dispute" in line and "cos 0.91" in line


def test_a_nominated_conflict_asserts_neither_a_cosine_nor_an_anchor_it_lacks():
    line = _conflict_notice(anchor="", cosine=0.0, nominated=True)
    assert "nominated as contradictory by a principal" in line
    assert "cos" not in line  # a nomination is a judgment, not a measurement
    assert "(no shared anchor)" in line  # never render a bare, empty `← `
    assert "yigraf dispute" not in line  # already nominated


def test_the_preferred_side_is_named_when_provenance_has_one():
    assert "yigraf supersede mem:bbb" in _conflict_notice(dominant="mem:aaa")
    assert "yigraf supersede <loser>" in _conflict_notice(dominant=None)  # same tier ⇒ never tie-broken


# --- Online: a belief that arrived over the shared log changes the right next step ----------------


def test_a_locally_authored_belief_carries_no_attribution():
    # `remember` writes [{"source": "cli"}] with no actor — the discriminator for "came over the wire".
    graph = _graph_with(mem_aaa=[{"source": "cli"}], mem_bbb=[{"source": "cli"}])
    line = _conflict_notice(graph)
    assert "(by " not in line
    assert "yigraf supersede" in line  # your own beliefs — supersede is a fine default


def test_a_conflict_with_a_teammates_belief_routes_to_dispute_not_supersede():
    graph = _graph_with(mem_aaa=[{"source": "cli"}],
                        mem_bbb=[{"actor": "alice", "source": "agent"}])
    line = _conflict_notice(graph)
    assert "(by alice)" in line  # attributed, per int:obligation-notice's online scenario
    assert "yigraf dispute" in line
    assert "Don't supersede someone else's belief without asking." in line


def test_drift_on_a_teammates_decision_does_not_tell_you_to_reaffirm_it():
    from yigraf.drift import DriftItem
    graph = _graph_with(mem_ccc=[{"actor": "bob", "source": "agent"}])
    item = DriftItem("soft", "mem:ccc", "sym:a.py#f", detail="body changed", relation="concerns")
    line = obligations._drift(item, graph).render()
    # You cannot honestly re-verify reasoning you never held; reaffirming it would be a rubber-stamp.
    assert "(by bob)" in line and "yigraf reaffirm" not in line
    assert "ask before you clear it" in line


def test_attribution_is_not_part_of_the_key_so_a_second_asserter_does_not_re_announce():
    from yigraf.contradiction import Conflict
    c = Conflict(anchor="sym:a.py#f", left="mem:aaa", right="mem:bbb", cosine=0.91)
    solo = _graph_with(mem_aaa=[{"source": "cli"}], mem_bbb=[{"source": "cli"}])
    joined = _graph_with(mem_aaa=[{"source": "cli"}],
                         mem_bbb=[{"source": "cli"}, {"actor": "alice", "source": "agent"}])
    assert obligations._conflict(c, solo).key == obligations._conflict(c, joined).key


def test_a_resolved_obligation_that_recurs_announces_again(tmp_path: Path, stale_repo: Path):
    _stop(stale_repo)
    latch = json.loads(obligations.latch_path(stale_repo).read_text())
    assert latch["s1"]["keys"], "the announced key is latched"
    # Resolution is silent, and the key drops out of the session set so a recurrence is a new event.
    fresh = obligations.new_obligations(stale_repo, [], "s1", fingerprint="x")
    assert fresh == []
    assert json.loads(obligations.latch_path(stale_repo).read_text())["s1"]["keys"] == []
