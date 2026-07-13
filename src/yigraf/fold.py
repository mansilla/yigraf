"""The fold: materialize the graph as a pure fold over the causally-ordered assertion log (task #3).

mem:058 reframed multi-writer coordination as "append to an ordered log"; this module is where
yigraf's supersedes/append discipline — memory-only in v0 — **generalizes to every write**. The fold
is a *pure left-fold*: no I/O, deterministic, and its output is the materialized VIEW, never a write
target (R6, mem:059). It runs over :meth:`yigraf.log.Log.iter_assertions_in_causal_order` and knows
nothing about substrates — the same fold serves the local (git-file → SQLite) and online (Postgres)
transports (mem:059). Wiring it into ``build_graph`` in place of ``project_into`` and proving the
self-hosted graph rebuilds identically is the migration (task #6); this task ships the mechanism.

**Single-pass by construction.** mem:98d5a556 guarantees each assertion arrives *parent-before-child*,
so a superseding or edge-bearing assertion always sees its intra-log target already materialized. The
two-pass projection ``project_into`` needed (mem:056080f0) — and the separate ``recompute_counters``
sweep — are designed away here: supersession counters are maintained inline as the fold advances.

**The assertion body contract** (what the families emit, task #6 produces it from the markdown):
``Assertion.body`` describes the node this assertion introduces plus its outgoing edges — never its
own id (that is :attr:`Assertion.id`, content-addressed) and never causal parents (mem:063)::

    {"family": "memory",
     "attrs": {"kind": "decision", "label": "...", "statement": "...", ...},
     "edges": [{"relation": "serves", "target": "int:x", "attrs": {...}?}, ...]}

Belief revision (mem:058): a ``supersedes`` edge marks its target superseded but never deletes it —
the target sinks in ranking yet stays retrievable as a rejected alternative. A ``pending`` supersede
(of a human-attested node, int:memory-attestation) is recorded but NOT counted, so the target stays
authoritative until a principal resolves the conflict — resolution being itself a later append
(mem:062). An unresolved edge target stashes a ``dangling_edges`` marker rather than conjuring a
phantom node, exactly as ``memory.project_into`` does (so :mod:`yigraf.drift` can re-anchor a rename).
"""
from __future__ import annotations

from typing import Any

import networkx as nx

from yigraf.graph import empty_graph
from yigraf.log import Assertion, Log


def fold(log: Log, base: nx.DiGraph | None = None) -> nx.DiGraph:
    """Materialize the graph by folding ``log``'s assertions in causal order onto ``base``.

    ``base`` is the non-asserted substrate the assertion families attach to — the structure graph from
    the extractor (structure is derived from source, not asserted), matching where ``project_into`` sits
    in ``build_graph`` today. ``None`` starts from an empty graph (the fold in isolation). The passed
    graph is mutated in place and returned; the fold performs no persistence — the result IS the view.
    """
    graph = base if base is not None else empty_graph()
    for assertion in log.iter_assertions_in_causal_order():
        _apply(graph, assertion)
    return graph


def _apply(graph: nx.DiGraph, assertion: Assertion) -> None:
    """Fold one assertion into ``graph``: upsert its node, then project its edges + supersede discipline.

    The log has already collapsed identical-content assertions (mem:060), so each id is applied once —
    the fold never has to merge conflicting attributes for the same node.
    """
    body = assertion.body
    graph.add_node(
        assertion.id,
        family=body.get("family"),
        provenance=list(assertion.provenance),  # attribution rides onto the view (mem:063)
        superseded_in=0,  # maintained inline below (no separate recompute pass — see module docstring)
        supersedes_out=0,
        **body.get("attrs", {}),
    )
    for edge in body.get("edges", []):
        _apply_edge(graph, assertion.id, edge)


def _apply_edge(graph: nx.DiGraph, source: str, edge: dict[str, Any]) -> None:
    relation = edge["relation"]
    target = edge["target"]
    if target not in graph:
        # No phantom nodes: stash the full spec so a later resolution / drift re-anchor can recover it.
        graph.nodes[source].setdefault("dangling_edges", []).append(edge)
        return

    attrs = dict(edge.get("attrs") or {})
    graph.add_edge(source, target, relation=relation, **attrs)

    # Generalized supersedes/append discipline (mem:058), maintained inline — causal order (mem:98d5a556)
    # guarantees the target is already present, so no second pass is needed. A pending supersede (of a
    # human-attested node) is recorded above but not counted: the target stays authoritative (mem:062).
    if relation == "supersedes" and not attrs.get("pending"):
        graph.nodes[target]["superseded_in"] = graph.nodes[target].get("superseded_in", 0) + 1
        graph.nodes[source]["supersedes_out"] = graph.nodes[source].get("supersedes_out", 0) + 1
