"""Typed edge algebra: an edge grammar + a bottleneck confidence semiring + relation composition.

yigraf's arrows already carry an *implicit* signature — ``implements`` goes ``task → sym``, ``serves``
goes ``memory → intent``, ``calls`` goes ``function → function`` — but nothing named the type, so the
graph could not (a) reject a nonsensical edge or (b) *derive* a relation that no writer asserted. This
module makes that type system explicit and gives it two operations an agent's queries need:

- **composition** (the category-theory payoff, not lambda calculus): a partial ``compose(r1, r2)`` says
  what relation you get by following an ``r1`` edge then an ``r2`` edge. ``implements ∘ calls`` ⇒ a task
  *depends_on* whatever its implementing symbols call — a fact nobody wrote down but that the graph
  entails. Composition is what turns "who is transitively affected if this symbol changes?" from a
  hand-rolled traversal into one typed reachability query, and its partiality is what prunes dead-end
  walks: a path that stops composing is not explored further.
- **a confidence semiring** over the ``EXTRACTED > INFERRED > AMBIGUOUS`` ladder (the ladder Graphify
  defined but yigraf only ever emitted the top rung of). Along a path confidence is the *weakest link*
  (``meet`` = min); across alternative paths it is the *best* (``join`` = max) — the (max, min)
  bottleneck semiring on a totally-ordered lattice. A *derived* (multi-hop) edge is capped at
  ``INFERRED``: a logical consequence of asserted facts is never itself an asserted fact, and a query
  must be able to tell "someone linked this" from "the graph inferred this."

Everything here is **read-time and pure** — no assertion, no storage. Files are truth and the graph is
a derived projection (CLAUDE.md R1/R6); a *derived* relation must not be persisted or it would look
like a claim. :func:`well_typed` is the reusable predicate a write boundary can call to refuse a
malformed edge with guidance (design law #1), and :func:`mistyped_edges` is the read-time audit that
holds the invariant over an already-built graph — neither mutates the fold, which stays a pure
materialization (:mod:`yigraf.fold`).
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import networkx as nx

# --------------------------------------------------------------------------------------------------
# Confidence — a bottleneck semiring on the totally-ordered ladder (Graphify's EXTRACTED|INFERRED|
# AMBIGUOUS). ``meet`` (⊗) is the weakest link along a path; ``join`` (⊕) is the best across paths.
# --------------------------------------------------------------------------------------------------

EXTRACTED = "EXTRACTED"  # asserted at a boundary: a tree-sitter fact or an authored link
INFERRED = "INFERRED"    # entailed by composition — never asserted by a writer
AMBIGUOUS = "AMBIGUOUS"  # a hop that could not be pinned down

#: Rank in the lattice; higher = more trustworthy. Unknown strings sink to the bottom (fail-safe).
_RANK = {AMBIGUOUS: 0, INFERRED: 1, EXTRACTED: 2}


def meet(*confs: str) -> str:
    """The ⊗ of the semiring — the *weakest link*. Identity (no args) is the top, ``EXTRACTED``."""
    return min(confs, key=lambda c: _RANK.get(c, 0)) if confs else EXTRACTED


def join(*confs: str) -> str:
    """The ⊕ of the semiring — the *best* of several paths. Identity (no args) is ``AMBIGUOUS``."""
    return max(confs, key=lambda c: _RANK.get(c, 0)) if confs else AMBIGUOUS


def combine_path(confs: Sequence[str]) -> str:
    """Confidence of a whole path: the weakest hop, and — for a *derived* multi-hop path — never above
    ``INFERRED``. A single asserted hop keeps its own confidence; a composition of two facts is a
    consequence, not a fact, so it caps out one rung down (lets a query separate asserted from derived).
    """
    confs = tuple(confs)
    if not confs:
        return EXTRACTED
    m = meet(*confs)
    return m if len(confs) == 1 else meet(m, INFERRED)


def stronger(a: str, b: str) -> bool:
    """``True`` if confidence ``a`` outranks ``b``."""
    return _RANK.get(a, 0) > _RANK.get(b, 0)


# --------------------------------------------------------------------------------------------------
# The edge grammar — each relation's allowed (source type → target type). A "type" is a node's family
# (``memory``) or its ``family/kind`` (``plan/task``, ``structure/function``); an endpoint set matches
# if it shares any tag, so a family-level entry (``structure``) admits every structure kind.
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Signature:
    """Allowed endpoint types for a relation, as sets of ``family`` / ``family/kind`` tags."""

    sources: frozenset[str]
    targets: frozenset[str]


_STRUCT = frozenset({"structure"})                       # any structure node (file/module/sym/anchor)
_FILE = frozenset({"structure/file"})
_CLASSLIKE = frozenset({"structure/class", "structure/type"})
_CALLER = frozenset({"structure/function", "structure/method", "structure/class"})
_CALLEE = frozenset({"structure/function", "structure/method", "structure/class", "structure/type"})
_TASK = frozenset({"plan/task"})
_MEMORY = frozenset({"memory"})
_INTENT = frozenset({"intent"})
_REVISABLE = frozenset({"memory", "intent"})             # supersedes is same-family belief revision

#: The typed edge grammar. Structure endpoints are grounded in yigraf's own built graph (the observed
#: ``calls``/``contains``/``imports``/``inherits`` endpoint kinds); cross-family endpoints mirror what
#: :mod:`yigraf.artifacts` / :mod:`yigraf.memory` / :mod:`yigraf.filelog` actually emit.
SIGNATURES: dict[str, Signature] = {
    # structure (tree-sitter extraction)
    "contains": Signature(_STRUCT, _STRUCT),        # nesting: file→module→sym→sym
    "calls": Signature(_CALLER, _CALLEE),           # a callee may be a class (constructor call)
    "imports": Signature(_FILE, _FILE),
    "inherits": Signature(_CLASSLIKE, _CLASSLIKE),
    # plan → {structure, intent, plan}
    "implements": Signature(_TASK, _STRUCT),        # target is a sym or a synthetic file-anchor
    "tracks": Signature(_TASK, _INTENT),
    "requires": Signature(_TASK, _TASK),
    # memory → {intent, structure, memory}
    "serves": Signature(_MEMORY, _INTENT),
    "concerns": Signature(_MEMORY, _STRUCT),
    "grounded_by": Signature(_MEMORY, _STRUCT),
    "equivalent_to": Signature(_MEMORY, _MEMORY),
    # belief revision (same-family; the fold marks the target superseded)
    "supersedes": Signature(_REVISABLE, _REVISABLE),
    # DERIVED-ONLY (never asserted, only produced by composition — see COMPOSE / DERIVED_RELATIONS)
    "depends_on": Signature(_TASK, _STRUCT),
}

#: Relations that only ever arise from :func:`compose` — a writer must never assert them. A write
#: boundary can reject one with guidance; the fold never sees them (they are not in any body).
DERIVED_RELATIONS = frozenset({"depends_on"})


def node_types(attrs: dict) -> frozenset[str]:
    """The type tags of a node: ``{family, "family/kind"}`` (or just ``{family}`` when kind is absent)."""
    family = attrs.get("family")
    if not family:
        return frozenset()
    kind = attrs.get("kind")
    return frozenset({family, f"{family}/{kind}"}) if kind else frozenset({family})


def well_typed(relation: str, source_attrs: dict, target_attrs: dict) -> bool:
    """Whether an edge respects its relation's signature. A relation with *no* signature is ungoverned
    and passes (fail-open, CLAUDE.md #5) — the type system only rejects what it explicitly knows."""
    sig = SIGNATURES.get(relation)
    if sig is None:
        return True
    return bool(node_types(source_attrs) & sig.sources) and bool(node_types(target_attrs) & sig.targets)


# --------------------------------------------------------------------------------------------------
# Composition — the partial monoid on relations. ``compose(r1, r2)`` is the relation of an r1-then-r2
# two-hop path, or ``None`` when the path does not compose (⇒ the traversal prunes it). NOT associative
# (``implements∘contains∘calls`` left-folds to ``depends_on`` but ``contains∘calls`` alone is ``None``),
# so a path's relation is defined as the LEFT fold of its forward relation sequence (:func:`compose_chain`).
# --------------------------------------------------------------------------------------------------

COMPOSE: dict[tuple[str, str], str] = {
    # transitive closures (a relation composed with itself)
    ("contains", "contains"): "contains",       # file contains module contains fn ⇒ file contains fn
    ("calls", "calls"): "calls",                # transitive call reachability
    ("requires", "requires"): "requires",       # prerequisite chain
    ("supersedes", "supersedes"): "supersedes",  # revision chain (new supersedes old supersedes older)
    # cross-family propagation into structure
    ("implements", "contains"): "implements",   # task implements a container ⇒ implements its members
    ("concerns", "contains"): "concerns",       # a memory pinned to a file is pinned to its members
    # the blast-radius entailment: what a task's code depends on
    ("implements", "calls"): "depends_on",
    ("depends_on", "calls"): "depends_on",
    ("depends_on", "contains"): "depends_on",
}


def compose(r1: str, r2: str) -> str | None:
    """The relation of an ``r1``-then-``r2`` path, or ``None`` if the two do not compose."""
    return COMPOSE.get((r1, r2))


def compose_chain(relations: Sequence[str]) -> str | None:
    """Left-fold :func:`compose` over a forward relation sequence — the relation of the whole path,
    or ``None`` if any step fails to compose. Empty ⇒ ``None``; a single relation ⇒ itself."""
    it = iter(relations)
    try:
        acc = next(it)
    except StopIteration:
        return None
    for r in it:
        acc = compose(acc, r)
        if acc is None:
            return None
    return acc


# --------------------------------------------------------------------------------------------------
# Typed reachability — the query composition powers: follow only well-typed, composing edges, tracking
# confidence via the semiring, pruning dead ends (non-composing / below the confidence floor / cyclic).
# --------------------------------------------------------------------------------------------------

#: Families whose nodes are the "who cares" of a blast-radius query — the ones an agent must re-verify
#: when structure changes under them (a task's completion, a memory's decision, an intent's contract).
_IMPACT_FAMILIES = frozenset({"plan", "memory", "intent"})


@dataclass(frozen=True)
class Reach:
    """One derived reachability fact: ``path[0]`` reaches ``target`` via the composed ``relation`` at
    ``confidence``. ``path`` is always in forward (source→target) order, whichever way it was walked."""

    target: str
    relation: str
    confidence: str
    depth: int
    path: tuple[str, ...]


def _prefers(a: Reach, b: Reach) -> bool:
    """Whether reach ``a`` should replace ``b`` for the same (target, relation): higher confidence, then
    shorter path, then lexicographically-smaller path (for a deterministic pick)."""
    if a.confidence != b.confidence:
        return stronger(a.confidence, b.confidence)
    if a.depth != b.depth:
        return a.depth < b.depth
    return a.path < b.path


def reach(
    graph: nx.DiGraph,
    start: str,
    *,
    relations: Iterable[str] | None = None,
    reverse: bool = False,
    max_depth: int = 6,
    min_confidence: str = AMBIGUOUS,
) -> list[Reach]:
    """Every node reachable from ``start`` along a *typed, composing* path, best-first per relation.

    Follows only edges that are :func:`well_typed` and whose relation composes with the path so far
    (:func:`compose_chain`); a non-composing edge is a dead end and is not walked (this is the "fewer
    dead-end walks" win). ``reverse=True`` walks incoming edges — the blast-radius direction — while
    still reporting each path in forward order so its composed relation reads correctly. Confidence is
    the semiring combination over the path (:func:`combine_path`); paths below ``min_confidence`` and
    cycles are pruned, and dominated states are not re-expanded (bottleneck monotonicity keeps this
    exact). ``relations`` restricts which relation labels may be traversed.
    """
    if start not in graph:
        return []
    floor = _RANK.get(min_confidence, 0)
    allowed = None if relations is None else set(relations)
    best: dict[tuple[str, str], Reach] = {}          # emitted: (target, relation) -> best Reach
    expanded: dict[tuple[str, str], tuple[int, int]] = {}  # dominance memo: (node, rel) -> (rank, depth)

    # A frontier state: (node, forward relation tuple, forward confidence tuple, forward path tuple).
    stack: list[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = [(start, (), (), (start,))]
    while stack:
        node, rels, confs, path = stack.pop()
        if len(path) - 1 >= max_depth:
            continue
        step = graph.in_edges(node, data=True) if reverse else graph.out_edges(node, data=True)
        for src, dst, attrs in step:
            nxt = src if reverse else dst        # the far endpoint relative to walk direction
            if nxt in path:                      # no cycles
                continue
            rel = attrs.get("relation")
            if rel is None or (allowed is not None and rel not in allowed):
                continue
            if not well_typed(rel, graph.nodes[src], graph.nodes[dst]):
                continue
            # forward relation order: forward walk appends the new edge, reverse walk prepends it.
            new_rels = (rel,) + rels if reverse else rels + (rel,)
            derived = compose_chain(new_rels)
            if derived is None:                  # does not compose ⇒ dead end
                continue
            new_confs = (attrs.get("confidence", EXTRACTED),) + confs if reverse else \
                confs + (attrs.get("confidence", EXTRACTED),)
            path_conf = combine_path(new_confs)
            if _RANK.get(path_conf, 0) < floor:
                continue
            new_path = (nxt,) + path if reverse else path + (nxt,)
            depth = len(new_path) - 1
            candidate = Reach(nxt, derived, path_conf, depth, new_path)
            key = (nxt, derived)
            if key not in best or _prefers(candidate, best[key]):
                best[key] = candidate
            # Dominance pruning: a state already reached at >= confidence AND <= depth dominates this
            # one — bottleneck confidence is non-increasing and depth non-decreasing, so re-expanding a
            # dominated state can never yield a strictly better descendant.
            seen = expanded.get(key)
            rank = _RANK.get(path_conf, 0)
            if seen is not None and seen[0] >= rank and seen[1] <= depth:
                continue
            expanded[key] = (rank, depth)
            stack.append((nxt, new_rels, new_confs, new_path))
    return sorted(best.values(), key=lambda r: (r.depth, r.target, r.relation))


def blast_radius(graph: nx.DiGraph, node_id: str, *, max_depth: int = 6) -> list[Reach]:
    """Who is transitively affected if ``node_id`` (a code symbol) changes: the intents, plans, and
    memories reverse-reachable along typed, composing edges. The read behind "this symbol drifted —
    what governed work must be re-verified?" (a typed generalization of :mod:`yigraf.drift`)."""
    return [
        r for r in reach(graph, node_id, reverse=True, max_depth=max_depth)
        if graph.nodes.get(r.target, {}).get("family") in _IMPACT_FAMILIES
    ]


def mistyped_edges(graph: nx.DiGraph) -> list[tuple[str, str, str]]:
    """Every live edge that violates its relation's signature, as sorted ``(source, target, relation)``.
    A read-time audit (never a mutation): the enforcement counterpart of :func:`well_typed`, holding the
    grammar as an invariant over an already-built graph. An empty list is the healthy state."""
    bad: list[tuple[str, str, str]] = []
    for src, dst, attrs in graph.edges(data=True):
        rel = attrs.get("relation")
        if rel is None or rel not in SIGNATURES:  # ungoverned relations are not audited
            continue
        if not well_typed(rel, graph.nodes[src], graph.nodes[dst]):
            bad.append((src, dst, rel))
    bad.sort()
    return bad
