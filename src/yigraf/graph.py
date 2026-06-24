"""The yigraf graph: a directed NetworkX graph serialized as node-link JSON.

Per ``docs/DESIGN.md`` R1, ``graph.json`` is committed but holds only *recomputable* state (nodes,
edges, and edge-derived counters). Volatile telemetry (``usage`` / ``last_seen``) lives in the
gitignored ``.local/`` sidecar, not here. Serialization is deterministic (sorted keys) so an
unchanged graph re-serializes byte-for-byte — which M1's "re-run is byte-identical" done-test needs.
"""
from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

#: Bumped when the on-disk graph schema changes incompatibly.
SCHEMA_VERSION = 0

#: node-link edges key. Pinned to "links" so the format is stable across networkx versions
#: (networkx >=3.4 otherwise warns that the implicit default key is changing to "edges").
_EDGES_KEY = "links"


def empty_graph() -> nx.DiGraph:
    """A fresh, empty directed graph carrying the current schema version."""
    g = nx.DiGraph()
    g.graph["schema_version"] = SCHEMA_VERSION
    return g


def to_node_link(g: nx.DiGraph) -> dict:
    """Serialize ``g`` to a node-link dict with nodes and edges in a stable, sorted order.

    ``node_link_data`` emits nodes/edges in graph *insertion* order, which would make ``graph.json``
    depend on traversal order. Sorting nodes by ``id`` and edges by ``(source, target, relation)``
    makes a no-change rebuild byte-identical (M1 done-test, docs/m1-notes.md §6); ``json.dumps`` then
    sorts the keys *within* each object.
    """
    data = nx.node_link_data(g, edges=_EDGES_KEY)
    data["nodes"].sort(key=lambda n: n["id"])
    data[_EDGES_KEY].sort(key=lambda e: (e["source"], e["target"], e.get("relation", "")))
    return data


def from_node_link(data: dict) -> nx.DiGraph:
    """Rebuild a directed graph from a node-link dict."""
    return nx.node_link_graph(data, directed=True, multigraph=False, edges=_EDGES_KEY)


def write_graph(g: nx.DiGraph, path: Path) -> None:
    """Write ``g`` to ``path`` as deterministic, pretty-printed node-link JSON."""
    text = json.dumps(to_node_link(g), indent=2, sort_keys=True) + "\n"
    Path(path).write_text(text, encoding="utf-8")


def read_graph(path: Path) -> nx.DiGraph:
    """Read a graph previously written by :func:`write_graph`."""
    return from_node_link(json.loads(Path(path).read_text(encoding="utf-8")))
