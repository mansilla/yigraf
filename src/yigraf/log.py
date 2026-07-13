"""The transport-agnostic assertion log (int:concurrent-write-model, plan task #2).

This is the *shared spine*: the one interface every write substrate implements, so a single fold
(task #3) can materialize the graph regardless of whether truth lives in git-committed files (local,
int:yigraf-local-v1) or a Postgres append-only table (online, int:yigraf-online-v1). Per mem:059 the
*only* local↔online difference is a thin :meth:`Log.iter_assertions_in_causal_order` adapter over the
substrate — everything downstream (the fold, the contradiction-detector, the query layer) is shared.

Two decisions shape every line here; both are executable contracts, not comments:

- **mem:063 — content id ≠ causal position.** An :class:`Assertion` splits into two layers, mirroring
  git's blob-vs-commit split. ``id``/``kind``/``body`` are pure CONTENT: the id is the content-hash of
  the semantic ``body`` ONLY (never ``parents``/``provenance``), so two writers who independently
  assert the same thing mint the SAME id and COLLAPSE on merge (:func:`InMemoryLog.append`). ``parents``
  and ``provenance`` are the CAUSAL/attribution layer — never in the id; provenance MERGES as a list on
  collapse, so N independent rediscoveries strengthen one node rather than duplicate (mem:060).
- **mem:056080f0 — causal order is its OWN layer.** :func:`causal_order` linearizes the causal-parent
  DAG deterministically (topological sort + content-id tiebreak). It NEVER infers order from file,
  slug, or insertion order — the bug that dropped a pending conflict when content-addressed filenames
  started sorting by slug. Both substrates route their ordering through this contract.

Design-law fit: fail-open (R5) — :func:`causal_order` degrades gracefully on dangling parents or a
(should-never-happen) cycle instead of raising; no substrate is wired live here (that is tasks #5–#9),
so this module has no I/O and no dependency on the graph. :class:`InMemoryLog` is the reference
substrate the fold is developed and tested against before the durable ones exist.
"""
from __future__ import annotations

import hashlib
import heapq
import json
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Protocol, runtime_checkable

#: Assertion-id recipe (``assertid-v1``): memid-v1's content-only rule (mem:063) generalized to every
#: write. Versioned like :data:`yigraf.memory.MEMORY_ID_ALGO` / :data:`yigraf.astnorm.ANCHOR_ALGO` so
#: the recipe can evolve without silently re-identifying existing assertions.
ASSERTION_ID_ALGO = "assertid-v1"


@dataclass
class Assertion:
    """One entry in the append-only log: a content-addressed claim plus its causal position.

    Kept deliberately family-agnostic — the log transports opaque assertions; the *fold* (task #3)
    interprets ``kind``/``body`` into graph nodes and edges. ``id`` is supplied by whoever mints the
    content (memory uses :func:`yigraf.memory.memory_id`; log-native writes use :func:`assertion_id`) —
    the log never re-hashes, it only relies on the invariant that the id excludes ``parents`` and
    ``provenance`` (mem:063).
    """

    id: str
    #: What ``body`` asserts, so the fold can dispatch: ``"memory"``, ``"link"``, ``"task"``,
    #: ``"resolution"`` (mem:062 — a contradiction/near-dup resolution is itself an append), …
    kind: str
    #: The semantic payload the id content-addresses (the node/edge the fold will materialize).
    body: dict
    #: Causal frontier — the ids this assertion was *authored-after* (the writer's known-and-folded
    #: set). Defines the partial order :func:`causal_order` linearizes. NOT part of the id (mem:063).
    parents: tuple[str, ...] = ()
    #: Attribution (actor/session/model/commit-sha/ts), one record per independent assertion of this
    #: content. A single write carries a one-element list; identical-content collapse UNIONs the lists
    #: (mem:060). Never part of the id.
    provenance: list[dict] = field(default_factory=list)


def _canonical(value: Any) -> Any:
    """Order-independent normalization for content hashing: sets/lists of scalars sort; dicts recurse.

    Mirrors :func:`yigraf.memory.memory_id`'s ``sorted(...)`` discipline so the id is stable regardless
    of the order a caller happened to build the payload in.
    """
    if isinstance(value, dict):
        return {k: _canonical(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple, set)):
        items = [_canonical(v) for v in value]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False))
    return value


