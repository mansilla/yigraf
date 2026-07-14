"""The local git-file :class:`~yigraf.log.Log` substrate: authored markdown → assertion log (task #6).

int:yigraf-local-v1 makes the source of truth "an append-only, content-addressed set of assertion
files committed to git." Those files are the intent/plan/memory markdown yigraf already writes — each
one *is* one assertion. This module is the read side of that substrate: it reads every authored
artifact into an :class:`~yigraf.log.Assertion` whose ``body`` is exactly the node + outgoing edges
:func:`yigraf.artifacts.project_into` / :func:`yigraf.memory.project_into` used to add directly, so
:func:`yigraf.fold.fold` over this log reproduces the family subgraph (the "rebuilds identically"
proof, ``tests/test_migrate.py``). This is the ``project_into`` → fold migration: once the fold is the
projection path, the two-pass hacks and the ``recompute_counters`` sweep are gone (fold docstring).

Two things make the single-pass fold resolve every cross-family edge without the old two passes:

- **causal parents carry the ordering.** Any edge whose target is *itself an assertion* (an
  ``int:``/``plan:``/``task:``/``mem:`` id — as opposed to a ``sym:``/``file:`` node that lives in the
  structure ``base``) is added to the source assertion's ``parents``. :func:`yigraf.log.causal_order`
  then guarantees the target is folded first, so the edge resolves on the single pass (mem:98d5a556).
  A ``sym:``/``file:`` target needs no parent — it is already in the ``base`` graph.
- **the body IS the source claim.** Derived belief (``accepted``/``superseded_in``/``supersedes_out``)
  is never emitted here — the fold recomputes it from the whole set (mem:065017c08f97dcbf). Provenance
  rides the envelope as a one-element list (mem:063), not the body, so identical-content collapse unions
  it. Everything else project_into set as a node attr is a source claim and is emitted verbatim.

``append`` is intentionally not implemented: durable writes still go through the authoring verbs
(``remember``/``link``/``supersede`` render the markdown), so this substrate only supplies the fold's
read seam. Wiring writes onto the log is later (online, tasks #7–#9)."""
from __future__ import annotations

from pathlib import Path

from yigraf import artifacts, memory
from yigraf.artifacts import CONF, Intent, Plan
from yigraf.astnorm import ANCHOR_ALGO
from yigraf.log import Assertion, causal_order

#: An edge target that is itself an assertion (folded from the log) rather than a structure ``base``
#: node — so it must precede its referrer in causal order. ``sym:``/``file:``/``commit:``/url/text
#: targets live in the base graph (or are opaque) and never need a causal parent.
_LOG_FAMILIES = frozenset({"int", "plan", "task", "mem"})


def _is_log_id(target: str) -> bool:
    return target.split(":", 1)[0] in _LOG_FAMILIES


def _edge(relation: str, target: str, **attrs) -> dict:
    """One outgoing-edge spec in the assertion body contract. ``confidence`` is always ``CONF`` —
    authored artifacts are asserted truth, matching project_into's per-edge ``confidence=CONF``."""
    return {"relation": relation, "target": target, "attrs": {"confidence": CONF, **attrs}}


def _intent_assertion(intent: Intent) -> Assertion:
    """One intent artifact → one assertion. Mirrors :func:`yigraf.artifacts.project_into`'s intent node
    plus its int→int ``supersedes`` reversal edges (the second pass, now a causal parent)."""
    attrs = {
        "kind": intent.type,
        "label": intent.statement or intent.slug,
        "confidence": CONF,
        "status": intent.status,
        "statement": intent.statement,
        "scenarios": intent.scenarios,
        "design": intent.design,
        "attestation": intent.attestation,
        "source_file": f"intents/{intent.slug}.md",
    }
    edges = [_edge("supersedes", old) for old in intent.supersedes]
    return Assertion(
        id=intent.id,
        kind=artifacts.INTENT_FAMILY,
        body={"family": artifacts.INTENT_FAMILY, "attrs": attrs, "edges": edges},
        parents=tuple(old for old in intent.supersedes if _is_log_id(old)),
    )


