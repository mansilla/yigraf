"""Counters, maturity, and GC — v0 keeps ``graph.json`` **fully recomputable** (DESIGN R1/R2/R3).

The relevance/GC engine without any *accumulated, committed* state:

- **maturity** (``working``/``settled``) is **git-derived** (R2): a memory is ``settled`` once its
  artifact has lived ``≥ K`` commits on the branch un-superseded — recomputed at build time from
  ``git log`` + supersede edges, so it's deterministic, branch-cadence-independent, and identical on
  every clone/CI run. No per-session ``survival`` counter is stored or merged.
- **telemetry** (``usage``/``last_seen``) is a **gitignored sidecar** (R1) — ``yigraf/.local/
  telemetry.json``, machine-local and best-effort, a soft recency/popularity nudge in ranking only.
  It is *never* written to the committed ``graph.json``, so a query never dirties git.
- **GC** (R3) **archives, never deletes, and never gates on ``usage``**: superseded churn
  (``superseded_in>0 ∧ refs_in=0``) is moved to an ``archive/`` folder; a still-referenced
  predecessor is left in place.

Because ``graph.json`` holds only recomputable state, branches reconcile by *rebuilding*; the
``merge_node_link`` union driver just avoids spurious line-level conflicts in the meantime.

> The *shared, committed, merge-reconciled* counter model (accumulated ``survival``/``usage`` in
> ``graph.json`` with a counter-reconciling merge driver) is **v1 / Enterprise** future work — it
> belongs to the cloud service where teams share artifacts and specs through an API
> (``docs/DESIGN.md`` "Counter models", ``docs/graph-design.md`` §3). v0 is deliberately local.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import networkx as nx

from yigraf.memory import MEMORY_FAMILY

#: Families that carry the telemetry nudge — the durable "why"/spec nodes whose recurrence across
#: sessions is what recency/popularity should reward (structure is ranked by refs_in/proximity).
COUNTED_FAMILIES = frozenset({MEMORY_FAMILY, "intent"})

#: Incoming edges that count as a node being "referenced" (importance) — shared with retrieval.
SEMANTIC_RELATIONS = frozenset({"implements", "tracks", "serves", "concerns", "references"})


# --------------------------------------------------------------------------------------------------
# git-derived maturity (R2) — recomputed each build, never stored as an accumulating counter
# --------------------------------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str | None:
    """Run a read-only git command under ``root``; ``None`` if git is unavailable or errors (fail-open)."""
    try:
        out = subprocess.run(["git", "-C", str(root), *args],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def survival_of(root: Path, repo_relpath: str) -> int:
    """Commits the branch has accrued since ``repo_relpath`` was introduced (R2's maturity clock).

    Derived from history, not accumulated: the count of commits from the file's *add* commit to
    ``HEAD``. ``0`` when there's no git, no such file, or it was added in the tip commit — so a
    freshly-captured memory starts at ``0`` and matures as the branch moves on past it.
    """
    adds = _git(root, "log", "--diff-filter=A", "--format=%H", "--", repo_relpath)
    if not adds or not adds.strip():
        return 0
    intro = adds.strip().splitlines()[-1]
    count = _git(root, "rev-list", "--count", f"{intro}..HEAD")
    try:
        return int(count.strip()) if count else 0
    except ValueError:
        return 0


def apply_maturity(graph: nx.DiGraph, root: Path, config: dict) -> None:
    """Stamp git-derived ``survival`` + ``maturity`` on every memory node (recomputed each build).

    ``settled`` once ``survival ≥ K`` with ``superseded_in == 0`` (graph-design §3 / DESIGN R2):
    certainty earned by surviving boundaries, not self-reported, and self-healing — a later
    supersession reverts the node to ``working`` on the next build. Recomputable, so it lives happily
    in the committed (recomputable) ``graph.json`` without an accumulating counter or a merge driver.
    """
    k = int(config.get("maturity_k", 3))
    for _, attrs in graph.nodes(data=True):
        if attrs.get("family") != MEMORY_FAMILY:
            continue
        source = attrs.get("source_file")
        survival = survival_of(root, f"yigraf/{source}") if source else 0
        attrs["survival"] = survival
        attrs["maturity"] = "settled" if (survival >= k and not attrs.get("superseded_in", 0)) else "working"


# --------------------------------------------------------------------------------------------------
# Telemetry sidecar (R1) — machine-local usage/last_seen, never committed
# --------------------------------------------------------------------------------------------------


def telemetry_path(root: Path) -> Path:
    return Path(root) / "yigraf" / ".local" / "telemetry.json"


def load_telemetry(root: Path) -> dict[str, dict]:
    """Read the gitignored ``{node_id: {usage, last_seen}}`` sidecar (``{}`` if absent/corrupt)."""
    path = telemetry_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def apply_telemetry(graph: nx.DiGraph, telemetry: dict[str, dict]) -> None:
    """Stamp sidecar ``usage``/``last_seen`` onto the in-memory graph for ranking (read paths only).

    Never called on the ``build`` write path, so the telemetry never reaches the committed
    ``graph.json`` — it's a query-time overlay that keeps ``graph.json`` recomputable.
    """
    for node_id, entry in telemetry.items():
        if node_id not in graph:
            continue
        if "usage" in entry:
            graph.nodes[node_id]["usage"] = entry["usage"]
        if "last_seen" in entry:
            graph.nodes[node_id]["last_seen"] = entry["last_seen"]


def record_injection(root: Path, graph: nx.DiGraph, node_ids: list[str],
                     now: float | None = None) -> list[str]:
    """Record that ``node_ids`` were surfaced: bump ``usage``/``last_seen`` in the sidecar (R1).

    Scoped to the counted families (memory+intent). Machine-local and best-effort — a surfacing is a
    soft ranking signal, not committed state. Returns the ids actually bumped.
    """
    stamp = int(now if now is not None else time.time())
    telemetry = load_telemetry(root)
    bumped: list[str] = []
    for node_id in node_ids:
        attrs = graph.nodes.get(node_id) if node_id in graph else None
        if attrs is None or attrs.get("family") not in COUNTED_FAMILIES:
            continue
        entry = telemetry.setdefault(node_id, {})
        entry["usage"] = int(entry.get("usage", 0)) + 1
        entry["last_seen"] = stamp
        bumped.append(node_id)
    if bumped:
        path = telemetry_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(telemetry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return bumped


def recency(last_seen: int | None, now: float, half_life_days: float) -> float:
    """Exp-decayed recency in ``[0, 1]``: ``1`` just-surfaced, halving every ``half_life_days``."""
    if not last_seen:
        return 0.0
    age_days = max(0.0, (now - last_seen)) / 86400.0
    return 0.5 ** (age_days / max(half_life_days, 1e-9))


def maturity_weight(attrs: dict) -> float:
    """The maturity contribution to relevance: a settled memory is weighted, a working one is not."""
    return 1.0 if attrs.get("maturity") == "settled" else 0.0


# --------------------------------------------------------------------------------------------------
# Garbage collection (R3) — archive churn, never delete, never gate on usage
# --------------------------------------------------------------------------------------------------


def refs_in(graph: nx.DiGraph, node_id: str) -> int:
    """Count incoming *semantic* edges — whether anything still points at this node."""
    return sum(1 for _, _, a in graph.in_edges(node_id, data=True)
               if a.get("relation") in SEMANTIC_RELATIONS)


def classify_gc(graph: nx.DiGraph) -> dict[str, str]:
    """Map each superseded-and-unreferenced memory node to its GC action: ``archive`` (R3).

    Churn = ``superseded_in>0 ∧ refs_in=0`` (a mind-change nobody else points at) → archived, never
    deleted (history is auditable) and never gated on ``usage`` (telemetry isn't authoritative). A
    superseded node that *is* still referenced is left in place as an available rejected alternative.
    """
    actions: dict[str, str] = {}
    for node_id, attrs in graph.nodes(data=True):
        if attrs.get("family") != MEMORY_FAMILY or not attrs.get("superseded_in", 0):
            continue
        if refs_in(graph, node_id) == 0:
            actions[node_id] = "archive"
    return actions


# --------------------------------------------------------------------------------------------------
# Union-merge driver — graph.json is recomputable, so this just avoids spurious conflicts
# --------------------------------------------------------------------------------------------------


def merge_node_link(ours: dict, theirs: dict, edges_key: str = "links") -> dict:
    """Union-merge two ``graph.json`` node-link dicts (no counter reconciliation — that's v1).

    ``graph.json`` holds only recomputable state in v0, so the post-merge build re-projects it
    exactly; this driver exists only so a concurrent two-branch edit doesn't throw a line-level JSON
    conflict in the meantime. Nodes/edges are unioned; ``ours`` wins a content tie (the build heals it).
    """
    nodes = {n["id"]: n for n in theirs.get("nodes", [])}
    nodes.update({n["id"]: n for n in ours.get("nodes", [])})

    edges: dict[tuple, dict] = {}
    for edge in theirs.get(edges_key, []) + ours.get(edges_key, []):
        edges[(edge["source"], edge["target"], edge.get("relation", ""))] = edge

    out = dict(ours)
    out["nodes"] = [nodes[k] for k in sorted(nodes)]
    out[edges_key] = sorted(edges.values(),
                            key=lambda e: (e["source"], e["target"], e.get("relation", "")))
    return out
