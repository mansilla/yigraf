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

**Source claim vs. derived belief (task #5).** An assertion's ``body`` carries only what a writer
*claims* — never whether that claim is currently *believed*. Acceptance (``accepted``), supersession
(``superseded_in``/``supersedes_out``) are :data:`_DERIVED_KEYS`: the fold's verdict over the WHOLE
assertion set, recomputed every fold and stripped if a body tries to smuggle them. That split is what
makes the intent's "never a silent last-writer-wins" hold under a log MERGE: two writers cannot assert
contradictory acceptance of one claim (identical content ⇒ identical id ⇒ collapse, not a fork), so
merging two logs is a set-union of source claims that re-derives belief deterministically — a genuine
disagreement surfaces as two DIFFERENT claims the contradiction-detector flags, never one belief
silently overwriting the other. ``accepted`` starts ``True`` and flips to ``False`` only when a
*counted* (non-pending) supersede retracts the node — the queryable form of mem:058's belief revision.

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

#: Node attributes that are DERIVED BELIEF — the fold's own output, recomputed from the whole assertion
#: set on every fold — as opposed to the SOURCE CLAIM a writer asserts (task #5). Keeping these out of
#: the content-addressed ``body`` is what lets a merge of two logs re-derive belief deterministically
#: instead of last-writer-wins: two writers can never assert *contradictory acceptance* of the same
#: claim (that would fork the id), so acceptance is always the fold's verdict over the union of claims.
#: The fold STRIPS any of these that leak into ``body.attrs`` (a source claim may not assert its own
#: belief) and sets them itself. ``provenance``/``family``/``scope`` come off the envelope, not attrs.
_DERIVED_KEYS = frozenset({"accepted", "superseded_in", "supersedes_out"})


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
    # Split source claim from derived belief (task #5): a claim may not assert its own acceptance/
    # supersession — those are the fold's verdict, so strip them before splatting and set them below.
    attrs = {k: v for k, v in body.get("attrs", {}).items() if k not in _DERIVED_KEYS}
    graph.add_node(
        assertion.id,
        family=body.get("family"),
        provenance=list(assertion.provenance),  # attribution rides onto the view (mem:063)
        scope=sorted(assertion.scope),  # reserved ATMS assumption-set, carried onto the view (task #5)
        superseded_in=0,  # maintained inline below (no separate recompute pass — see module docstring)
        supersedes_out=0,
        accepted=True,  # derived belief: live until a *counted* supersede retracts it (set in _apply_edge)
        **attrs,
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
        tgt = graph.nodes[target]
        tgt["superseded_in"] = tgt.get("superseded_in", 0) + 1
        tgt["accepted"] = tgt["superseded_in"] == 0  # derived belief retracted (mem:058: kept, not deleted)
        graph.nodes[source]["supersedes_out"] = graph.nodes[source].get("supersedes_out", 0) + 1