def _plan_assertions(plan: Plan) -> list[Assertion]:
    """One plan artifact → the plan assertion (``contains`` each task) + one assertion per task.

    The plan takes its tasks as causal parents so the ``contains`` edges resolve on the single pass;
    each task carries its ``tracks``/``requires``/``implements`` edges exactly as project_into did."""
    out: list[Assertion] = []
    for task in plan.tasks:
        attrs = {
            "kind": "task",
            "label": task.description,
            "confidence": CONF,
            "state": task.state,
            "order": task.num,
        }
        edges: list[dict] = []
        parents: list[str] = []
        if task.tracks is not None:
            edges.append(_edge("tracks", task.tracks))
            if _is_log_id(task.tracks):
                parents.append(task.tracks)
        for req in task.requires:
            edges.append(_edge("requires", req))
            if _is_log_id(req):
                parents.append(req)
        for impl in task.implements:
            extra = {}
            if impl.anchor is not None:  # project_into only stamps the anchor when it exists
                extra = {"anchor": impl.anchor, "anchor_algo": impl.anchor_algo or ANCHOR_ALGO}
            edges.append(_edge("implements", impl.sym, **extra))
            if _is_log_id(impl.sym):
                parents.append(impl.sym)
        out.append(Assertion(
            id=task.id,
            kind=artifacts.PLAN_FAMILY,
            body={"family": artifacts.PLAN_FAMILY, "attrs": attrs, "edges": edges},
            parents=tuple(parents),
        ))

    plan_attrs = {"kind": "plan", "label": plan.title, "confidence": CONF, "phase": plan.phase}
    out.append(Assertion(
        id=plan.id,
        kind=artifacts.PLAN_FAMILY,
        body={"family": artifacts.PLAN_FAMILY, "attrs": plan_attrs,
              "edges": [_edge("contains", t.id) for t in plan.tasks]},
        parents=tuple(t.id for t in plan.tasks),  # tasks fold before the plan that contains them
    ))
    return out


def _memory_assertion(mem) -> Assertion:
    """One memory artifact → one assertion. Mirrors :func:`yigraf.memory.project_into`'s node + its
    ``serves``/``concerns``/``grounded_by``/``supersedes``/``equivalent_to`` edges (both passes).

    Derived belief is never emitted (the fold computes it); provenance rides the envelope as a
    one-element list so identical-content collapse unions it (mem:063). An opaque evidence ref
    (``commit:``/url/text — no in-repo locus to anchor) is recorded as an ``opaque_evidence`` node attr,
    exactly as project_into stashed it, never an edge."""
    attrs = {
        "kind": mem.type,
        "label": mem.statement or mem.slug,
        "confidence": CONF,
        "status": mem.status,
        "maturity": mem.maturity,
        "grounding": mem.grounding,
        "attestation": mem.attestation,
        "statement": mem.statement,
        "why": mem.why,
        "alternatives": mem.alternatives,
        "promotable": mem.promotable,
        "source_file": mem.source_file or f"memory/{mem.seq:03d}-{mem.slug}.md",
    }
    if mem.rejected_valid_when:
        attrs["rejected_valid_when"] = list(mem.rejected_valid_when)
    if mem.rejected_invalidated_when:
        attrs["rejected_invalidated_when"] = list(mem.rejected_invalidated_when)

    edges: list[dict] = [_edge("serves", t) for t in mem.serves]
    for concern in mem.concerns:
        extra = {}
        if concern.anchor is not None:
            extra = {"anchor": concern.anchor, "anchor_algo": concern.anchor_algo or ANCHOR_ALGO}
        edges.append(_edge("concerns", concern.sym, **extra))

    opaque: list[str] = []
    for ev in mem.evidence:
        if ev.anchor is None and not (ev.ref.startswith("sym:") or ev.ref.startswith("file:")):
            opaque.append(ev.ref)  # commit:/url/text — no locus to hash → node attr, never an edge
        else:
            edges.append(_edge("grounded_by", ev.ref, anchor=ev.anchor,
                               anchor_algo=ev.anchor_algo or ANCHOR_ALGO))
    if opaque:
        attrs["opaque_evidence"] = opaque

    edges += [_edge("supersedes", old) for old in mem.supersedes]
    edges += [_edge("supersedes", old, pending=True) for old in mem.pending_supersedes]
    edges += [_edge("equivalent_to", peer) for peer in mem.equivalent_to]

    # Causal parents: every edge whose target is itself an assertion (serves→intent, supersedes→memory,
    # equivalent_to→memory). concerns/grounded_by point at structure/base nodes and need no parent.
    referents = (list(mem.serves) + list(mem.supersedes) + list(mem.pending_supersedes)
                 + list(mem.equivalent_to))
    provenance = [dict(mem.provenance)] if mem.provenance else []
    return Assertion(
        id=mem.id,
        kind=memory.MEMORY_FAMILY,
        body={"family": memory.MEMORY_FAMILY, "attrs": attrs, "edges": edges},
        parents=tuple(r for r in referents if _is_log_id(r)),
        provenance=provenance,
    )


