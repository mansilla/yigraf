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

from dataclasses import replace
from pathlib import Path

from yigraf import artifacts, memory, resolution
from yigraf.artifacts import CONF, Intent, Plan
from yigraf.astnorm import ANCHOR_ALGO
from yigraf.log import Assertion, assertion_id, causal_order

#: An edge target that is itself an assertion (folded from the log) rather than a structure ``base``
#: node — so it must precede its referrer in causal order. ``sym:``/``file:``/``commit:``/url/text
#: targets live in the base graph (or are opaque) and never need a causal parent.
_LOG_FAMILIES = frozenset({"int", "plan", "task", "mem"})


def _is_log_id(target: str) -> bool:
    return target.split(":", 1)[0] in _LOG_FAMILIES


# --------------------------------------------------------------------------------------------------
# Revisions — the two families whose LOCATOR is stable while their BODY changes
# --------------------------------------------------------------------------------------------------
#
# mem:063 defines an assertion ``id`` as the content-hash of its ``body``: two writers who say the same
# thing mint the same id and COLLAPSE. Every downstream mechanism reads it that way —
# :func:`~yigraf.log.merge_assertion` keeps the existing body on an id match, :func:`causal_order` keeps
# the last, and the fold uses the id as the graph NODE id (so one id is one node, never two beliefs to
# compare).
#
# Intents and tasks broke that invariant: their id was a slug (``int:<slug>``) and a positional locator
# (``task:<plan>/<n>``) while their MUTABLE state — a task's ``[ ]``/``[x]`` and its ``implements``
# anchors, an intent's ``status`` — lived in the body. The consequences were all silent. Once a locator
# had been pushed, ``yigraf sync``'s push set (``a.id not in known_ids``) skipped every later edit as
# already-known, so re-anchors, completions and ``--status satisfied`` never propagated; and where a
# revision did reach the replica, the three sites above each picked a different winner.
#
# So the id carries the revision and the body carries the locator. The fold materializes the node under
# the ``locator`` (:func:`yigraf.fold._apply`), so every cross-family edge still targets ``task:plan/1``
# and nothing downstream changes — while the push set becomes correct for free, since an edited body is
# a new id the log has not seen.
#
# Which revision of a locator is LIVE is decided by design law #6, not by a clock: these families' truth
# is a git-committed FILE, and the log is a derived projection of it. The local working tree wins, and a
# replica revision may not overwrite it (:func:`yigraf.extract._fold_replica`). Two people editing one
# plan concurrently is a git merge on the markdown — the same place every other conflict in the repo is
# already resolved — never a last-writer-wins race in the log.


#: The families whose truth is a git-committed FILE, not the log (design law #6). The local working
#: tree decides which body is live; a replica assertion naming a node this workspace already
#: materialized is declined rather than merged (:func:`yigraf.fold.fold_assertions`'s
#: ``defer_families``, applied in :func:`yigraf.extract._fold_replica`). This is ALL FOUR authored
#: families — every one of them is a ``.md`` file the principal edits.
#:
#: Memory and resolution were initially excluded, on the reasoning that they are content-addressed, so
#: a same-id assertion is the same claim and a genuine disagreement is two DIFFERENT ids that
#: :mod:`yigraf.contradiction` surfaces as a knowledge conflict. That is true of the CLAIM and false of
#: the ASSERTION. :func:`yigraf.memory.memory_id` hashes what a memory claims — statement, why,
#: rejected — and deliberately not its drift anchors, because a re-anchor must not mint a new belief.
#: So ``reaffirm`` and ``link`` produce the same id with a DIFFERENT body, which is exactly the
#: invariant break revisioning fixed for intents and tasks, and it failed the same two ways: `yigraf
#: sync`'s push set (``a.id not in known_ids``) skipped the re-anchor as already-known so it never
#: propagated, and the replica fold — running after the local one — overwrote the fresh anchor with the
#: pushed one, so `yigraf drift` re-reported drift the principal had just cleared and no amount of
#: reaffirming could clear it.
#:
#: Deferring costs the collapse union (mem:060): when two principals mint the same claim the replica's
#: provenance and scope are dropped rather than unioned, so attribution reads local. That is the same
#: trade already taken for intent/plan, and it is the right side of it — a belief you can see in your
#: own working tree should not be narrated by someone else's copy of it. Note the deferral is keyed on
#: the NODE being present, so a teammate's memory you do not have folds normally; only a competing copy
#: of a node you already hold is declined.
FILE_TRUTH_FAMILIES = frozenset({artifacts.INTENT_FAMILY, artifacts.PLAN_FAMILY,
                                 memory.MEMORY_FAMILY, resolution.RESOLUTION_FAMILY})


