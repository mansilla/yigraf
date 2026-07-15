"""The memory node family + capture verbs — the M7 done-test (docs/memory-model.md, capture-flow.md).

Covers: ``remember``/``note-constraint``/``supersede`` project memory nodes with their
``serves``/``concerns``/``supersedes`` edges; a ``concerns`` edge is anchored and drift-bearing (the
second drift relation after ``implements``); a rename auto-re-anchors a ``concerns`` edge for free;
supersession materializes the ``superseded_in`` counter and the active decision out-ranks the stale
one; and the decision surfaces in ``context`` / the action-driven hook.
"""
import re
from pathlib import Path

from typer.testing import CliRunner

from yigraf import cli, counters, memory
from yigraf.cli import app
from yigraf.config import default_config, load_config
from yigraf.drift import compute_drift
from yigraf.extract import build_graph
from yigraf import graphdb
from yigraf import retrieval


def _read_with_verdict(root: Path):
    """Read-path graph: overlay the telemetry sidecar (upholds) + resolve the maturity verdict."""
    cfg = load_config(root / "yigraf" / "config.yaml")
    g, _ = build_graph(root, cfg)
    counters.apply_telemetry(g, counters.load_telemetry(root))
    counters.apply_maturity_verdict(g, cfg)
    return g

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
    return graphdb.load_workspace(root)


def _mid(result) -> str:
    """Extract the content-addressed id from a capture verb's ``Captured mem:<id> (...)`` line."""
    return re.search(r"Captured (mem:[0-9a-f]{16})", result.output).group(1)


def _remember(root: Path, statement: str, **opts) -> str:
    args = ["remember", statement, "--repo", str(root)]
    for key in ("type", "why", "rejected", "grounding"):
        if key in opts:
            args += [f"--{key}", opts[key]]
    for target in opts.get("serves", []):
        args += ["--serves", target]
    for sym in opts.get("concerns", []):
        args += ["--concerns", sym]
    for ref in opts.get("evidence", []):
        args += ["--evidence", ref]
    return _mid(_run(args))


# --------------------------------------------------------------------------------------------------
# remember → node + edges + anchor
# --------------------------------------------------------------------------------------------------


def test_remember_projects_a_memory_node_with_its_edges(tmp_path: Path):
    root = _repo(tmp_path)
    mid = _remember(root, "session refresh uses optimistic locking", type="decision",
                    why="refresh path is hot; a retry is cheaper than serializing",
                    serves=["int:session-expiry"], concerns=[SYM], rejected="pessimistic row lock")
    g = _graph(root)
    node = g.nodes[mid]
    assert node["family"] == "memory" and node["kind"] == "decision" and node["status"] == "active"
    assert node["statement"] == "session refresh uses optimistic locking"
    assert node["why"].startswith("refresh path is hot")
    assert node["alternatives"] == "pessimistic row lock"
    assert g.edges[mid, "int:session-expiry"]["relation"] == "serves"
    assert g.edges[mid, SYM]["relation"] == "concerns"


def test_concerns_edge_is_anchored_to_the_symbol_hash(tmp_path: Path):
    root = _repo(tmp_path)
    mid = _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    g = _graph(root)
    edge = g.edges[mid, SYM]
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
    node = memory.read_memory(memory.find_memory(root, _mid(result)))  # captured anyway
    assert node.concerns[0].sym == "sym:auth/session.py#ghost" and node.concerns[0].anchor is None


def test_note_constraint_is_a_promotable_constraint(tmp_path: Path):
    root = _repo(tmp_path)
    mid = _mid(_run(["note-constraint", "refresh() must not block over 50ms", "--concerns", SYM,
                     "--repo", str(root)]))
    node = _graph(root).nodes[mid]
    assert node["kind"] == "constraint" and node["promotable"] is True


# --------------------------------------------------------------------------------------------------
# concerns drift (the second drift-bearing relation)
# --------------------------------------------------------------------------------------------------


def test_editing_concerned_code_surfaces_concerns_drift(tmp_path: Path):
    root = _repo(tmp_path)
    mid = _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")  # body changed
    graph, _ = build_graph(root, default_config())
    items = [i for i in compute_drift(graph) if i.relation == "concerns"]
    assert [i.kind for i in items] == ["soft"]
    assert items[0].task_id == mid and items[0].locator == SYM