def assertions_from_repo(root: Path) -> list[Assertion]:
    """Read every authored intent/plan/memory artifact under ``root`` into the assertion log (unordered;
    :func:`yigraf.log.causal_order` linearizes). Reuses the family readers so parsing stays single-sourced."""
    root = Path(root)
    out: list[Assertion] = [_intent_assertion(i) for i in artifacts.iter_intents(root)]
    for plan in artifacts.iter_plans(root):
        out += _plan_assertions(plan)
    out += [_memory_assertion(m) for m in memory.iter_memories(root)]
    return out


#: The fold stashes every unresolved edge on one ``dangling_edges`` list (family-agnostic); the drift
#: and retrieval read paths still expect project_into's per-relation ``dangling_*`` keys. This maps a
#: relation to (attr name, is-anchored): an anchored dangling (implements/concerns/grounded_by, which
#: :mod:`yigraf.drift` rename-re-anchors) becomes a ``{sym, anchor, anchor_algo}`` dict; the rest become
#: bare target strings — exactly the two shapes project_into stashed.
_TYPED_DANGLING = {
    "serves": ("dangling_serves", False),
    "concerns": ("dangling_concerns", True),
    "grounded_by": ("dangling_grounded_by", True),
    "supersedes": ("dangling_supersedes", False),
    "equivalent_to": ("dangling_equivalent_to", False),
    "tracks": ("dangling_tracks", False),
    "requires": ("dangling_requires", False),
    "implements": ("dangling_implements", True),
}


def inject_base_anchors(graph, root: Path) -> None:
    """Add the ``file:`` anchor nodes the asserted edges attach to, before the fold runs.

    project_into created these inline (an infra/glue file a task ``implements`` or a memory ``concerns``
    has no extracted symbol, so its node is minted here with the file's current SHA — friend-review #12).
    The fold only materializes the assertion families, so this must run first, onto the structure ``base``,
    for those ``file:`` edges to resolve rather than dangle."""
    artifacts._project_file_anchor_nodes(graph, root, artifacts.iter_plans(root))
    memory._project_file_anchor_nodes(graph, root, memory.iter_memories(root))


def denormalize_danglings(graph) -> None:
    """Rewrite each node's family-agnostic ``dangling_edges`` into project_into's per-relation
    ``dangling_*`` keys, so :mod:`yigraf.drift` (rename re-anchoring, hard-drift) and retrieval read them
    unchanged. Pure shape-bridging over the fold's output; leaves the resolved graph identical."""
    for _, attrs in graph.nodes(data=True):
        dangling = attrs.pop("dangling_edges", None)
        if not dangling:
            continue
        for edge in dangling:
            attr, anchored = _TYPED_DANGLING[edge["relation"]]
            if anchored:
                ea = edge.get("attrs") or {}
                entry = {"sym": edge["target"], "anchor": ea.get("anchor"),
                         "anchor_algo": ea.get("anchor_algo")}
            else:
                entry = edge["target"]
            attrs.setdefault(attr, []).append(entry)


class FileLog:
    """The local git-file :class:`~yigraf.log.Log`: the authored markdown artifacts, read as an
    assertion log the fold consumes. Writes still go through the authoring verbs (they render the
    markdown), so :meth:`append` is unimplemented — this substrate supplies only the fold's read seam."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def append(self, assertion: Assertion) -> Assertion:  # pragma: no cover - writes go through the verbs
        raise NotImplementedError(
            "FileLog is read-only: durable writes go through the authoring verbs (remember/link/"
            "supersede), which render the markdown files this log reads back.")

    def iter_assertions_in_causal_order(self):
        return causal_order(assertions_from_repo(self.root))
