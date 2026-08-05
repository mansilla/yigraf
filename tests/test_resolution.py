"""Resolution artifacts: a verdict on beliefs the resolving principal does not own (mem:062).

The two properties that matter for the team case:

- a verdict can be authored by someone who owns *neither* belief (otherwise a conflict deadlocks the
  moment one author leaves), and
- a *nominated* dispute surfaces without an embedding index, so every client sharing a log sees the
  same open-conflict set rather than only whoever happens to have vectors locally.
"""
from pathlib import Path

import networkx as nx
from typer.testing import CliRunner

from yigraf import contradiction, filelog, resolution
from yigraf.cli import app
from yigraf.fold import fold
from yigraf.log import Assertion, causal_order

runner = CliRunner()


def _belief(node_id: str, statement: str = "", anchor: str | None = None) -> Assertion:
    edges = []
    if anchor:
        edges.append({"relation": "concerns", "target": anchor, "attrs": {}})
    return Assertion(
        id=node_id, kind="memory",
        body={"family": "memory",
              "attrs": {"kind": "decision", "status": "active", "statement": statement or node_id},
              "edges": edges})


def _fold(*assertions: Assertion, base: nx.DiGraph | None = None) -> nx.DiGraph:
    class _Log:
        def iter_assertions_in_causal_order(self):
            return causal_order(list(assertions))

    return fold(_Log(), base=base if base is not None else nx.DiGraph())


def test_verdict_projects_an_edge_between_two_beliefs_the_author_owns_neither_of():
    """The core claim: the resolving edge lands between the operands, not out of the resolution node."""
    res = resolution.Resolution(
        id=resolution.resolution_id("reconcile", "mem:a", "mem:b"),
        kind="reconcile", left="mem:a", right="mem:b", why="both true, different altitudes")
    graph = _fold(_belief("mem:a"), _belief("mem:b"), filelog._resolution_assertion(res))

    assert graph.edges["mem:a", "mem:b"]["relation"] == "equivalent_to"
    assert graph.edges["mem:a", "mem:b"]["via"] == res.id
    # ...and the verdict stays attributable from either side.
    assert {v for _, v, d in graph.out_edges(res.id, data=True) if d["relation"] == "resolves"} == {
        "mem:a", "mem:b"}


def test_reconcile_verdict_closes_the_coherence_finding():
    res = resolution.Resolution(
        id=resolution.resolution_id("reconcile", "mem:a", "mem:b"),
        kind="reconcile", left="mem:a", right="mem:b")
    graph = _fold(_belief("mem:a"), _belief("mem:b"), filelog._resolution_assertion(res))
    assert contradiction._reconciled(graph, "mem:a", "mem:b")


def test_supersede_verdict_retracts_the_target_without_editing_it():
    res = resolution.Resolution(
        id=resolution.resolution_id("supersede", "mem:new", "mem:old"),
        kind="supersede", left="mem:new", right="mem:old")
    graph = _fold(_belief("mem:new"), _belief("mem:old"), filelog._resolution_assertion(res))

    assert graph.nodes["mem:old"]["superseded_in"] == 1
    assert graph.nodes["mem:old"]["accepted"] is False
    assert graph.nodes["mem:new"]["accepted"] is True


def test_nominated_dispute_surfaces_with_no_embedding_index():
    """The team fix: the cosine sweep fails open to silence, a nomination does not."""
    res = resolution.Resolution(
        id=resolution.resolution_id("dispute", "mem:a", "mem:b"),
        kind="dispute", left="mem:a", right="mem:b", why="these contradict")
    graph = _fold(_belief("mem:a"), _belief("mem:b"), filelog._resolution_assertion(res))

    found = contradiction.detect_conflicts(graph, Path("/nonexistent"), {}, index=None)
    assert [(c.left, c.right, c.nominated) for c in found] == [("mem:a", "mem:b", True)]


def test_a_later_reconcile_closes_an_earlier_nomination():
    dispute = resolution.Resolution(id=resolution.resolution_id("dispute", "mem:a", "mem:b"),
                                    kind="dispute", left="mem:a", right="mem:b")
    agreed = resolution.Resolution(id=resolution.resolution_id("reconcile", "mem:a", "mem:b"),
                                   kind="reconcile", left="mem:a", right="mem:b")
    graph = _fold(_belief("mem:a"), _belief("mem:b"),
                  filelog._resolution_assertion(dispute), filelog._resolution_assertion(agreed))

    assert contradiction.detect_conflicts(graph, Path("/nonexistent"), {}, index=None) == []