def test_concerns_edge_auto_reanchors_on_rename(tmp_path: Path):
    root = _repo(tmp_path)
    mid = _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    (root / SRC).write_text("def renew(token):\n    return token\n")  # pure rename, identical body
    graph, _ = build_graph(root, default_config())
    new = "sym:auth/session.py#renew"
    assert graph.has_edge(mid, new)
    assert graph[mid][new]["relation"] == "concerns"
    assert graph[mid][new]["renamed_from"] == SYM
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
    mid = _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")  # body changed → soft drift
    graph, _ = build_graph(root, default_config())
    assert [i.kind for i in compute_drift(graph) if i.relation == "concerns"] == ["soft"]

    out = _run(["reaffirm", mid, "--repo", str(root)])
    assert "re-anchored" in out.output and SYM in out.output

    graph, _ = build_graph(root, default_config())
    assert [i for i in compute_drift(graph) if i.relation == "concerns"] == []  # drift cleared
    # the anchor now equals the *current* body hash, and the edge/claim is otherwise unchanged
    assert graph.edges[mid, SYM]["anchor"] == graph.nodes[SYM]["content_hash"]
    assert graph.nodes[mid]["statement"] == "refresh keeps the token immutable"
    assert graph.nodes[mid]["status"] == "active"  # no supersede, no new node
    assert len(memory.iter_memories(root)) == 1  # reaffirm re-anchors in place, mints nothing


def test_reaffirm_is_a_noop_when_there_is_no_drift(tmp_path: Path):
    root = _repo(tmp_path)
    mid = _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    out = _run(["reaffirm", mid, "--repo", str(root)])
    assert "already matched" in out.output


def test_reaffirm_unknown_memory_guides_and_exits_zero(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["reaffirm", "mem:999", "--repo", str(root)])
    assert result.exit_code == 0 and "No memory node with id mem:999" in result.output


def test_reaffirm_without_concerns_has_nothing_to_do(tmp_path: Path):
    root = _repo(tmp_path)
    mid = _remember(root, "a decision that governs no specific symbol", serves=["int:session-expiry"])
    result = runner.invoke(app, ["reaffirm", mid, "--repo", str(root)])
    assert result.exit_code == 0 and "concerns no symbol" in result.output


def test_reaffirm_cannot_re_anchor_a_gone_symbol(tmp_path: Path):
    """A deleted symbol is hard drift, not a reaffirm case — guide toward supersede, don't crash."""
    root = _repo(tmp_path)
    mid = _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    (root / SRC).write_text("def unrelated():\n    return 0\n")  # refresh is gone
    out = _run(["reaffirm", mid, "--repo", str(root)])
    assert "no longer resolve" in out.output and "supersede" in out.output


def test_superseded_memory_does_not_drift_on_concerned_code_change(tmp_path: Path):
    root = _repo(tmp_path)
    m1 = _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    m2 = _mid(_run(["supersede", m1, "refresh may rotate the token",
                    "--concerns", SYM, "--repo", str(root)]))
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")  # body changed
    graph, _ = build_graph(root, default_config())
    sources = {i.task_id for i in compute_drift(graph) if i.relation == "concerns"}
    # The active successor still drifts; the superseded predecessor is historical and stays silent.
    assert m2 in sources and m1 not in sources


# --------------------------------------------------------------------------------------------------
# supersede → counters + ranking
# --------------------------------------------------------------------------------------------------


def test_supersede_links_and_marks_the_predecessor_stale(tmp_path: Path):
    root = _repo(tmp_path)
    m1 = _remember(root, "session refresh uses optimistic locking", concerns=[SYM])
    m2 = _mid(_run(["supersede", m1, "session refresh uses pessimistic locking",
                    "--why", "contention is low; a row lock is simpler", "--concerns", SYM,
                    "--repo", str(root)]))
    g = _graph(root)
    assert g.edges[m2, m1]["relation"] == "supersedes"
    assert g.nodes[m1]["superseded_in"] == 1
    assert g.nodes[m2]["supersedes_out"] == 1
    assert g.nodes[m2]["superseded_in"] == 0


