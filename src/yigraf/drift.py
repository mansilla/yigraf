"""Drift detection + rename handling over the built graph (M3, docs/m3-notes.md).

Drift is derived, never persisted (glossary §4): an ``implements`` edge whose target symbol changed
body since it was anchored is **soft drift**; one whose locator no longer resolves (and isn't a
rename) is **hard drift**. A pure rename/move is **not** drift — because the anchor excludes the
symbol's own name (R10 refinement), a renamed symbol keeps its body-hash, so the edge auto-re-anchors
to the new locator by exact match. v0 is ``implements``-only (R7).
"""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from yigraf.astnorm import ANCHOR_ALGO

CONF = "EXTRACTED"


@dataclass
class DriftItem:
    kind: str  # "soft" | "hard" | "renamed"
    task_id: str
    locator: str  # the anchored/declared symbol locator
    new_locator: str | None = None  # the resolved locator, for a rename
    detail: str = ""


def _hash_index(graph: nx.DiGraph) -> dict[str, list[str]]:
    """Map each structure node's ``content_hash`` to the node ids that carry it (sorted)."""
    index: dict[str, list[str]] = {}
    for node_id, attrs in graph.nodes(data=True):
        if attrs.get("family") == "structure" and "content_hash" in attrs:
            index.setdefault(attrs["content_hash"], []).append(node_id)
    for ids in index.values():
        ids.sort()
    return index


def resolve_renames(graph: nx.DiGraph) -> None:
    """Re-anchor rename/move dangling ``implements`` edges in place (mutates ``graph``).

    For each task's ``dangling_implements`` entry, look its anchor up among structure nodes: a unique
    hit is a rename → add the edge to the new locator (tagged ``renamed_from``) and clear the entry.
    Zero hits = real hard drift; multiple hits = ambiguous → both left dangling, not guessed (§3).
    """
    index = _hash_index(graph)
    for node_id in list(graph.nodes):
        dangling = graph.nodes[node_id].get("dangling_implements")
        if not dangling:
            continue
        remaining = []
        for entry in dangling:
            anchor, algo = entry.get("anchor"), entry.get("anchor_algo")
            matches = index.get(anchor, []) if anchor and algo == ANCHOR_ALGO else []
            if len(matches) == 1:
                graph.add_edge(
                    node_id, matches[0], relation="implements", confidence=CONF,
                    anchor=anchor, anchor_algo=algo, renamed_from=entry["sym"],
                )
            else:
                remaining.append(entry)
        if remaining:
            graph.nodes[node_id]["dangling_implements"] = remaining
        else:
            del graph.nodes[node_id]["dangling_implements"]


def compute_drift(graph: nx.DiGraph) -> list[DriftItem]:
    """Report soft/hard/renamed drift over ``graph`` (assumes :func:`resolve_renames` has run)."""
    items: list[DriftItem] = []

    for src, dst, attrs in graph.edges(data=True):
        if attrs.get("relation") != "implements":
            continue
        if "renamed_from" in attrs:
            items.append(DriftItem("renamed", src, attrs["renamed_from"], new_locator=dst))
        anchor = attrs.get("anchor")
        if anchor is None or attrs.get("anchor_algo") != ANCHOR_ALGO:
            continue  # unanchored or a different algo — don't compare (R10)
        current = graph.nodes[dst].get("content_hash")
        if current is not None and current != anchor:
            items.append(DriftItem("soft", src, dst, detail="body changed since anchored"))

    for node_id, node_attrs in graph.nodes(data=True):
        for entry in node_attrs.get("dangling_implements", []):
            items.append(DriftItem("hard", node_id, entry["sym"], detail="symbol not found"))

    items.sort(key=lambda it: (it.kind, it.task_id, it.locator))
    return items
