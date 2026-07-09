"""The memory node family + capture verbs — the M7 done-test (docs/memory-model.md, capture-flow.md).

Covers: ``remember``/``note-constraint``/``supersede`` project memory nodes with their
``serves``/``concerns``/``supersedes`` edges; a ``concerns`` edge is anchored and drift-bearing (the
second drift relation after ``implements``); a rename auto-re-anchors a ``concerns`` edge for free;
supersession materializes the ``superseded_in`` counter and the active decision out-ranks the stale
one; and the decision surfaces in ``context`` / the action-driven hook.
"""
from pathlib import Path

from typer.testing import CliRunner

from yigraf import memory
from yigraf.cli import app
from yigraf.config import default_config
from yigraf.drift import compute_drift
from yigraf.extract import build_graph
from yigraf.graph import read_graph
from yigraf import retrieval

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"
SRC = "auth/session.py"


def _repo(tmp_path: Path) -> Path:
    """An initialized, built repo with one symbol and one active intent to serve."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["intent", "session-expiry", "--repo", str(tmp_path),
                               "-s", "Sessions SHALL expire after 30m idle.",
                               "--scenario", "Given idle 30m, When a request arrives, Then 401.",
                               "--status", "active"]).exit_code == 0
    return tmp_path


def _run(args: list[str]):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result


def _graph(root: Path):
    return read_graph(root / "yigraf" / "graph.json")


def _remember(root: Path, statement: str, **opts) -> None:
    args = ["remember", statement, "--repo", str(root)]
    for key in ("type", "why", "rejected", "grounding"):
        if key in opts:
            args += [f"--{key}", opts[key]]
    for target in opts.get("serves", []):
        args += ["--serves", target]
    for sym in opts.get("concerns", []):
        args += ["--concerns", sym]
    _run(args)


# --------------------------------------------------------------------------------------------------
# remember → node + edges + anchor
# --------------------------------------------------------------------------------------------------


def test_remember_projects_a_memory_node_with_its_edges(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "session refresh uses optimistic locking", type="decision",
              why="refresh path is hot; a retry is cheaper than serializing",
              serves=["int:session-expiry"], concerns=[SYM], rejected="pessimistic row lock")
    g = _graph(root)
    node = g.nodes["mem:001"]
    assert node["family"] == "memory" and node["kind"] == "decision" and node["status"] == "active"
    assert node["statement"] == "session refresh uses optimistic locking"
    assert node["why"].startswith("refresh path is hot")
    assert node["alternatives"] == "pessimistic row lock"
    assert g.edges["mem:001", "int:session-expiry"]["relation"] == "serves"
    assert g.edges["mem:001", SYM]["relation"] == "concerns"


def test_concerns_edge_is_anchored_to_the_symbol_hash(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    g = _graph(root)
    edge = g.edges["mem:001", SYM]
    assert edge["anchor_algo"] == "astnorm-v1"
    assert edge["anchor"] == g.nodes[SYM]["content_hash"]  # freshly captured → no drift


def test_remember_rejects_an_unknown_type(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["remember", "x", "--type", "bogus", "--repo", str(root)])
    # Recoverable conditions return exit 0 + guidance, never a hard error (errors teach abandonment).
    assert result.exit_code == 0 and "--type must be one of" in result.output


def test_remember_soft_warns_and_dangles_an_unknown_concerns_symbol(tmp_path: Path):
    """D#3: a forward-reference concerns is legitimate — soft-warn + create a dangling edge, never block."""
    root = _repo(tmp_path)
    result = runner.invoke(app, ["remember", "x", "--concerns", "sym:auth/session.py#ghost",
                                 "--repo", str(root)])
    assert result.exit_code == 0
    assert "no such symbol" in result.output and "dangling concerns edge" in result.output
    assert "Did you mean: sym:auth/session.py#refresh?" in result.output  # still helps a typo
    node = memory.read_memory(memory.find_memory(root, "mem:001"))  # captured anyway
    assert node.concerns[0].sym == "sym:auth/session.py#ghost" and node.concerns[0].anchor is None


