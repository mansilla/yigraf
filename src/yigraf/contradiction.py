"""Async contradiction / coherence detector — a consumer of the folded view (plan task #4).

int:concurrent-write-model / mem:062: surface two LIVE beliefs concerning the SAME anchor that say
nearly the same thing yet were never reconciled, as a knowledge-conflict *finding* for a principal —
**never a synchronous write gate**. It is derived, exactly like :mod:`yigraf.drift`: recomputed from
the view, never stored (R6). Resolution is a *later append* — a ``supersedes`` / ``attest`` /
``equivalent_to`` assertion on the human-authority surface — not a mutation performed here (mem:062).

**What it is.** The write-time near-duplicate guard (:func:`yigraf.embeddings.most_similar_memory`)
generalized to a BATCH sweep over the whole merged view — which is exactly what mem:060 names the
standing reconcile. The per-write guard only ever sees one repo's graph, so a near-duplicate or
contradiction introduced by MERGING two independent logs (the multi-writer case this plan exists for)
slips straight past it; this sweep catches it cross-log, after the fold. It groups contradictions and
near-dups together — mem:062's single "coherence-dirty" set awaiting a principal — because whether a
co-anchored live pair is a redundant restatement (resolve → ``equivalent_to`` / supersede) or an
opposing belief (resolve → supersede / attest) is the principal's call, not the detector's.

**Fail-open to SILENCE** (design law #4, #5). With no embedding index it returns ``[]`` rather than
flooding the agent with every co-anchored pair (measured on the self-hosted graph: 10 anchors, mostly
*complementary* decisions). A principal-facing coherence signal must be high-precision; the cosine
gate (``embeddings.conflict_cosine``, default 0.85 — above the complementary-noise band, below the
0.9 refuse-at-write line) keeps it so. Stance-opposition *below* the paraphrase band is a job for an
LLM judge in the online async pass (int:yigraf-online-v1), never this deterministic sweep.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from yigraf import revision
from yigraf.embeddings import load_index

MEMORY_FAMILY = "memory"

#: Relations whose presence between a pair means a principal has already reconciled them (mem:062) —
#: an equivalence resolution declaring the two live beliefs compatible/duplicate. An *applied*
#: supersede needs no entry: it drives the target's ``superseded_in`` > 0, so liveness already drops
#: it. A *pending* supersede is NOT reconciliation — it is an open conflict held for a human, so it
#: stays surfaced (flagged :attr:`Conflict.pending`).
_RECONCILED_RELATIONS = frozenset({"equivalent_to", "duplicate_of"})

DEFAULT_CONFLICT_COSINE = 0.85


@dataclass
class Conflict:
    """A knowledge-conflict finding: two live, co-anchored, unreconciled beliefs (mem:062).

    Derived and recomputable — the "knowledge-conflict node" of int:concurrent-write-model as a finding
    the resolution UI (a log client) renders, and the count the status surface carries; never a stored
    assertion. ``left``/``right`` are the memory ids, sorted so the finding is stable across rebuilds.
    """

    anchor: str  # the shared ``concerns`` target (the code locus both beliefs govern)
    left: str  # the pair of memory ids, sorted (left < right) for a deterministic finding
    right: str
    cosine: float  # how close the two beliefs read — the surfacing signal
    pending: bool = False  # a supersede between them is held pending (mem:062): resolution proposed, awaiting a human
    dominant: str | None = None  # which side the provenance order prefers (yigraf.revision), None if same-tier


def _is_live_memory(attrs: dict) -> bool:
    """A memory belief still in force: active + not (applied-)superseded. Mirrors the write-time guard
    (:func:`yigraf.embeddings.most_similar_memory`) so the batch sweep and per-write check agree."""
    return (attrs.get("family") == MEMORY_FAMILY
            and attrs.get("status", "active") == "active"
            and not attrs.get("superseded_in", 0))


def _reconciled(graph: nx.DiGraph, a: str, b: str) -> bool:
    for u, v in ((a, b), (b, a)):
        if graph.has_edge(u, v) and graph.edges[u, v].get("relation") in _RECONCILED_RELATIONS:
            return True
    return False


def _pending(graph: nx.DiGraph, a: str, b: str) -> bool:
    for u, v in ((a, b), (b, a)):
        if (graph.has_edge(u, v) and graph.edges[u, v].get("relation") == "supersedes"
                and graph.edges[u, v].get("pending")):
            return True
    return False


def detect_conflicts(graph: nx.DiGraph, root: Path, config: dict, index=None) -> list[Conflict]:
    """The standing reconcile sweep: co-anchored live belief pairs above the cosine gate (mem:060/062).

    Pure and fail-open: no index ⇒ ``[]`` (silence over noise, design law #4). Loads only the persisted
    vectors — pairwise cosine is a dot product of two normalized rows, so no model is loaded (cheap
    enough for the status path). The status surface already holds a loaded index; it passes it in to
    avoid a second read. A pair sharing several anchors is reported once (first anchor by sort).
    """
    if index is None:
        index = load_index(root, config)
    if index is None:
        return []
    threshold = config.get("embeddings", {}).get("conflict_cosine", DEFAULT_CONFLICT_COSINE)

    by_anchor: dict[str, list[str]] = defaultdict(list)
    for node_id, attrs in graph.nodes(data=True):
        if not _is_live_memory(attrs):
            continue
        for _, target, edge in graph.out_edges(node_id, data=True):
            if edge.get("relation") == "concerns":
                by_anchor[target].append(node_id)

    conflicts: list[Conflict] = []
    seen: set[tuple[str, str]] = set()
    for anchor in sorted(by_anchor):
        mems = sorted(by_anchor[anchor])
        for i in range(len(mems)):
            for j in range(i + 1, len(mems)):
                left, right = mems[i], mems[j]
                if (left, right) in seen or _reconciled(graph, left, right):
                    continue
                va, vb = index.vector(left), index.vector(right)
                if va is None or vb is None:
                    continue
                cosine = float(va @ vb)  # both rows L2-normalized ⇒ dot == cosine
                if cosine >= threshold:
                    seen.add((left, right))
                    conflicts.append(Conflict(
                        anchor, left, right, cosine,
                        pending=_pending(graph, left, right),
                        # Provenance-typed guidance for the human resolving this (epistemic-control-plane
                        # #6): which side the order prefers, or None when they are the same tier — never
                        # an auto-resolution (mem:062), never last-writer-wins.
                        dominant=revision.dominant_id(left, graph.nodes[left], right, graph.nodes[right])))
    conflicts.sort(key=lambda c: (-c.cosine, c.anchor, c.left, c.right))
    return conflicts


def open_conflict_count(graph: nx.DiGraph, root: Path, config: dict, index=None) -> int:
    """The cheap coherence-dirty count for the status surface (mem:062) — the *only* conflict signal
    the agent channel carries; the full findings go to the human-authority resolution UI, never the
    hook injection (mem:012: a human concern must not spend the agent's context budget)."""
    return len(detect_conflicts(graph, root, config, index=index))
