"""Typed edge algebra (:mod:`yigraf.relations`): the confidence semiring, the edge grammar, relation
composition, and typed reachability. Graphs are hand-built (per tests/test_invariants.py) so each case
is cheap and states the property directly."""
import itertools

import networkx as nx

from yigraf import relations as R
from yigraf.relations import AMBIGUOUS, EXTRACTED, INFERRED

_LEVELS = (AMBIGUOUS, INFERRED, EXTRACTED)


# =================================================================================================
# Confidence — the (max, min) bottleneck semiring on the totally-ordered ladder
# =================================================================================================


def test_meet_is_the_weakest_link_join_is_the_best():
    assert R.meet(EXTRACTED, INFERRED) == INFERRED
    assert R.meet(EXTRACTED, AMBIGUOUS) == AMBIGUOUS
    assert R.join(EXTRACTED, INFERRED) == EXTRACTED
    assert R.join(AMBIGUOUS, INFERRED) == INFERRED


def test_semiring_identities():
    """⊗ (meet) identity is the top; ⊕ (join) identity is the bottom."""
    assert R.meet() == EXTRACTED and R.join() == AMBIGUOUS
    for x in _LEVELS:
        assert R.meet(x, EXTRACTED) == x       # top is absorbed by meet
        assert R.join(x, AMBIGUOUS) == x       # bottom is absorbed by join


def test_meet_and_join_are_commutative_and_associative():
    for a, b, c in itertools.product(_LEVELS, repeat=3):
        assert R.meet(a, b) == R.meet(b, a)
        assert R.join(a, b) == R.join(b, a)
        assert R.meet(R.meet(a, b), c) == R.meet(a, R.meet(b, c))
        assert R.join(R.join(a, b), c) == R.join(a, R.join(b, c))


def test_meet_distributes_over_join():
    """The lattice/semiring distributive law that makes best-path-of-bottlenecks well-defined."""
    for a, b, c in itertools.product(_LEVELS, repeat=3):
        assert R.meet(a, R.join(b, c)) == R.join(R.meet(a, b), R.meet(a, c))


def test_combine_path_caps_multihop_derivations_at_inferred():
    assert R.combine_path([EXTRACTED]) == EXTRACTED             # a single asserted hop is not capped
    assert R.combine_path([EXTRACTED, EXTRACTED]) == INFERRED   # a derived 2-hop fact is at most INFERRED
    assert R.combine_path([EXTRACTED, INFERRED]) == INFERRED
    assert R.combine_path([EXTRACTED, AMBIGUOUS]) == AMBIGUOUS  # weakest link still dominates the cap
    assert R.combine_path([]) == EXTRACTED


# =================================================================================================
# The edge grammar — signatures + well_typed
# =================================================================================================


def test_node_types_expose_family_and_family_kind():
    assert R.node_types({"family": "plan", "kind": "task"}) == frozenset({"plan", "plan/task"})
    assert R.node_types({"family": "memory"}) == frozenset({"memory"})
    assert R.node_types({}) == frozenset()


def test_well_typed_accepts_real_signatures():
    task = {"family": "plan", "kind": "task"}
    sym = {"family": "structure", "kind": "function"}
    intent = {"family": "intent", "kind": "intent"}
    mem = {"family": "memory", "kind": "decision"}
    cls = {"family": "structure", "kind": "class"}
    assert R.well_typed("implements", task, sym)
    assert R.well_typed("tracks", task, intent)
    assert R.well_typed("serves", mem, intent)
    assert R.well_typed("concerns", mem, sym)
    assert R.well_typed("calls", sym, cls)          # a constructor call: function -> class
    assert R.well_typed("inherits", cls, cls)


def test_well_typed_rejects_nonsense():
    task = {"family": "plan", "kind": "task"}
    sym = {"family": "structure", "kind": "function"}
    mem = {"family": "memory", "kind": "decision"}
    assert not R.well_typed("implements", mem, sym)   # only a task implements
    assert not R.well_typed("serves", task, sym)      # serves is memory -> intent
    assert not R.well_typed("calls", mem, sym)        # a memory does not call code
    assert not R.well_typed("inherits", sym, sym)     # a function does not inherit


def test_ungoverned_relation_is_fail_open():
    assert R.well_typed("no_such_relation", {"family": "x"}, {"family": "y"})


# =================================================================================================
# Composition — the partial monoid; left-fold semantics because compose is NOT associative
# =================================================================================================


def test_compose_pairs():
    assert R.compose("implements", "calls") == "depends_on"
    assert R.compose("contains", "contains") == "contains"
    assert R.compose("implements", "contains") == "implements"
    assert R.compose("calls", "implements") is None       # a callee has no implements to compose


def test_compose_is_not_associative_so_chains_left_fold():
    # The exact hazard the traversal must respect: the left fold composes, the right fold dead-ends.
    assert R.compose("contains", "calls") is None                       # right fold would stop here
    assert R.compose_chain(["implements", "contains", "calls"]) == "depends_on"  # left fold succeeds
    assert R.compose_chain(["calls", "implements"]) is None
    assert R.compose_chain(["serves"]) == "serves"                      # a single relation is itself
    assert R.compose_chain([]) is None


# =================================================================================================
# Typed reachability — the query composition powers
# =================================================================================================