def test_a_dispute_on_a_superseded_belief_is_moot_not_open():
    dispute = resolution.Resolution(id=resolution.resolution_id("dispute", "mem:a", "mem:b"),
                                    kind="dispute", left="mem:a", right="mem:b")
    retract = resolution.Resolution(id=resolution.resolution_id("supersede", "mem:c", "mem:b"),
                                    kind="supersede", left="mem:c", right="mem:b")
    graph = _fold(_belief("mem:a"), _belief("mem:b"), _belief("mem:c"),
                  filelog._resolution_assertion(dispute), filelog._resolution_assertion(retract))

    assert contradiction.detect_conflicts(graph, Path("/nonexistent"), {}, index=None) == []


def test_a_reconcile_closes_a_dispute_that_won_the_edge_slot():
    """Regression: a DiGraph holds one edge per ordered pair, so two verdicts on the same pair compete
    for it and the winner is decided by the causal-order id tiebreak — i.e. arbitrarily. Detection
    reads the verdict NODES, so the outcome must not depend on which edge survived."""
    dispute = resolution.Resolution(id=resolution.resolution_id("dispute", "mem:a", "mem:b"),
                                    kind="dispute", left="mem:a", right="mem:b")
    agreed = resolution.Resolution(id=resolution.resolution_id("reconcile", "mem:a", "mem:b"),
                                   kind="reconcile", left="mem:a", right="mem:b")
    graph = _fold(_belief("mem:a"), _belief("mem:b"),
                  filelog._resolution_assertion(dispute), filelog._resolution_assertion(agreed))

    # Exactly one of the two relations won the slot; which one is not something we assert.
    assert graph.edges["mem:a", "mem:b"]["relation"] in ("disputes", "equivalent_to")
    # The shadowed verdict is preserved on its own node rather than silently dropped.
    shadowed = [a.get("shadowed_projections") for _, a in graph.nodes(data=True)
                if a.get("family") == "resolution"]
    assert any(shadowed), "the losing projection must be recorded, not lost"
    # And the conflict is closed either way.
    assert contradiction.detect_conflicts(graph, Path("/nonexistent"), {}, index=None) == []


def test_reconcile_in_either_operand_order_closes_the_dispute():
    """Bob disputes (a, b); Alice reconciles (b, a). Same pair, so the verdict must still apply."""
    dispute = resolution.Resolution(id=resolution.resolution_id("dispute", "mem:a", "mem:b"),
                                    kind="dispute", left="mem:a", right="mem:b")
    agreed = resolution.Resolution(id=resolution.resolution_id("reconcile", "mem:b", "mem:a"),
                                   kind="reconcile", left="mem:b", right="mem:a")
    graph = _fold(_belief("mem:a"), _belief("mem:b"),
                  filelog._resolution_assertion(dispute), filelog._resolution_assertion(agreed))
    assert contradiction.detect_conflicts(graph, Path("/nonexistent"), {}, index=None) == []


def test_reconcile_does_not_mutate_the_belief_it_judges():
    """memid-v1 does not cover ``equivalent_to``, so writing it onto a belief would change that
    assertion's body while leaving its id fixed — invisible to a content-addressed sync."""
    res = resolution.Resolution(id=resolution.resolution_id("reconcile", "mem:a", "mem:b"),
                                kind="reconcile", left="mem:a", right="mem:b")
    left = _belief("mem:a")
    body_before = dict(left.body)
    _fold(left, _belief("mem:b"), filelog._resolution_assertion(res))
    assert left.body == body_before


def test_verdict_id_is_content_addressed_so_two_principals_collapse():
    """Same verdict on the same pair ⇒ one node, not a fork (mem:060/mem:063). ``why`` is excluded:
    two people agreeing for different reasons are still asserting the same thing."""
    a = resolution.resolution_id("reconcile", "mem:a", "mem:b")
    b = resolution.resolution_id("reconcile", "mem:a", "mem:b")
    assert a == b
    assert a != resolution.resolution_id("dispute", "mem:a", "mem:b")
    assert a != resolution.resolution_id("reconcile", "mem:b", "mem:a")


def test_dangling_projection_is_recovered_not_half_applied():
    """A partial replica missing an operand must not leave a half-applied verdict (R5 fail-open).

    Both directions stash the full spec somewhere a later fold with the whole log can recover it: a
    missing *target* follows the existing per-relation convention on the source belief, while a missing
    *source* — the case only a projection can hit — is held on the resolution node itself.
    """
    missing_target = resolution.Resolution(
        id=resolution.resolution_id("reconcile", "mem:a", "mem:gone"),
        kind="reconcile", left="mem:a", right="mem:gone")
    graph = _fold(_belief("mem:a"), filelog._resolution_assertion(missing_target))
    assert not graph.has_edge("mem:a", "mem:gone")
    assert graph.nodes["mem:a"]["dangling_edges"][0]["target"] == "mem:gone"

    missing_source = resolution.Resolution(
        id=resolution.resolution_id("reconcile", "mem:gone", "mem:b"),
        kind="reconcile", left="mem:gone", right="mem:b")
    graph2 = _fold(_belief("mem:b"), filelog._resolution_assertion(missing_source))
    assert not graph2.has_edge("mem:gone", "mem:b")
    assert graph2.nodes[missing_source.id]["dangling_projections"][0]["source"] == "mem:gone"