def _revision_id(locator: str, kind: str, body: dict) -> str:
    """``<locator>@<content-hash>`` — a mutable family's assertion id.

    Keeps the locator legible and prefix-parseable (``_is_log_id`` and every ``id.split(':')`` reader
    still see ``task``/``int``) while making the id honor mem:063: a different body is a different
    assertion. ``parents``/``provenance`` stay out of the hash, exactly as :func:`assertion_id` requires,
    so two people who tick the same task to the same state still collapse to one event.
    """
    return f"{locator}@{assertion_id(kind, body)}"


def _resolve_parents(assertions: list[Assertion]) -> list[Assertion]:
    """Rewrite causal parents from LOCATORS to the current revision ids they name.

    The family builders emit parents as locators, because that is what an edge target is. But a parent
    must name an *assertion*, and for a revisioned family the assertion is the revision — so a parent of
    ``int:foo`` becomes ``int:foo@<rev>``. Without this the online log's prefix-closed check
    (:func:`yigraf.onlinelog.validate_ingest`) would reject every dependent assertion, and
    :func:`causal_order` would silently drop the ordering constraint that makes edges resolve in one pass.

    A locator with no local revision (a dangling reference) is left as-is — fail-open (R5), and exactly
    the behaviour it had before revisions existed.
    """
    by_locator = {a.body["locator"]: a.id for a in assertions if a.body.get("locator")}
    if not by_locator:
        return assertions
    return [replace(a, parents=tuple(dict.fromkeys(by_locator.get(p, p) for p in a.parents)))
            for a in assertions]


def _edge(relation: str, target: str, **attrs) -> dict:
    """One outgoing-edge spec in the assertion body contract. ``confidence`` is always ``CONF`` —
    authored artifacts are asserted truth, matching project_into's per-edge ``confidence=CONF``."""
    return {"relation": relation, "target": target, "attrs": {"confidence": CONF, **attrs}}


def _intent_assertion(intent: Intent) -> Assertion:
    """One intent artifact → one assertion. Mirrors :func:`yigraf.artifacts.project_into`'s intent node
    plus its int→int ``supersedes`` reversal edges (the second pass, now a causal parent).

    Revisioned: ``status`` (and the statement itself) are mutable, so the id is
    ``int:<slug>@<rev>`` and the node id stays ``int:<slug>`` via ``body.locator``."""
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
    body = {"family": artifacts.INTENT_FAMILY, "locator": intent.id, "attrs": attrs, "edges": edges}
    return Assertion(
        id=_revision_id(intent.id, artifacts.INTENT_FAMILY, body),
        kind=artifacts.INTENT_FAMILY,
        body=body,
        parents=tuple(old for old in intent.supersedes if _is_log_id(old)),
    )