def test_active_decision_outranks_its_superseded_predecessor(tmp_path: Path):
    root = _repo(tmp_path)
    m1 = _remember(root, "session refresh uses optimistic locking", concerns=[SYM])
    m2 = _mid(_run(["supersede", m1, "session refresh uses pessimistic locking",
                    "--concerns", SYM, "--repo", str(root)]))
    graph, _ = build_graph(root, default_config())
    result = retrieval.context(graph, "session refresh locking", default_config(), family="memory")
    # Both decisions render; the active successor appears before the superseded predecessor.
    assert result.text.index(m2) < result.text.index(m1)
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
    mid = _remember(root, "session refresh uses optimistic locking", type="decision",
                    why="refresh path is hot", serves=["int:session-expiry"], concerns=[SYM])
    graph, _ = build_graph(root, default_config())
    result = retrieval.context(graph, "optimistic locking refresh", default_config())
    assert "Decisions (why):" in result.text
    assert f"{mid} [decision·inferred]" in result.text  # grounding rides the tag (C#6, default inferred)
    assert "why: refresh path is hot" in result.text


def test_memory_artifact_round_trips(tmp_path: Path):
    root = _repo(tmp_path)
    mid = _remember(root, "a decision", why="because", concerns=[SYM], rejected="the alternative")
    path = memory.find_memory(root, mid)
    assert path is not None
    mem = memory.read_memory(path)
    assert mem.id == mid and mem.statement == "a decision" and mem.why == "because"
    assert mem.alternatives == "the alternative"
    assert mem.concerns[0].sym == SYM and mem.concerns[0].anchor is not None


# --------------------------------------------------------------------------------------------------
# Grounding axis (int:memory-grounding, C#6): inferred | docs | empirical, orthogonal to maturity.
# --------------------------------------------------------------------------------------------------


def test_grounding_defaults_to_inferred_and_round_trips(tmp_path: Path):
    root = _repo(tmp_path)
    mid = _remember(root, "a reasoned guess")
    mem = memory.read_memory(memory.find_memory(root, mid))
    assert mem.grounding == "inferred"  # default: an agent assertion is not yet evidence-backed
    assert _graph(root).nodes[mid]["grounding"] == "inferred"


def test_grounding_override_persists(tmp_path: Path):
    root = _repo(tmp_path)
    mid = _remember(root, "confirmed by a live spike", grounding="empirical", evidence=["commit:abc123"])
    assert memory.read_memory(memory.find_memory(root, mid)).grounding == "empirical"


def test_invalid_grounding_is_guided_not_crashed(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["remember", "x", "--repo", str(root), "--grounding", "hunch"])
    assert result.exit_code == 0  # design-law #1: recoverable → exit 0 with guidance, not a stack trace
    assert "--grounding must be one of" in result.output
    assert memory.iter_memories(root) == []  # nothing was written


def test_context_shows_grounding_tag(tmp_path: Path):
    root = _repo(tmp_path)
    mid = _remember(root, "empirical decision", grounding="empirical",
                    serves=["int:session-expiry"], concerns=[SYM], evidence=["commit:abc123"])
    graph, _ = build_graph(root, default_config())
    result = retrieval.context(graph, "empirical decision", default_config())
    assert f"{mid} [decision·empirical]" in result.text


def test_context_grounding_filter_drops_other_tiers(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "an inferred belief", concerns=[SYM])  # inferred (default)
    _remember(root, "an empirical belief", grounding="empirical", concerns=[SYM],
              evidence=["commit:abc123"])
    graph, _ = build_graph(root, default_config())
    result = retrieval.context(graph, "belief", default_config(), grounding="empirical")
    assert "an empirical belief" in result.text
    assert "an inferred belief" not in result.text  # filtered out; only the empirical tier remains


def test_reaffirm_upgrades_grounding_in_place(tmp_path: Path):
    root = _repo(tmp_path)
    mid = _remember(root, "inferred then confirmed", concerns=[SYM])
    assert memory.read_memory(memory.find_memory(root, mid)).grounding == "inferred"
    res = _run(["reaffirm", mid, "--repo", str(root), "--grounding", "empirical",
                "--evidence", "commit:abc123"])  # empirical now requires naming the observation
    assert "grounding inferred → empirical" in res.output
    # the claim is unchanged (no supersede), only the epistemic status advanced — same node, active
    mem = memory.read_memory(memory.find_memory(root, mid))
    assert mem.grounding == "empirical" and mem.statement == "inferred then confirmed"