def test_roundtrip_through_markdown(tmp_path):
    res = resolution.Resolution(id=resolution.resolution_id("dispute", "mem:a", "mem:b"),
                                kind="dispute", left="mem:a", right="mem:b",
                                why="one says cache, the other says never cache",
                                provenance={"source": "cli", "actor": "me@example.com"})
    path = resolution.resolution_path(tmp_path, res)
    path.parent.mkdir(parents=True)
    path.write_text(resolution.render_resolution(res), encoding="utf-8")

    back = resolution.read_resolution(path)
    assert (back.id, back.kind, back.left, back.right) == (res.id, "dispute", "mem:a", "mem:b")
    assert back.why == res.why
    assert back.provenance["actor"] == "me@example.com"
    assert [r.id for r in resolution.iter_resolutions(tmp_path)] == [res.id]


def test_dispute_verb_writes_a_verdict_for_beliefs_and_is_idempotent(tmp_path):
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    (tmp_path / "app.py").write_text("def f():\n    return 1\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    first = runner.invoke(app, ["remember", "cache the token", "--why", "latency",
                                "--concerns", "sym:app.py#f", "--repo", str(tmp_path)])
    second = runner.invoke(app, ["remember", "never cache the token", "--why", "security",
                                 "--concerns", "sym:app.py#f", "--new", "--repo", str(tmp_path)])
    assert first.exit_code == 0 and second.exit_code == 0
    from yigraf import memory as memory_mod
    ids = [m.id for m in memory_mod.iter_memories(tmp_path)]
    assert len(ids) == 2

    out = runner.invoke(app, ["dispute", ids[0], ids[1], "--why", "they contradict",
                              "--repo", str(tmp_path)])
    assert out.exit_code == 0, out.output
    assert len(resolution.iter_resolutions(tmp_path)) == 1
    # Re-running declines with guidance rather than duplicating (content-addressed, and _guidance
    # deliberately exits 0 so an agent retries instead of abandoning the tool).
    again = runner.invoke(app, ["dispute", ids[0], ids[1], "--repo", str(tmp_path)])
    assert again.exit_code == 0
    assert "already" in again.output
    assert len(resolution.iter_resolutions(tmp_path)) == 1


def test_context_renders_the_beliefs_not_the_bookkeeping(tmp_path):
    """A resolution is a verdict *about* beliefs — it must not spend the agent's context budget, and a
    family retrieval has no reserved share for must never take the read path down."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    (tmp_path / "app.py").write_text("def f():\n    return 1\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    runner.invoke(app, ["remember", "cache the token", "--why", "latency",
                        "--concerns", "sym:app.py#f", "--repo", str(tmp_path)])
    runner.invoke(app, ["remember", "never cache the token", "--why", "security",
                        "--concerns", "sym:app.py#f", "--new", "--repo", str(tmp_path)])
    from yigraf import memory as memory_mod
    ids = [m.id for m in memory_mod.iter_memories(tmp_path)]
    assert runner.invoke(app, ["dispute", *ids, "--repo", str(tmp_path)]).exit_code == 0

    out = runner.invoke(app, ["context", "cache", "--repo", str(tmp_path)])
    assert out.exit_code == 0, out.output
    assert all(i in out.output for i in ids), "both disputed beliefs must still render"
    assert "res:" not in out.output, "the verdict node is bookkeeping, not context"


def test_reconcile_works_when_neither_belief_is_authored_here(tmp_path):
    """The deadlock case: neither belief has a local artifact, so an in-place edit is impossible."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0

    # Both ids exist only in the folded graph (as a replica would supply them), not on disk.
    import yigraf.cli as cli_mod
    original = cli_mod._known_belief
    cli_mod._known_belief = lambda repo, belief_id: True
    try:
        out = runner.invoke(app, ["reconcile", "mem:remote1", "mem:remote2",
                                  "--why", "same call, different altitude", "--repo", str(tmp_path)])
    finally:
        cli_mod._known_belief = original

    assert out.exit_code == 0, out.output
    written = resolution.iter_resolutions(tmp_path)
    assert [(r.kind, r.left, r.right) for r in written] == [("reconcile", "mem:remote1", "mem:remote2")]