def _graph() -> nx.DiGraph:
    """A small four-family graph: a task implements ``f``; f→g→h call; a memory concerns f and serves an
    intent the task tracks; a class ``C`` inherits ``D`` (a composition dead-end vs. D's calls)."""
    g = nx.DiGraph()
    def n(nid, family, kind):
        g.add_node(nid, family=family, kind=kind)
    n("task:m/1", "plan", "task")
    n("int:x", "intent", "intent")
    n("mem:1", "memory", "decision")
    n("module:a.py", "structure", "module")
    for s in ("f", "g", "h"):
        n(f"sym:a.py#{s}", "structure", "function")
    n("sym:a.py#C", "structure", "class")
    n("sym:a.py#D", "structure", "class")

    def e(s, t, rel, conf=EXTRACTED):
        g.add_edge(s, t, relation=rel, confidence=conf)
    e("task:m/1", "sym:a.py#f", "implements")
    e("task:m/1", "int:x", "tracks")
    e("sym:a.py#f", "sym:a.py#g", "calls")
    e("sym:a.py#g", "sym:a.py#h", "calls")
    e("module:a.py", "sym:a.py#f", "contains")
    e("mem:1", "sym:a.py#f", "concerns")
    e("mem:1", "int:x", "serves")
    e("sym:a.py#C", "sym:a.py#D", "inherits")
    e("sym:a.py#D", "sym:a.py#g", "calls")   # reachable only if inherits∘calls composed (it does not)
    return g


def _by_target(reaches):
    return {r.target: r for r in reaches}


def test_reach_derives_depends_on_and_caps_confidence():
    got = _by_target(R.reach(_graph(), "task:m/1"))
    # direct, asserted, single-hop — keeps its EXTRACTED confidence
    assert (got["sym:a.py#f"].relation, got["sym:a.py#f"].confidence) == ("implements", EXTRACTED)
    assert (got["int:x"].relation, got["int:x"].confidence) == ("tracks", EXTRACTED)
    # implements ∘ calls ⇒ depends_on, and a derived multi-hop fact is capped at INFERRED
    assert (got["sym:a.py#g"].relation, got["sym:a.py#g"].confidence) == ("depends_on", INFERRED)
    assert got["sym:a.py#g"].depth == 2
    # implements ∘ calls ∘ calls ⇒ still depends_on, at depth 3
    assert (got["sym:a.py#h"].relation, got["sym:a.py#h"].depth) == ("depends_on", 3)
    assert got["sym:a.py#h"].path == ("task:m/1", "sym:a.py#f", "sym:a.py#g", "sym:a.py#h")


def test_reach_prunes_non_composing_paths():
    """From the class ``C``: ``inherits`` reaches ``D``, but ``inherits ∘ calls`` does not compose, so
    D's callee ``g`` is a dead end and never reached — the traversal-pruning that avoids dead walks."""
    got = _by_target(R.reach(_graph(), "sym:a.py#C"))
    assert set(got) == {"sym:a.py#D"}
    assert got["sym:a.py#D"].relation == "inherits"


def test_reach_confidence_floor_drops_inferred():
    """min_confidence=EXTRACTED keeps only asserted single hops; every derived (INFERRED) edge is cut."""
    got = _by_target(R.reach(_graph(), "task:m/1", min_confidence=EXTRACTED))
    assert set(got) == {"sym:a.py#f", "int:x"}


def test_reach_relations_filter_confines_traversal():
    got = _by_target(R.reach(_graph(), "task:m/1", relations={"implements"}))
    assert set(got) == {"sym:a.py#f"}     # cannot cross the calls edges, so depends_on never forms


def test_reach_is_cycle_safe():
    g = _graph()
    g.add_edge("sym:a.py#h", "sym:a.py#f", relation="calls", confidence=EXTRACTED)  # f→g→h→f
    got = _by_target(R.reach(g, "task:m/1"))
    assert set(got) >= {"sym:a.py#f", "sym:a.py#g", "sym:a.py#h"}   # terminates, no revisit blow-up
    for r in got.values():
        assert len(set(r.path)) == len(r.path)                     # every path is simple


def test_reach_is_deterministic():
    a = R.reach(_graph(), "task:m/1")
    b = R.reach(_graph(), "task:m/1")
    assert a == b


# =================================================================================================
# Blast radius — reverse typed reachability to the governed families
# =================================================================================================


def test_blast_radius_of_a_symbol_finds_its_governors():
    """Changing ``f`` directly concerns the task implementing it and the memory pinned to it (its
    container ``module`` is structure, not a governed family, so it is excluded)."""
    got = _by_target(R.blast_radius(_graph(), "sym:a.py#f"))
    assert set(got) == {"task:m/1", "mem:1"}
    assert got["task:m/1"].relation == "implements"
    assert got["mem:1"].relation == "concerns"


def test_blast_radius_reaches_through_a_call_chain_as_depends_on():
    """Changing the deep callee ``h`` transitively reaches the task via implements∘calls∘calls; the
    memory (concerns, which does not compose with calls) is deliberately NOT swept in."""
    got = _by_target(R.blast_radius(_graph(), "sym:a.py#h"))
    assert set(got) == {"task:m/1"}
    assert got["task:m/1"].relation == "depends_on"
    assert got["task:m/1"].path == ("task:m/1", "sym:a.py#f", "sym:a.py#g", "sym:a.py#h")


# =================================================================================================
# Audit — mistyped_edges holds the grammar as an invariant over a built graph
# =================================================================================================


def test_mistyped_edges_empty_on_a_well_formed_graph():
    assert R.mistyped_edges(_graph()) == []


def test_mistyped_edges_reports_violations():
    g = _graph()
    g.add_edge("mem:1", "sym:a.py#f", relation="calls", confidence=EXTRACTED)  # memory cannot call
    assert ("mem:1", "sym:a.py#f", "calls") in R.mistyped_edges(g)


def test_reach_on_absent_start_is_empty():
    assert R.reach(_graph(), "sym:nonexistent") == []