# --------------------------------------------------------------------------------------------------
# Maturity landing (task #1): provenance drives the tier a memory ENTERS at.
# --------------------------------------------------------------------------------------------------


def test_landing_maturity_maps_provenance_to_tier():
    """The pure rule: mined/review land proposed; an agent assertion (or no provenance) lands working."""
    assert memory.landing_maturity({"source": "mined"}) == "proposed"
    assert memory.landing_maturity({"source": "review"}) == "proposed"
    assert memory.landing_maturity({"source": "cli"}) == "working"
    assert memory.landing_maturity(None) == "working"


def test_agent_remember_lands_working(tmp_path: Path):
    """An agent-asserted remember lands ``working`` — the shown-nowhere default, full weight."""
    root = _repo(tmp_path)
    mid = _remember(root, "an agent-asserted decision")
    assert memory.read_memory(memory.find_memory(root, mid)).maturity == "working"
    assert _graph(root).nodes[mid]["maturity"] == "working"


def test_proposed_candidate_shows_the_proposed_tag(tmp_path: Path):
    """A mined/review candidate lands proposed and surfaces the ``·proposed`` inline cue (task #1).

    No CLI verb exposes provenance yet (the miner + review bridge land in later tasks), so this drives
    the shared capture helper directly — the landing zone task #1 builds for them to feed."""
    root = _repo(tmp_path)
    node = cli._capture_memory(root, root / "yigraf", statement="a mined candidate", type_="decision",
                               why="", serves=[], concern_syms=[SYM], rejected=None, supersedes=[],
                               promotable=False, provenance={"source": "mined"})
    assert node.maturity == "proposed"
    assert memory.read_memory(memory.find_memory(root, node.id)).maturity == "proposed"
    graph, _ = build_graph(root, default_config())
    result = retrieval.context(graph, "mined candidate", default_config())
    assert f"{node.id} [decision·inferred·proposed]" in result.text


# --------------------------------------------------------------------------------------------------
# propose verb (tasks #5/#6): the review-compound bridge + knowledge miner share one landing path.
# --------------------------------------------------------------------------------------------------


def _propose(root: Path, statement: str, from_: str, **opts):
    args = ["propose", statement, "--from", from_, "--repo", str(root)]
    for key in ("type", "why", "rejected", "grounding", "origin"):
        if key in opts:
            args += [f"--{key}", opts[key]]
    for sym in opts.get("concerns", []):
        args += ["--concerns", sym]
    return _run(args)


def test_propose_review_lands_a_proposed_constraint_anchored_to_the_locus(tmp_path: Path):
    """#5: a confirmed review finding → proposed constraint, anchored (concerns) to the reviewed locus,
    carrying the anti-pattern as the rejected alternative."""
    root = _repo(tmp_path)
    mid = _mid(_propose(root, "never refresh without validating the token first", from_="review",
                        concerns=[SYM], rejected="returning the token unchecked — the current body"))
    node = memory.read_memory(memory.find_memory(root, mid))
    assert node.type == "constraint"           # review defaults to constraint
    assert node.maturity == "proposed"         # lands in quarantine
    assert node.provenance["source"] == "review"
    assert node.alternatives.startswith("returning the token unchecked")
    assert _graph(root).edges[mid, SYM]["relation"] == "concerns"  # anchored to the locus


def test_propose_mined_defaults_to_decision_and_records_origin(tmp_path: Path):
    """#6: a distilled candidate from history → proposed decision; --origin rides the provenance trail."""
    root = _repo(tmp_path)
    mid = _mid(_propose(root, "refresh was made idempotent deliberately", from_="mined",
                        concerns=[SYM], origin="commit abc123"))
    node = memory.read_memory(memory.find_memory(root, mid))
    assert node.type == "decision" and node.maturity == "proposed"
    assert node.provenance == {"source": "mined", "origin": "commit abc123"}


def test_propose_rejects_an_unknown_from(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["propose", "x", "--from", "scraped", "--repo", str(root)])
    assert result.exit_code == 0  # design-law #1: recoverable → exit 0 with guidance
    assert "--from must be one of" in result.output
    assert memory.iter_memories(root) == []  # nothing written


