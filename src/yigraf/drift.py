"""Drift detection + rename handling over the built graph (M3, docs/m3-notes.md).

Drift is derived, never persisted (glossary §4): a drift-bearing edge whose target symbol changed
body since it was anchored is **soft drift**; one whose locator no longer resolves (and isn't a
rename) is **hard drift**. A pure rename/move is **not** drift — because the anchor excludes the
symbol's own name (R10 refinement), a renamed symbol keeps its body-hash, so the edge auto-re-anchors
to the new locator by exact match.

v0 was ``implements``-only (R7). The memory milestone (M7) adds the second drift-bearing relation,
``concerns`` (memory → code): a captured decision/constraint is anchored to the code it governs, so
editing that code surfaces a "re-verify this decision still holds" reconcile, exactly as ``implements``
does for a task. Both relations flow through the *same* rename/soft/hard machinery below — they differ
only in the source family (a ``task`` vs a ``memory`` node) and the frontmatter field the anchor lives
in (``dangling_implements`` vs ``dangling_concerns``).
"""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from yigraf.astnorm import ANCHOR_ALGO

CONF = "EXTRACTED"

#: The drift-bearing relations and the per-node attr each stashes an unresolved (dangling) target on.
#: One code path serves all three, so ``concerns`` and ``grounded_by`` inherit rename re-anchoring +
#: soft/hard detection for free. ``grounded_by`` (memory → the evidence that grounds it,
#: int:memory-grounding): the evidence changing means the ``empirical`` tier is now unearned — a
#: demotion signal reconciled by ``reaffirm --grounding`` (re-observed) or a downgrade to ``inferred``.
_DRIFT_RELATIONS = {
    "implements": "dangling_implements",
    "concerns": "dangling_concerns",
    "grounded_by": "dangling_grounded_by",
}


@dataclass
class DriftItem:
    kind: str  # "soft" | "hard" | "renamed"
    task_id: str  # the *source* node id of the drift-bearing edge (a task, or — for concerns — a memory)
    locator: str  # the anchored/declared symbol locator
    new_locator: str | None = None  # the resolved locator, for a rename
    detail: str = ""
    relation: str = "implements"  # which drift-bearing relation drifted (implements | concerns)


def _hash_index(graph: nx.DiGraph) -> dict[str, list[str]]:
    """Map each astnorm structure node's ``content_hash`` to the node ids that carry it (sorted).

    Rename re-anchoring is an astnorm-symbol concept — a moved symbol keeps its body-hash. ``file:``
    anchor nodes (``hash_algo != astnorm-v1``) are excluded: a file doesn't "rename" by content match,
    and its raw SHA lives in a different hash space anyway (friend-review #12).
    """
    index: dict[str, list[str]] = {}
    for node_id, attrs in graph.nodes(data=True):
        if (attrs.get("family") == "structure" and "content_hash" in attrs
                and attrs.get("hash_algo", ANCHOR_ALGO) == ANCHOR_ALGO):
            index.setdefault(attrs["content_hash"], []).append(node_id)
    for ids in index.values():
        ids.sort()
    return index


def resolve_renames(graph: nx.DiGraph) -> None:
    """Re-anchor rename/move dangling drift-bearing edges in place (mutates ``graph``).

    For each node's ``dangling_implements`` / ``dangling_concerns`` entry, look its anchor up among
    structure nodes: a unique hit is a rename → add the edge to the new locator (tagged
    ``renamed_from``) and clear the entry. Zero hits = real hard drift; multiple hits = ambiguous →
    left dangling, not guessed (§3). The same logic serves both relations (``concerns`` for free).
    """
    index = _hash_index(graph)
    for node_id in list(graph.nodes):
        for relation, attr in _DRIFT_RELATIONS.items():
            dangling = graph.nodes[node_id].get(attr)
            if not dangling:
                continue
            remaining = []
            for entry in dangling:
                anchor, algo = entry.get("anchor"), entry.get("anchor_algo")
                matches = index.get(anchor, []) if anchor and algo == ANCHOR_ALGO else []
                if len(matches) == 1:
                    graph.add_edge(
                        node_id, matches[0], relation=relation, confidence=CONF,
                        anchor=anchor, anchor_algo=algo, renamed_from=entry["sym"],
                    )
                else:
                    remaining.append(entry)
            if remaining:
                graph.nodes[node_id][attr] = remaining
            else:
                del graph.nodes[node_id][attr]


def compute_drift(graph: nx.DiGraph) -> list[DriftItem]:
    """Report soft/hard/renamed drift over ``graph`` (assumes :func:`resolve_renames` has run).

    Covers both drift-bearing relations (``implements`` from a task, ``concerns`` from a memory);
    each :class:`DriftItem` carries its ``relation`` so callers can word the reconcile line per kind.
    """
    items: list[DriftItem] = []

    # A superseded decision is historical (mem:024 → mem:023 via `supersedes`); its `concerns` anchor
    # must not drift-nag — the successor now carries that concern. Skip drift sourced from such nodes.
    superseded = {dst for _, dst, a in graph.edges(data=True) if a.get("relation") == "supersedes"}

    for src, dst, attrs in graph.edges(data=True):
        relation = attrs.get("relation")
        if relation not in _DRIFT_RELATIONS or src in superseded:
            continue
        if "renamed_from" in attrs:
            items.append(DriftItem("renamed", src, attrs["renamed_from"], new_locator=dst,
                                   relation=relation))
        anchor = attrs.get("anchor")
        # Compare only when the edge's anchor algo matches the target node's hash algo: preserves the
        # astnorm-v2-bump protection (a v1 anchor never compares against a v2 hash) *and* routes a
        # file: anchor (file-sha256-v1) only against a file node's raw SHA (#12). Symbol nodes carry no
        # hash_algo, so they default to astnorm-v1 — the original R10 behavior, unchanged.
        if anchor is None or attrs.get("anchor_algo") != graph.nodes[dst].get("hash_algo", ANCHOR_ALGO):
            continue
        current = graph.nodes[dst].get("content_hash")
        if current is not None and current != anchor:
            items.append(DriftItem("soft", src, dst, detail="body changed since anchored",
                                   relation=relation))

    for node_id, node_attrs in graph.nodes(data=True):
        if node_id in superseded:  # a superseded decision's dangling concern is historical — no nag
            continue
        for relation, attr in _DRIFT_RELATIONS.items():
            for entry in node_attrs.get(attr, []):
                items.append(DriftItem("hard", node_id, entry["sym"], detail="symbol not found",
                                       relation=relation))

    items.sort(key=lambda it: (it.kind, it.task_id, it.locator))
    return items
