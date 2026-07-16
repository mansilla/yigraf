"""Property-based invariant suite (epistemic-control-plane #7).

The task's named invariants, each stated as a property Hypothesis quantifies over instead of a single
example — the load-bearing guarantees of the epistemic control plane that a point-test could miss:

  1. budget reduction never drops the sole explanation of a shown conflict  (retrieval pinning, task #4)
  2. pure rename preserves anchors                                          (astnorm-v1, M3)
  3. an unrelated assertion does not change the packet                      (locus-local retrieval)

plus the algebra of the provenance-typed revision order (task #6): a *partial* order that never breaks a
same-tier tie (the mem:062 no-last-writer-wins guarantee), and is antisymmetric + transitive.

Graphs are hand-built (per tests/test_reserved_budget.py) so each example is cheap; Hypothesis can then
run hundreds of them. ``deadline=None`` because the first example warms tree-sitter / imports.
"""
import keyword

import networkx as nx
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from tree_sitter import Parser

from yigraf import retrieval, revision
from yigraf.astnorm import content_hash  # noqa: F401  (kept explicit: the rule under test)
from yigraf.config import default_config
from yigraf.extract import _PY_LANGUAGE, extract_file

_PARSER = Parser(_PY_LANGUAGE)


# =================================================================================================
# Invariant: the provenance-typed revision order is a strict PARTIAL order (task #6)
# =================================================================================================

# A belief node as retrieval sees it — every axis the classifier reads, drawn independently so the
# strategy covers cross-family combinations (a human-attested structure node, an empirical decision, …).
_belief = st.fixed_dictionaries({
    "family": st.sampled_from(["memory", "intent", "plan", "structure", "other"]),
    "attestation": st.sampled_from(["agent", "human"]),
    "grounding": st.sampled_from(["inferred", "docs", "empirical"]),
    "kind": st.sampled_from(["decision", "constraint", "rationale", "learned-fact", "preference"]),
})


@given(a=_belief)
@settings(deadline=None)
def test_dominance_is_irreflexive(a):
    """No belief dominates itself — same provenance is always incomparable."""
    assert not revision.dominates(a, a)


@given(a=_belief, b=_belief)
@settings(deadline=None)
def test_dominance_is_antisymmetric(a, b):
    """At most one side dominates — the order can never say both A>B and B>A (which would let a resolution
    pick either, i.e. last-writer-wins)."""
    assert not (revision.dominates(a, b) and revision.dominates(b, a))


@given(a=_belief, b=_belief)
@settings(deadline=None)
def test_same_tier_beliefs_are_incomparable(a, b):
    """The partial-order heart of mem:062: equal provenance ⇒ no winner (held open for a human), never a
    scalar tiebreak."""
    if revision.classify(a) == revision.classify(b):
        assert not revision.dominates(a, b)
        assert revision.dominant_id("mem:a", a, "mem:b", b) is None


@given(a=_belief, b=_belief, c=_belief)
@settings(deadline=None)
def test_dominance_is_transitive(a, b, c):
    if revision.dominates(a, b) and revision.dominates(b, c):
        assert revision.dominates(a, c)


@given(a=_belief, b=_belief)
@settings(deadline=None)
def test_dominant_id_agrees_with_dominates_and_is_order_independent(a, b):
    """Whatever ``dominant_id`` returns is exactly the strictly-higher side, and swapping the arguments
    returns the same belief — the guidance can't depend on argument (insertion) order."""
    forward = revision.dominant_id("mem:a", a, "mem:b", b)
    backward = revision.dominant_id("mem:b", b, "mem:a", a)
    assert forward == backward
    if revision.dominates(a, b):
        assert forward == "mem:a"
    elif revision.dominates(b, a):
        assert forward == "mem:b"
    else:
        assert forward is None


# =================================================================================================
# Invariant 1: budget reduction never drops the sole explanation of a shown conflict (task #4/#7)
# =================================================================================================

_CONFLICT_BODY = "UNIQUE_CONFLICT_BODY"
# A signal line that names the pinned memory — the *explanation* of a shown conflict the render must keep.
_CONFLICT_LINE = ["  ⚠ mem:new pending-supersedes human-attested mem:conflicted — resolve by attesting it."]


def _render(graph, ranked, budget_tokens, **kw):
    return retrieval._render(graph, ranked, "q", [], [], budget_tokens, config=default_config(), **kw)


def _mem_flood(g: nx.DiGraph, n: int) -> list[str]:
    ids = []
    for i in range(n):
        nid = f"mem:m{i:02d}"
        g.add_node(nid, family="memory", kind="decision", statement="filler_decision_body")
        ids.append(nid)
    return ids