def test_proposed_finding_resurfaces_at_its_locus_via_the_edit_hook(tmp_path: Path):
    """The #5 done-test: the proposed finding is silent in the noise but re-surfaces at the edit hook
    for the exact locus it concerns (int:review-compound: 'at the moment of action')."""
    root = _repo(tmp_path)
    mid = _mid(_propose(root, "never refresh without validating the token first", from_="review",
                        concerns=[SYM]))
    cfg = default_config()
    graph, _ = build_graph(root, cfg)
    result = retrieval.context_for_locus(graph, SRC, cfg)
    assert result is not None and mid in result.text and "·proposed" in result.text


def test_a_real_encounter_confirms_a_proposed_candidate_up_to_working(tmp_path: Path):
    """The compounding payoff: enough survived edit-hook encounters (upholds ≥ maturity_confirm) graduate
    a proposed candidate to working — no new confirm machinery, it reuses the maturity uphold accumulator."""
    root = _repo(tmp_path)
    mid = _mid(_propose(root, "never refresh without validating the token first", from_="review",
                        concerns=[SYM]))
    cfg = default_config()
    assert _read_with_verdict(root).nodes[mid]["maturity"] == "proposed"  # un-encountered
    graph, _ = build_graph(root, cfg)
    counters.record_uphold(root, graph, [mid], cfg["maturity_confirm"])  # one real encounter
    assert _read_with_verdict(root).nodes[mid]["maturity"] == "working"   # confirmed out of quarantine


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
    mid = _remember(root, "a decision")
    assert memory.read_memory(memory.find_memory(root, mid)).attestation == "agent"
    assert _graph(root).nodes[mid]["attestation"] == "agent"


def test_supersede_of_human_attested_node_is_held_pending(tmp_path: Path):
    """int:memory-attestation: an agent supersede of a human-attested node is captured but NOT applied."""
    root = _repo(tmp_path)
    m1 = _remember(root, "human-endorsed decision", concerns=[SYM])
    _attest_human(root, m1)
    res = _run(["supersede", m1, "a competing decision", "--repo", str(root)])
    assert "HELD PENDING" in res.output
    m2 = _mid(res)
    g = _graph(root)
    assert g.nodes[m1].get("superseded_in", 0) == 0  # old node stays authoritative (not demoted)
    new = memory.read_memory(memory.find_memory(root, m2))
    assert new.pending_supersedes == [m1] and new.supersedes == []  # pending, not applied


def test_agent_supersede_of_agent_node_applies_normally(tmp_path: Path):
    """Control: an agent-attested node supersedes normally (demotes the old) — stickiness is human-only."""
    root = _repo(tmp_path)
    m1 = _remember(root, "an agent decision", concerns=[SYM])
    m2 = _mid(_run(["supersede", m1, "the replacement", "--repo", str(root)]))
    g = _graph(root)
    assert g.nodes[m1]["superseded_in"] == 1  # demoted, applied
    assert memory.read_memory(memory.find_memory(root, m2)).supersedes == [m1]


def test_reconcile_wires_an_equivalent_to_edge(tmp_path: Path):
    """reconcile appends `equivalent_to` to the first belief's file (round-trips) and projects it as an
    `equivalent_to` edge — the source-of-truth writer for the reconciliation relation the coherence
    sweep (yigraf.contradiction._reconciled) reads. Both beliefs stay live (no supersede, no demotion)."""
    root = _repo(tmp_path)
    m1 = _remember(root, "first belief about refresh", concerns=[SYM])
    m2 = _remember(root, "a compatible restatement about refresh", concerns=[SYM])
    _run(["reconcile", m1, m2, "--repo", str(root)])

    assert memory.read_memory(memory.find_memory(root, m1)).equivalent_to == [m2]  # round-trips
    g = _graph(root)
    assert g.edges[m1, m2]["relation"] == "equivalent_to"  # projected
    assert not g.nodes[m1].get("superseded_in") and not g.nodes[m2].get("superseded_in")  # both live


def test_reconcile_guards_unknown_and_self(tmp_path: Path):
    """Recoverable misuse exits 0 with guidance (design law #1), never a crash."""
    root = _repo(tmp_path)
    m1 = _remember(root, "only belief", concerns=[SYM])
    unknown = runner.invoke(app, ["reconcile", m1, "mem:0000000000000000", "--repo", str(root)])
    assert unknown.exit_code == 0 and "No memory node" in unknown.output
    itself = runner.invoke(app, ["reconcile", m1, m1, "--repo", str(root)])
    assert itself.exit_code == 0 and "can't be reconciled with itself" in itself.output