def test_note_constraint_is_a_promotable_constraint(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["note-constraint", "refresh() must not block over 50ms", "--concerns", SYM,
          "--repo", str(root)])
    node = _graph(root).nodes["mem:001"]
    assert node["kind"] == "constraint" and node["promotable"] is True


# --------------------------------------------------------------------------------------------------
# concerns drift (the second drift-bearing relation)
# --------------------------------------------------------------------------------------------------


def test_editing_concerned_code_surfaces_concerns_drift(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")  # body changed
    graph, _ = build_graph(root, default_config())
    items = [i for i in compute_drift(graph) if i.relation == "concerns"]
    assert [i.kind for i in items] == ["soft"]
    assert items[0].task_id == "mem:001" and items[0].locator == SYM


def test_concerns_edge_auto_reanchors_on_rename(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    (root / SRC).write_text("def renew(token):\n    return token\n")  # pure rename, identical body
    graph, _ = build_graph(root, default_config())
    new = "sym:auth/session.py#renew"
    assert graph.has_edge("mem:001", new)
    assert graph["mem:001"][new]["relation"] == "concerns"
    assert graph["mem:001"][new]["renamed_from"] == SYM
    assert [i.kind for i in compute_drift(graph) if i.relation == "concerns"] == ["renamed"]


def test_deleting_concerned_code_is_hard_concerns_drift(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    (root / SRC).write_text("def unrelated():\n    return 0\n")
    graph, _ = build_graph(root, default_config())
    items = [i for i in compute_drift(graph) if i.relation == "concerns"]
    assert [i.kind for i in items] == ["hard"] and items[0].locator == SYM


def test_reaffirm_re_anchors_and_clears_concerns_drift(tmp_path: Path):
    """The honest counterpart to supersede: re-verify holds, re-stamp the anchor, drift clears in place."""
    root = _repo(tmp_path)
    _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")  # body changed → soft drift
    graph, _ = build_graph(root, default_config())
    assert [i.kind for i in compute_drift(graph) if i.relation == "concerns"] == ["soft"]

    out = _run(["reaffirm", "mem:001", "--repo", str(root)])
    assert "re-anchored" in out.output and SYM in out.output

    graph, _ = build_graph(root, default_config())
    assert [i for i in compute_drift(graph) if i.relation == "concerns"] == []  # drift cleared
    # the anchor now equals the *current* body hash, and the edge/claim is otherwise unchanged
    assert graph.edges["mem:001", SYM]["anchor"] == graph.nodes[SYM]["content_hash"]
    assert graph.nodes["mem:001"]["statement"] == "refresh keeps the token immutable"
    assert graph.nodes["mem:001"]["status"] == "active"  # no supersede, no new node
    assert memory.find_memory(root, "mem:002") is None


def test_reaffirm_is_a_noop_when_there_is_no_drift(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    out = _run(["reaffirm", "mem:001", "--repo", str(root)])
    assert "already matched" in out.output


def test_reaffirm_unknown_memory_guides_and_exits_zero(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["reaffirm", "mem:999", "--repo", str(root)])
    assert result.exit_code == 0 and "No memory node with id mem:999" in result.output


def test_reaffirm_without_concerns_has_nothing_to_do(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "a decision that governs no specific symbol", serves=["int:session-expiry"])
    result = runner.invoke(app, ["reaffirm", "mem:001", "--repo", str(root)])
    assert result.exit_code == 0 and "concerns no symbol" in result.output


def test_reaffirm_cannot_re_anchor_a_gone_symbol(tmp_path: Path):
    """A deleted symbol is hard drift, not a reaffirm case — guide toward supersede, don't crash."""
    root = _repo(tmp_path)
    _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    (root / SRC).write_text("def unrelated():\n    return 0\n")  # refresh is gone
    out = _run(["reaffirm", "mem:001", "--repo", str(root)])
    assert "no longer resolve" in out.output and "supersede" in out.output


def test_superseded_memory_does_not_drift_on_concerned_code_change(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    _run(["supersede", "mem:001", "refresh may rotate the token",
          "--concerns", SYM, "--repo", str(root)])
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")  # body changed
    graph, _ = build_graph(root, default_config())
    sources = {i.task_id for i in compute_drift(graph) if i.relation == "concerns"}
    # The active successor still drifts; the superseded predecessor is historical and stays silent.
    assert "mem:002" in sources and "mem:001" not in sources


# --------------------------------------------------------------------------------------------------
# supersede → counters + ranking
# --------------------------------------------------------------------------------------------------


def test_supersede_links_and_marks_the_predecessor_stale(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "session refresh uses optimistic locking", concerns=[SYM])
    _run(["supersede", "mem:001", "session refresh uses pessimistic locking",
          "--why", "contention is low; a row lock is simpler", "--concerns", SYM, "--repo", str(root)])
    g = _graph(root)
    assert g.edges["mem:002", "mem:001"]["relation"] == "supersedes"
    assert g.nodes["mem:001"]["superseded_in"] == 1
    assert g.nodes["mem:002"]["supersedes_out"] == 1
    assert g.nodes["mem:002"]["superseded_in"] == 0


def test_active_decision_outranks_its_superseded_predecessor(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "session refresh uses optimistic locking", concerns=[SYM])
    _run(["supersede", "mem:001", "session refresh uses pessimistic locking",
          "--concerns", SYM, "--repo", str(root)])
    graph, _ = build_graph(root, default_config())
    result = retrieval.context(graph, "session refresh locking", default_config(), family="memory")
    # Both decisions render; the active one (mem:002) appears before the superseded mem:001.
    assert result.text.index("mem:002") < result.text.index("mem:001")
    assert "·superseded" in result.text


def test_supersede_rejects_an_unknown_old_id(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["supersede", "mem:999", "new claim", "--repo", str(root)])
    assert result.exit_code == 0 and "No memory node" in result.output


# --------------------------------------------------------------------------------------------------
# render + artifact round-trip
# --------------------------------------------------------------------------------------------------


def test_context_renders_the_decision_with_its_why(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "session refresh uses optimistic locking", type="decision",
              why="refresh path is hot", serves=["int:session-expiry"], concerns=[SYM])
    graph, _ = build_graph(root, default_config())
    result = retrieval.context(graph, "optimistic locking refresh", default_config())
    assert "Decisions (why):" in result.text
    assert "mem:001 [decision·inferred]" in result.text  # grounding rides the tag (C#6, default inferred)
    assert "why: refresh path is hot" in result.text


def test_memory_artifact_round_trips(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "a decision", why="because", concerns=[SYM], rejected="the alternative")
    path = memory.find_memory(root, "mem:001")
    assert path is not None
    mem = memory.read_memory(path)
    assert mem.id == "mem:001" and mem.statement == "a decision" and mem.why == "because"
    assert mem.alternatives == "the alternative"
    assert mem.concerns[0].sym == SYM and mem.concerns[0].anchor is not None


def test_next_seq_increments_across_captures(tmp_path: Path):
    root = _repo(tmp_path)
    assert memory.next_seq(root) == 1
    _remember(root, "first")
    assert memory.next_seq(root) == 2
    _remember(root, "second")
    assert memory.next_seq(root) == 3


# --------------------------------------------------------------------------------------------------
# Grounding axis (int:memory-grounding, C#6): inferred | docs | empirical, orthogonal to maturity.
# --------------------------------------------------------------------------------------------------


def test_grounding_defaults_to_inferred_and_round_trips(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "a reasoned guess")
    mem = memory.read_memory(memory.find_memory(root, "mem:001"))
    assert mem.grounding == "inferred"  # default: an agent assertion is not yet evidence-backed
    assert _graph(root).nodes["mem:001"]["grounding"] == "inferred"


def test_grounding_override_persists(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "confirmed by a live spike", grounding="empirical")
    assert memory.read_memory(memory.find_memory(root, "mem:001")).grounding == "empirical"


def test_invalid_grounding_is_guided_not_crashed(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["remember", "x", "--repo", str(root), "--grounding", "hunch"])
    assert result.exit_code == 0  # design-law #1: recoverable → exit 0 with guidance, not a stack trace
    assert "--grounding must be one of" in result.output
    assert memory.find_memory(root, "mem:001") is None  # nothing was written


def test_context_shows_grounding_tag(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "empirical decision", grounding="empirical",
              serves=["int:session-expiry"], concerns=[SYM])
    graph, _ = build_graph(root, default_config())
    result = retrieval.context(graph, "empirical decision", default_config())
    assert "mem:001 [decision·empirical]" in result.text


def test_context_grounding_filter_drops_other_tiers(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "an inferred belief", concerns=[SYM])  # inferred (default)
    _remember(root, "an empirical belief", grounding="empirical", concerns=[SYM])
    graph, _ = build_graph(root, default_config())
    result = retrieval.context(graph, "belief", default_config(), grounding="empirical")
    assert "an empirical belief" in result.text
    assert "an inferred belief" not in result.text  # filtered out; only the empirical tier remains


def test_reaffirm_upgrades_grounding_in_place(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "inferred then confirmed", concerns=[SYM])
    assert memory.read_memory(memory.find_memory(root, "mem:001")).grounding == "inferred"
    res = _run(["reaffirm", "mem:001", "--repo", str(root), "--grounding", "empirical"])
    assert "grounding inferred → empirical" in res.output
    # the claim is unchanged (no supersede), only the epistemic status advanced — still mem:001, active
    mem = memory.read_memory(memory.find_memory(root, "mem:001"))
    assert mem.grounding == "empirical" and mem.statement == "inferred then confirmed"


# --------------------------------------------------------------------------------------------------
# Attestation axis (int:memory-attestation): agent|human, trust floor, sticky supersede.
# --------------------------------------------------------------------------------------------------


def _attest_human(root: Path, mem_id: str) -> None:
    """Mark a node human-attested by editing its frontmatter (files are truth; the verb lands in #4)."""
    path = memory.find_memory(root, mem_id)
    node = memory.read_memory(path)
    node.attestation = "human"
    path.write_text(memory.render_memory(node), encoding="utf-8")
    _run(["build", str(root)])


def test_attestation_defaults_agent_and_round_trips(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "a decision")
    assert memory.read_memory(memory.find_memory(root, "mem:001")).attestation == "agent"
    assert _graph(root).nodes["mem:001"]["attestation"] == "agent"


def test_supersede_of_human_attested_node_is_held_pending(tmp_path: Path):
    """int:memory-attestation: an agent supersede of a human-attested node is captured but NOT applied."""
    root = _repo(tmp_path)
    _remember(root, "human-endorsed decision", concerns=[SYM])
    _attest_human(root, "mem:001")
    res = _run(["supersede", "mem:001", "a competing decision", "--repo", str(root)])
    assert "HELD PENDING" in res.output
    g = _graph(root)
    assert g.nodes["mem:001"].get("superseded_in", 0) == 0  # old node stays authoritative (not demoted)
    new = memory.read_memory(memory.find_memory(root, "mem:002"))
    assert new.pending_supersedes == ["mem:001"] and new.supersedes == []  # pending, not applied


def test_agent_supersede_of_agent_node_applies_normally(tmp_path: Path):
    """Control: an agent-attested node supersedes normally (demotes the old) — stickiness is human-only."""
    root = _repo(tmp_path)
    _remember(root, "an agent decision", concerns=[SYM])
    _run(["supersede", "mem:001", "the replacement", "--repo", str(root)])
    g = _graph(root)
    assert g.nodes["mem:001"]["superseded_in"] == 1  # demoted, applied
    assert memory.read_memory(memory.find_memory(root, "mem:002")).supersedes == ["mem:001"]


def test_pending_conflict_surfaces_in_context(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "human decision about refresh", concerns=[SYM], serves=["int:session-expiry"])
    _attest_human(root, "mem:001")
    _run(["supersede", "mem:001", "a new refresh decision", "--concerns", SYM, "--repo", str(root)])
    graph, _ = build_graph(root, default_config())
    text = retrieval.context(graph, "refresh decision", default_config()).text
    assert "Conflict (pending" in text and "pending-supersedes human-attested mem:001" in text


def test_human_attestation_shows_in_the_memory_line(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "endorsed decision about refresh", concerns=[SYM], serves=["int:session-expiry"])
    _attest_human(root, "mem:001")
    graph, _ = build_graph(root, default_config())
    text = retrieval.context(graph, "endorsed decision refresh", default_config()).text
    assert "·human]" in text or "·human·" in text  # the trust-floor marker rides the tag