@given(flood=st.integers(min_value=0, max_value=40), budget=st.integers(min_value=40, max_value=400))
@settings(deadline=None, max_examples=200)
def test_a_flood_never_evicts_a_pinned_conflict_explanation(flood, budget):
    """Whenever the budget admits the conflicted belief *at all* (measured with no flood), it still renders
    with any number of higher-ranked same-family beliefs crowding ahead of it — because a shown signal
    line names it, so the render pins it first. Quantified over flood size and budget, this is the
    invariant the point-test in test_reserved_budget checks at one operating point."""
    g0 = nx.DiGraph()
    g0.add_node("mem:conflicted", family="memory", kind="decision", statement=_CONFLICT_BODY)
    baseline = _render(g0, ["mem:conflicted"], budget, conflict_lines=_CONFLICT_LINE)
    assume(_CONFLICT_BODY in baseline.text)  # only assert the invariant where the budget admits the pin

    g = nx.DiGraph()
    flood_ids = _mem_flood(g, flood)
    g.add_node("mem:conflicted", family="memory", kind="decision", statement=_CONFLICT_BODY)
    ranked = flood_ids + ["mem:conflicted"]  # the pin ranks LAST, behind its whole family
    crowded = _render(g, ranked, budget, conflict_lines=_CONFLICT_LINE)
    assert _CONFLICT_BODY in crowded.text


# =================================================================================================
# Invariant 2: pure rename preserves anchors (astnorm-v1, M3)
# =================================================================================================

_IDENT = st.from_regex(r"[a-z][a-z0-9_]{0,12}", fullmatch=True).filter(lambda s: not keyword.iskeyword(s))


def _fn_anchor(name: str, body_k: int) -> tuple[str, str]:
    """Extract ``(node_id, content_hash)`` for ``def <name>(a): return a + <body_k>``."""
    src = f"def {name}(a):\n    return a + {body_k}\n".encode()
    proj = extract_file("m.py", src, _PARSER)
    nid = f"sym:m.py#{name}"
    return nid, proj.nodes[nid]["content_hash"]


@given(name1=_IDENT, name2=_IDENT, body_k=st.integers(min_value=0, max_value=9999))
@settings(deadline=None, max_examples=150)
def test_pure_rename_preserves_the_anchor(name1, name2, body_k):
    """Renaming a symbol's own declared name leaves its body anchor byte-identical (the symbol's name is
    dropped from the hash, astnorm-v1) — so M3 can re-anchor a renamed symbol by exact match — even though
    the node id, which embeds the name, does change."""
    id1, h1 = _fn_anchor(name1, body_k)
    id2, h2 = _fn_anchor(name2, body_k)
    assert h1 == h2
    if name1 != name2:
        assert id1 != id2


@given(name=_IDENT, k1=st.integers(min_value=0, max_value=9999), k2=st.integers(min_value=0, max_value=9999))
@settings(deadline=None, max_examples=100)
def test_a_body_change_does_flip_the_anchor(name, k1, k2):
    """Control for the rename invariant: a real body edit (a different literal) DOES change the anchor, so
    the rename test isn't passing vacuously."""
    assume(k1 != k2)
    _, h1 = _fn_anchor(name, k1)
    _, h2 = _fn_anchor(name, k2)
    assert h1 != h2


# =================================================================================================
# Invariant 3: an unrelated assertion does not change the packet (locus-local retrieval)
# =================================================================================================

_GOV_BODY = "GOVERNING_DECISION_BODY"


def _governed_graph() -> nx.DiGraph:
    """A file governed by one decision — the minimal graph for which the edit hook emits a packet."""
    g = nx.DiGraph()
    g.add_node("sym:app/f.py#f", family="structure", kind="function", signature="def f(): ...")
    g.add_node("mem:gov", family="memory", kind="decision", status="active", superseded_in=0,
               statement=_GOV_BODY)
    g.add_edge("mem:gov", "sym:app/f.py#f", relation="concerns")
    return g


@given(
    noise_id=st.from_regex(r"mem:[a-z0-9]{4,10}", fullmatch=True),
    stmt=st.text(min_size=1, max_size=60),
    kind=st.sampled_from(["decision", "constraint", "learned-fact", "preference"]),
)
@settings(deadline=None, max_examples=150)
def test_an_unrelated_assertion_does_not_change_the_locus_packet(noise_id, stmt, kind):
    """The edit-hook packet for a file is a function of that file's neighborhood alone: adding a memory
    that concerns a DIFFERENT, disconnected symbol never alters (nor intrudes on) it. Guards against a
    global-state leak — the packet must not depend on the rest of the corpus."""
    assume(noise_id != "mem:gov")
    cfg = default_config()
    base = retrieval.context_for_locus(_governed_graph(), "app/f.py", cfg)
    assert base is not None  # the file is governed → the hook speaks

    g = _governed_graph()
    g.add_node("sym:other/g.py#g", family="structure", kind="function")  # a different file, unlinked
    g.add_node(noise_id, family="memory", kind=kind, status="active", superseded_in=0, statement=stmt)
    g.add_edge(noise_id, "sym:other/g.py#g", relation="concerns")
    after = retrieval.context_for_locus(g, "app/f.py", cfg)

    assert after.text == base.text