def test_pending_conflict_surfaces_in_context(tmp_path: Path):
    root = _repo(tmp_path)
    # Regression guard for the two-pass projection (mem:063): the SUCCESSOR's slug sorts BEFORE the
    # predecessor's ("aaa…" < "zzz…"), so with content-addressed (<slug>-<hash>.md) filenames the
    # superseding node is read/projected first — its ``pending`` supersedes edge points at a
    # predecessor not yet in the graph. A one-pass projection would stash it as dangling and drop the
    # conflict; the two-pass project_into must resolve it regardless of on-disk order.
    m1 = _remember(root, "zzz human decision about refresh", concerns=[SYM],
                   serves=["int:session-expiry"])
    _attest_human(root, m1)
    _run(["supersede", m1, "aaa new refresh decision", "--concerns", SYM, "--repo", str(root)])
    graph, _ = build_graph(root, default_config())
    text = retrieval.context(graph, "refresh decision", default_config()).text
    assert "Conflict (pending" in text and f"pending-supersedes human-attested {m1}" in text


def test_human_attestation_shows_in_the_memory_line(tmp_path: Path):
    root = _repo(tmp_path)
    mid = _remember(root, "endorsed decision about refresh", concerns=[SYM], serves=["int:session-expiry"])
    _attest_human(root, mid)
    graph, _ = build_graph(root, default_config())
    text = retrieval.context(graph, "endorsed decision refresh", default_config()).text
    assert "·human]" in text or "·human·" in text  # the trust-floor marker rides the tag


# --------------------------------------------------------------------------------------------------
# Elicitation / human-attestation entry (int:intent-elicitation): the `attest` verb.
# --------------------------------------------------------------------------------------------------


def test_attest_marks_a_memory_human(tmp_path: Path):
    root = _repo(tmp_path)
    mid = _remember(root, "a decision")
    res = _run(["attest", mid, "--repo", str(root)])
    assert "human" in res.output
    assert _graph(root).nodes[mid]["attestation"] == "human"


def test_attest_marks_an_intent_human_and_shows_in_context(tmp_path: Path):
    """The elicitation capture: the principal's answer is persisted as a human-attested intent (mem:032)."""
    root = _repo(tmp_path)
    _run(["attest", "int:session-expiry", "--repo", str(root)])
    graph, _ = build_graph(root, default_config())
    assert graph.nodes["int:session-expiry"]["attestation"] == "human"
    text = retrieval.context(graph, "session expire idle", default_config()).text
    assert "·human]" in text  # the trust-floor marker rides the intent tag


def test_attest_applies_a_pending_supersede_and_demotes_the_old(tmp_path: Path):
    """The full sticky cycle: human node → agent supersede (pending) → attest the new → applied."""
    root = _repo(tmp_path)
    m1 = _remember(root, "human-endorsed decision", concerns=[SYM])
    _run(["attest", m1, "--repo", str(root)])                          # m1 human-attested
    m2 = _mid(_run(["supersede", m1, "the competing view", "--repo", str(root)]))  # m2 pending
    assert _graph(root).nodes[m1].get("superseded_in", 0) == 0         # not demoted yet
    res = _run(["attest", m2, "--repo", str(root)])                    # principal accepts the change
    assert "Applied the held supersede" in res.output
    g = _graph(root)
    assert g.nodes[m1]["superseded_in"] == 1                           # now demoted
    new = memory.read_memory(memory.find_memory(root, m2))
    assert new.supersedes == [m1] and new.pending_supersedes == []  # pending → applied


def test_attest_unknown_target_is_guided(tmp_path: Path):
    root = _repo(tmp_path)
    assert "No memory node" in _run(["attest", "mem:404", "--repo", str(root)]).output
    assert "No intent" in _run(["attest", "int:nope", "--repo", str(root)]).output


# --------------------------------------------------------------------------------------------------
# grounded_by evidence + evidence-drift (int:memory-grounding): the empirical tier must NAME a live
# observation, and a locus evidence rides the same drift machinery as concerns.
# --------------------------------------------------------------------------------------------------