def assertion_id(kind: str, body: dict) -> str:
    """Content-address a log-native assertion by ``(kind, body)`` ONLY (``assertid-v1``, mem:063).

    Generalizes memid-v1: the id hashes *what the assertion says*, never its causal parents or
    provenance — so the same claim asserted by two writers collapses to one id. Families with their
    own recipe (memory → ``mem:<hash>``) mint their id there and pass it straight through; this is for
    edges/links/resolutions that have no bespoke recipe yet.
    """
    payload = {"algo": ASSERTION_ID_ALGO, "kind": kind, "body": _canonical(body)}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def causal_order(assertions: Iterable[Assertion]) -> list[Assertion]:
    """Deterministically linearize the causal-parent DAG (Kahn's algorithm, content-id tiebreak).

    The contract every :meth:`Log.iter_assertions_in_causal_order` must satisfy: for each assertion,
    every parent that is *present in the log* is yielded before it. Concurrent assertions (neither in
    the other's causal history) are ordered by ``id`` so the linearization is reproducible and
    substrate-independent (mem:056080f0) — the online seq-ordered substrate and the local file
    substrate produce the same order for the same content.

    Fail-open (R5): parents naming ids absent from ``assertions`` (a partial replica / dangling causal
    ref) are ignored for ordering — the fold tolerates missing content. A cycle (append-only makes this
    impossible; guards a corrupt input) never hangs: once no zero-in-degree node remains, the rest are
    flushed in id order.
    """
    by_id: dict[str, Assertion] = {}
    for a in assertions:  # last-write-wins on an exact id dupe; real collapse happens in append()
        by_id[a.id] = a

    # In-degree counts only intra-log parent edges; children maps parent -> its dependents.
    indegree: dict[str, int] = {aid: 0 for aid in by_id}
    children: dict[str, list[str]] = defaultdict(list)
    for aid, a in by_id.items():
        for parent in a.parents:
            if parent in by_id:
                indegree[aid] += 1
                children[parent].append(aid)

    ready = [aid for aid, deg in indegree.items() if deg == 0]
    heapq.heapify(ready)  # a min-heap on id gives the deterministic tiebreak
    ordered: list[Assertion] = []
    while ready:
        aid = heapq.heappop(ready)
        ordered.append(by_id[aid])
        for child in children[aid]:
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, child)

    if len(ordered) < len(by_id):  # cycle: flush the remainder deterministically, never hang (R5)
        placed = {a.id for a in ordered}
        ordered += [by_id[aid] for aid in sorted(by_id) if aid not in placed]
    return ordered


@runtime_checkable
class Log(Protocol):
    """The transport-agnostic write substrate. Concrete logs (in-memory here; git-file local at task
    #5/#6, Postgres online at task #7) implement exactly these two methods — nothing else varies."""

    def append(self, assertion: Assertion) -> Assertion:
        """Durably record ``assertion``. Idempotent on ``id``: re-appending identical content MUST
        collapse into the existing entry (union its ``parents``, extend its ``provenance``), never
        duplicate (mem:060/063). Returns the stored (possibly merged) assertion."""
        ...

    def iter_assertions_in_causal_order(self) -> Iterable[Assertion]:
        """Yield every stored assertion honoring the :func:`causal_order` contract. This is the sole
        seam the fold sees; substrates differ only in how they realize the ordering (mem:059)."""
        ...


def merge_assertion(existing: Assertion, incoming: Assertion) -> Assertion:
    """Collapse two assertions that share an id (⇒ identical content, mem:063): union their causal
    frontier and concatenate provenance (dedup identical records). This is the mechanism by which
    independent rediscoveries strengthen one node instead of forking it (mem:060)."""
    parents = list(existing.parents) + [p for p in incoming.parents if p not in existing.parents]
    provenance = list(existing.provenance)
    for record in incoming.provenance:
        if record not in provenance:
            provenance.append(record)
    return replace(existing, parents=tuple(parents), provenance=provenance)


class InMemoryLog:
    """Reference substrate — proves the :class:`Log` interface and is what task #3's fold is developed
    and tested against before any durable substrate exists. No persistence; not for production use."""

    def __init__(self) -> None:
        self._by_id: dict[str, Assertion] = {}

    def append(self, assertion: Assertion) -> Assertion:
        existing = self._by_id.get(assertion.id)
        stored = merge_assertion(existing, assertion) if existing else assertion
        self._by_id[assertion.id] = stored
        return stored

    def iter_assertions_in_causal_order(self) -> Iterable[Assertion]:
        return causal_order(self._by_id.values())