def _plan_assertions(plan: Plan) -> list[Assertion]:
    """One plan artifact → the plan assertion (``contains`` each task) + one assertion per task.

    The plan takes its tasks as causal parents so the ``contains`` edges resolve on the single pass;
    each task carries its ``tracks``/``requires``/``implements`` edges exactly as project_into did.

    Both are revisioned (``@<rev>`` ids, ``body.locator`` node ids): a task's ``state`` and its
    ``implements`` anchors are the most-edited bodies in the repo, and they were the ones a fixed id
    made invisible to sync. The plan node revises too — its ``contains`` set changes when a task is
    added — so it is not a special case."""
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
        body = {"family": artifacts.PLAN_FAMILY, "locator": task.id, "attrs": attrs, "edges": edges}
        out.append(Assertion(
            id=_revision_id(task.id, artifacts.PLAN_FAMILY, body),
            kind=artifacts.PLAN_FAMILY,
            body=body,
            parents=tuple(parents),
        ))

    plan_attrs = {"kind": "plan", "label": plan.title, "confidence": CONF, "phase": plan.phase}
    plan_body = {"family": artifacts.PLAN_FAMILY, "locator": plan.id, "attrs": plan_attrs,
                 "edges": [_edge("contains", t.id) for t in plan.tasks]}
    out.append(Assertion(
        id=_revision_id(plan.id, artifacts.PLAN_FAMILY, plan_body),
        kind=artifacts.PLAN_FAMILY,
        body=plan_body,
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
        # Pinning rides the assertion because it is authored state on the artifact, like `promotable`
        # — a teammate who pins a house rule should have it pinned for everyone who folds the log.
        # It is outside the memory *id* (mem:063's semantic payload) for the same reason: it changes
        # nothing about what the belief says, so it must not fork the node from an identical capture.
        "pinned": mem.pinned,
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


def _resolution_assertion(res) -> Assertion:
    """One resolution artifact → one assertion (mem:062: a verdict is an append, not an edit).

    Unlike every other family, the edge that *carries the verdict* runs between the two beliefs rather
    than out of this node — emitted as a ``projections`` entry with an explicit ``source`` so the fold
    can add it without the resolving principal owning either operand (:mod:`yigraf.resolution`). The
    node's own ``resolves`` edges keep the verdict attributable and traversable from either side.
    """
    attrs = {
        "kind": res.kind,
        "label": f"{res.kind}: {res.left} ↔ {res.right}",
        "confidence": CONF,
        "left": res.left,
        "right": res.right,
        "why": res.why,
        "source_file": res.source_file or f"resolutions/{res.kind}-{res.id.split(':', 1)[1]}.md",
    }
    edges = [_edge("resolves", res.left), _edge("resolves", res.right)]
    projections = [{"source": res.left, "relation": res.relation, "target": res.right,
                    "attrs": {"confidence": CONF, "via": res.id}}]
    provenance = [dict(res.provenance)] if res.provenance else []
    return Assertion(
        id=res.id,
        kind=resolution.RESOLUTION_FAMILY,
        body={"family": resolution.RESOLUTION_FAMILY, "attrs": attrs,
              "edges": edges, "projections": projections},
        # Authored-after BOTH operands: causal order then guarantees each is folded before the verdict,
        # so the projected edge resolves on the single pass rather than dangling.
        parents=tuple(r for r in (res.left, res.right) if _is_log_id(r)),
        provenance=provenance,
    )


def assertions_from_repo(root: Path) -> list[Assertion]:
    """Read every authored intent/plan/memory/resolution artifact under ``root`` into the assertion log
    (unordered; :func:`yigraf.log.causal_order` linearizes). Reuses the family readers so parsing stays
    single-sourced.

    The parent rewrite runs last, over the whole set, because a parent locator can only be mapped to a
    revision id once every revision in the repo is known (a memory serving an intent is read after it,
    but a task requiring a later-numbered task is not)."""
    root = Path(root)
    out: list[Assertion] = [_intent_assertion(i) for i in artifacts.iter_intents(root)]
    for plan in artifacts.iter_plans(root):
        out += _plan_assertions(plan)
    out += [_memory_assertion(m) for m in memory.iter_memories(root)]
    out += [_resolution_assertion(r) for r in resolution.iter_resolutions(root)]
    return _resolve_parents(out)


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
    "disputes": ("dangling_disputes", False),
    "resolves": ("dangling_resolves", False),
    "tracks": ("dangling_tracks", False),
    "requires": ("dangling_requires", False),
    "implements": ("dangling_implements", True),
    #: project_into never stashed one of these — a plan and its tasks are read out of the same file, so
    #: locally a ``contains`` target is always there. The FOLD can see one: a plan assertion may arrive
    #: without the task assertions it names (a partial replica, or a since-cursor pull that starts after
    #: them), and then the plan's own edges are what dangle.
    "contains": ("dangling_contains", False),
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
    unchanged. Pure shape-bridging over the fold's output; leaves the resolved graph identical.

    Fail-open on a relation the map has not heard of, rather than ``KeyError``. This runs over every
    fold of a log, and the whole point of stashing an unresolved edge is that a partial replica still
    materializes (R5) — so a relation nobody wrote a bridge for must cost an unread attribute, not the
    graph. It is stashed under the same ``dangling_<relation>`` name it would have had, unanchored:
    every reader asks for a key by name, so an unclaimed one is inert."""
    for _, attrs in graph.nodes(data=True):
        dangling = attrs.pop("dangling_edges", None)
        if not dangling:
            continue
        for edge in dangling:
            relation = edge["relation"]
            attr, anchored = _TYPED_DANGLING.get(relation, (f"dangling_{relation}", False))
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