EV_SYM = "sym:auth/session.py#verify"


def _add_evidence_symbol(root: Path, body: str = "    return x\n") -> str:
    """Add a second symbol (``verify``) to the source to serve as a drift-checkable evidence locus,
    keeping ``refresh`` (the usual concern) intact so only the evidence drifts when we edit it."""
    (root / SRC).write_text(f"def refresh(token):\n    return token\n\n\ndef verify(x):\n{body}")
    _run(["build", str(root)])
    return EV_SYM


def test_remember_empirical_without_evidence_is_guided(tmp_path: Path):
    """The empirical tier is a claim about a live observation — it must name one, or exit 0 + guidance."""
    root = _repo(tmp_path)
    result = runner.invoke(app, ["remember", "confirmed by a spike", "--grounding", "empirical",
                                 "--repo", str(root)])
    assert result.exit_code == 0  # design-law #1: recoverable → guidance, not a crash
    assert "--grounding empirical means confirmed by a live observation" in result.output
    assert memory.iter_memories(root) == []  # nothing written — the claim was unearned


def test_evidence_locus_projects_an_anchored_grounded_by_edge(tmp_path: Path):
    root = _repo(tmp_path)
    ev = _add_evidence_symbol(root)
    mid = _remember(root, "refresh is idempotent", grounding="empirical", concerns=[SYM], evidence=[ev])
    g = _graph(root)
    edge = g.edges[mid, ev]
    assert edge["relation"] == "grounded_by"
    assert edge["anchor"] == g.nodes[ev]["content_hash"]  # freshly captured → anchored, no drift


def test_opaque_evidence_is_recorded_but_not_an_edge(tmp_path: Path):
    root = _repo(tmp_path)
    mid = _remember(root, "matches the RFC", grounding="empirical", evidence=["commit:abc123"])
    g = _graph(root)
    assert not any(a.get("relation") == "grounded_by" for _, _, a in g.out_edges(mid, data=True))
    assert g.nodes[mid]["opaque_evidence"] == ["commit:abc123"]  # recorded, never drifts


def test_editing_evidence_surfaces_grounded_by_drift(tmp_path: Path):
    root = _repo(tmp_path)
    ev = _add_evidence_symbol(root)
    mid = _remember(root, "refresh is idempotent", grounding="empirical", concerns=[SYM], evidence=[ev])
    _add_evidence_symbol(root, body="    return x + 1\n")  # the evidence's body changed
    graph, _ = build_graph(root, default_config())
    items = [i for i in compute_drift(graph) if i.relation == "grounded_by"]
    assert [i.kind for i in items] == ["soft"] and items[0].task_id == mid
    concerns_items = [i for i in compute_drift(graph) if i.relation == "concerns"]
    assert concerns_items == []  # the concern (refresh) is untouched — only the evidence drifted


def test_renaming_evidence_reanchors_without_drift(tmp_path: Path):
    root = _repo(tmp_path)
    ev = _add_evidence_symbol(root)
    mid = _remember(root, "refresh is idempotent", grounding="empirical", concerns=[SYM], evidence=[ev])
    # Rename the evidence symbol (same body) — the anchor excludes the name, so it re-anchors for free.
    (root / SRC).write_text("def refresh(token):\n    return token\n\n\ndef verify_renamed(x):\n    return x\n")
    graph, _ = build_graph(root, default_config())
    assert [i for i in compute_drift(graph) if i.relation == "grounded_by" and i.kind != "renamed"] == []
    assert graph.edges[mid, "sym:auth/session.py#verify_renamed"]["relation"] == "grounded_by"


def test_reaffirm_evidence_clears_grounds_drift(tmp_path: Path):
    root = _repo(tmp_path)
    ev = _add_evidence_symbol(root)
    mid = _remember(root, "refresh is idempotent", grounding="empirical", concerns=[SYM], evidence=[ev])
    _add_evidence_symbol(root, body="    return x + 1\n")  # evidence drifts
    res = _run(["reaffirm", mid, "--repo", str(root), "--grounding", "empirical", "--evidence", ev])
    assert "grounds-drift cleared" in res.output
    graph, _ = build_graph(root, default_config())
    assert [i for i in compute_drift(graph) if i.relation == "grounded_by"] == []  # re-anchored


