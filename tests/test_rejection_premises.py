"""Applicability-conditioned rejected alternatives (task epistemic-control-plane/3).

A rejection outlives the reason it was made: the option ruled out "because we have no Redis" should
stop steering the agent away the moment Redis lands. This is the JTMS in-list / out-list applied to
the "we ruled this out" belief — ``valid_when`` premises must hold, ``invalidated_when`` conditions
must not. Premises are graph locators (``int:``/``mem:``/``sym:``/``file:``) whose liveness yigraf
evaluates at read time (never stored, R6), so surfacing is gated deterministically without an LLM.

Covers: :func:`yigraf.retrieval.premise_holds` per family; the applicability predicate; the two
end-to-end lapse paths (an archived governing intent, a file that appears); content-address stability
(a premise-less node keeps its pre-task-3 id); round-trip; and the guidance for a misused premise.
"""
from pathlib import Path

import networkx as nx
from typer.testing import CliRunner

from yigraf import memory, retrieval
from yigraf.cli import app
from yigraf.config import default_config
from yigraf.extract import build_graph

runner = CliRunner()

SYM = "sym:cache/store.py#get"


def _repo(tmp_path: Path) -> Path:
    """An initialized, built repo with one symbol and one active intent to serve/condition on."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "cache" / "store.py"
    src.parent.mkdir(parents=True)
    src.write_text("def get(key):\n    return key\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["intent", "cache-policy", "--repo", str(tmp_path),
                               "-s", "The cache SHALL stay in-process.",
                               "--scenario", "Given a lookup, When it misses, Then compute in-process.",
                               "--status", "active"]).exit_code == 0
    return tmp_path


def _run(args: list[str]):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result


def _text(root: Path, query: str) -> str:
    """Fresh-from-files context render for ``query`` (build_graph re-reads source + artifacts)."""
    graph, _ = build_graph(root, default_config())
    return retrieval.context(graph, query, default_config()).text


# --------------------------------------------------------------------------------------------------
# premise_holds — the deterministic liveness predicate, per node family
# --------------------------------------------------------------------------------------------------


def _graph(**nodes) -> nx.DiGraph:
    g = nx.DiGraph()
    for nid, attrs in nodes.items():
        g.add_node(nid, **attrs)
    return g


def test_premise_holds_intent_is_true_unless_archived():
    g = _graph(**{"int:a": {"family": "intent", "status": "active"},
                  "int:b": {"family": "intent", "status": "satisfied"},
                  "int:c": {"family": "intent", "status": "archived"}})
    assert retrieval.premise_holds(g, "int:a") is True
    assert retrieval.premise_holds(g, "int:b") is True   # satisfied is still live
    assert retrieval.premise_holds(g, "int:c") is False  # archived = retired/reversed → lapsed


def test_premise_holds_memory_is_false_once_superseded():
    g = _graph(**{"mem:live": {"family": "memory", "superseded_in": 0},
                  "mem:dead": {"family": "memory", "superseded_in": 2}})
    assert retrieval.premise_holds(g, "mem:live") is True
    assert retrieval.premise_holds(g, "mem:dead") is False


def test_premise_holds_structure_locus_holds_while_present():
    g = _graph(**{SYM: {"family": "structure", "kind": "function"}})
    assert retrieval.premise_holds(g, SYM) is True
    assert retrieval.premise_holds(g, "sym:cache/store.py#gone") is False  # absent = gone/hard-drift


def test_premise_holds_absent_ref_never_holds():
    # We never assert a condition we cannot confirm: an unresolved premise ref does NOT hold.
    assert retrieval.premise_holds(_graph(), "int:missing") is False
    assert retrieval.premise_holds(_graph(), "file:nope.tf") is False


# --------------------------------------------------------------------------------------------------
# _rejection_applicable — valid_when (in-list) AND NOT invalidated_when (out-list)
# --------------------------------------------------------------------------------------------------


def test_unconditioned_rejection_always_applies():
    # The pre-task-3 invariant: a rejection with no premises surfaces regardless of graph state.
    assert retrieval._rejection_applicable(_graph(), {"alternatives": "x"}) is True


def test_valid_when_gates_on_every_premise():
    g = _graph(**{"int:a": {"family": "intent", "status": "active"},
                  "int:c": {"family": "intent", "status": "archived"}})
    assert retrieval._rejection_applicable(g, {"rejected_valid_when": ["int:a"]}) is True
    assert retrieval._rejection_applicable(g, {"rejected_valid_when": ["int:a", "int:c"]}) is False


def test_invalidated_when_withdraws_once_any_condition_holds():
    g = _graph(**{"file:redis.tf": {"family": "structure", "kind": "file-anchor"}})
    # present ⇒ the invalidating condition is met ⇒ withdrawn
    assert retrieval._rejection_applicable(g, {"rejected_invalidated_when": ["file:redis.tf"]}) is False
    # absent ⇒ condition not met ⇒ still applies
    assert retrieval._rejection_applicable(_graph(), {"rejected_invalidated_when": ["file:redis.tf"]}) is True


# --------------------------------------------------------------------------------------------------
# End-to-end: the rejection clause appears/vanishes in context as its premises live/lapse
# --------------------------------------------------------------------------------------------------


def test_unconditioned_rejection_surfaces_in_context(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["remember", "store lookups are memoized", "--repo", str(root),
          "--why", "hot path", "--concerns", SYM, "--rejected", "an LRU with a hard cap"])
    assert "(rejected: an LRU with a hard cap)" in _text(root, "store lookups memoized")


def test_valid_when_intent_gates_the_rejection(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["remember", "keep the cache in-process", "--repo", str(root), "--concerns", SYM,
          "--rejected", "a Redis-backed cache", "--rejected-valid-when", "int:cache-policy"])
    shown = _text(root, "keep the cache in-process")
    assert "(rejected: a Redis-backed cache)" in shown  # premise (the intent) is live

    # Reverse the governing goal → the intent is archived → the rejection's premise lapses.
    _run(["intent", "cache-policy", "--repo", str(root), "--status", "archived"])
    lapsed = _text(root, "keep the cache in-process")
    assert "a Redis-backed cache" not in lapsed          # the stale rejection is withheld
    assert "keep the cache in-process" in lapsed          # but the decision itself still surfaces


def test_invalidated_when_file_withdraws_rejection_when_it_appears(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["remember", "compute cache misses in-process", "--repo", str(root), "--concerns", SYM,
          "--rejected", "no Redis in the deploy",
          "--rejected-invalidated-when", "file:infra/redis.tf"])
    assert "(rejected: no Redis in the deploy)" in _text(root, "compute cache misses in-process")

    # Redis lands → the invalidating condition is now true → the rejection is auto-withdrawn.
    (root / "infra").mkdir()
    (root / "infra" / "redis.tf").write_text('resource "redis" {}\n')
    assert "no Redis in the deploy" not in _text(root, "compute cache misses in-process")


# --------------------------------------------------------------------------------------------------
# Content-address stability (memid-v1) + persistence + guidance
# --------------------------------------------------------------------------------------------------


def test_premises_join_the_id_only_when_present():
    args = ("decision", "s", "w", "alt", [], [], [], [])
    base = memory.memory_id(*args)
    # Empty premises must not change the id — a premise-less node keeps its pre-task-3 identity (R1).
    assert memory.memory_id(*args, rejected_valid_when=[], rejected_invalidated_when=[]) == base
    # A premise IS part of the reasoning, so a conditioned rejection is a distinct belief.
    assert memory.memory_id(*args, rejected_valid_when=["int:x"]) != base
    assert memory.memory_id(*args, rejected_invalidated_when=["file:y"]) != base


def test_premises_round_trip_through_the_artifact(tmp_path: Path):
    root = _repo(tmp_path)
    res = _run(["remember", "conditioned decision", "--repo", str(root), "--concerns", SYM,
                "--rejected", "the alt", "--rejected-valid-when", "int:cache-policy",
                "--rejected-invalidated-when", "file:infra/redis.tf"])
    mid = res.output.split("Captured ")[1].split(" ")[0]
    mem = memory.read_memory(memory.find_memory(root, mid))
    assert mem.rejected_valid_when == ["int:cache-policy"]
    assert mem.rejected_invalidated_when == ["file:infra/redis.tf"]
    # graph.json projects them as node attrs only when present.
    node = build_graph(root, default_config())[0].nodes[mid]
    assert node["rejected_valid_when"] == ["int:cache-policy"]


def test_premise_without_a_rejection_is_guided_not_crashed(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["remember", "x", "--repo", str(root),
                                 "--rejected-valid-when", "int:cache-policy"])
    assert result.exit_code == 0  # design-law #1: recoverable → exit 0 with guidance
    assert "--rejected" in result.output
    assert memory.iter_memories(root) == []  # nothing written


def test_non_locator_premise_is_guided_not_crashed(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["remember", "x", "--repo", str(root), "--rejected", "y",
                                 "--rejected-valid-when", "because it was slow"])
    assert result.exit_code == 0
    assert "must be a graph locator" in result.output
    assert memory.iter_memories(root) == []


def test_unresolved_valid_when_soft_warns_but_still_captures(tmp_path: Path):
    root = _repo(tmp_path)
    result = _run(["remember", "x", "--repo", str(root), "--rejected", "y",
                   "--rejected-valid-when", "int:does-not-exist"])
    assert "doesn't resolve" in result.output          # a soft warning (D#3), the edge is still written
    assert len(memory.iter_memories(root)) == 1        # captured despite the warning