def test_reaffirm_to_empirical_without_evidence_is_guided(tmp_path: Path):
    """Closes the loophole: upgrading grounding to empirical in place also requires naming evidence."""
    root = _repo(tmp_path)
    mid = _remember(root, "inferred belief", concerns=[SYM])  # inferred, no evidence
    result = runner.invoke(app, ["reaffirm", mid, "--repo", str(root), "--grounding", "empirical"])
    assert result.exit_code == 0
    assert "--grounding empirical requires naming the observation" in result.output
    assert memory.read_memory(memory.find_memory(root, mid)).grounding == "inferred"  # unchanged


def test_context_shows_grounded_evidence(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "refresh is idempotent", grounding="empirical", concerns=[SYM],
              evidence=["commit:abc123"])
    graph, _ = build_graph(root, default_config())
    result = retrieval.context(graph, "idempotent", default_config())
    assert "[grounded: commit:abc123]" in result.text


# --------------------------------------------------------------------------------------------------
# Content-addressed ids (memid-v1, task:concurrent-write-v1/1, mem:063) — the seq counter's replacement
# --------------------------------------------------------------------------------------------------


def test_memory_id_is_content_addressed_not_sequential(tmp_path: Path):
    """A remembered memory is keyed by a content hash (mem:<16 hex>), never the old mem:NNN counter."""
    root = _repo(tmp_path)
    mid = _remember(root, "session refresh uses optimistic locking", why="hot path")
    assert re.fullmatch(r"mem:[0-9a-f]{16}", mid), mid
    assert mid in _graph(root).nodes


def test_identical_payloads_collapse_to_one_id():
    """Two agents asserting the SAME decision mint the SAME id (int:concurrent-write-model, mem:060)."""
    args = ("decision", "orders use optimistic locking", "hot path", "row lock",
            ["int:x"], ["sym:o#u"], [], [])
    assert memory.memory_id(*args) == memory.memory_id(*args)
    # link lists are order-independent (sorted into the hash)
    a = memory.memory_id("decision", "s", "w", None, ["int:a", "int:b"], ["sym:x", "sym:y"], [], [])
    b = memory.memory_id("decision", "s", "w", None, ["int:b", "int:a"], ["sym:y", "sym:x"], [], [])
    assert a == b


def test_different_reasoning_yields_a_different_id():
    """Identity spans the whole payload: same-claim-different-why diverges (conservative collapse, mem:063)."""
    base = memory.memory_id("decision", "s", "why one", None, [], [], [], [])
    assert base != memory.memory_id("decision", "s", "why two", None, [], [], [], [])
    assert base != memory.memory_id("decision", "s2", "why one", None, [], [], [], [])
    assert base != memory.memory_id("constraint", "s", "why one", None, [], [], [], [])


def test_minted_id_matches_the_payload_hash(tmp_path: Path):
    """The on-disk id is exactly memory_id() over the captured payload — no hidden inputs (provenance/ts)."""
    root = _repo(tmp_path)
    mid = _remember(root, "refresh keeps the token immutable", why="callers rely on it",
                    concerns=[SYM], rejected="mutate in place", serves=["int:session-expiry"])
    expected = memory.memory_id("decision", "refresh keeps the token immutable",
                                "callers rely on it", "mutate in place",
                                ["int:session-expiry"], [SYM], [], [])
    assert mid == expected


def test_legacy_seq_id_file_is_grandfathered(tmp_path: Path):
    """A pre-memid NNN-slug.md carrying an explicit id: mem:NNN still resolves and projects unchanged."""
    root = _repo(tmp_path)
    legacy = root / "yigraf" / "memory" / "007-legacy.md"
    legacy.write_text(
        "---\nid: mem:007\nfamily: memory\ntype: decision\nstatus: active\n"
        "maturity: working\ngrounding: inferred\nattestation: agent\n"
        "serves: []\nconcerns: []\nsupersedes: []\nprovenance:\n  source: cli\n---\n"
        "## a legacy decision\n\n**Why:** captured before memid-v1\n",
        encoding="utf-8")
    assert memory.find_memory(root, "mem:007") == legacy
    _run(["build", str(root)])
    assert "mem:007" in _graph(root).nodes
