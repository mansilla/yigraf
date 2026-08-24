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

from yigraf.astnorm import (ANCHOR_ALGO, EMPTY_SECTION_HASH, SECTION_ANCHOR_ALGO,
                           parse_file_target)

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
    #: The commit the drifted anchor was stamped at, when the edge recorded one
    #: (:class:`yigraf.artifacts.Implements`) — what dates a STALE completion. ``None`` for a `concerns`
    #: anchor (memories re-stamp through `reaffirm`, which reports its own outcome) and for any anchor
    #: stamped before the field existed, so every reader must degrade rather than assume it.
    stamped_at: str | None = None


#: The anchor algos whose hash survives a rename, so a dangling edge can be re-anchored by matching it.
#: ``astnorm-v1``: a symbol's hash excludes its own declared name (R10). ``mdsec-v1``: a section's hash
#: excludes its own heading text, for exactly the same reason and with the same consequence
#: (mem:a65f1ccad03b765e). ``file-sha256-v1`` is absent and stays absent — a whole file or a line range
#: has no name held out of its hash, so a "match" would mean two identical files, not a move.
_RENAMEABLE_ALGOS = frozenset({ANCHOR_ALGO, SECTION_ANCHOR_ALGO})


def _rename_scope(algo: str, locator: str) -> str:
    """The space within which ``locator``'s hash is allowed to identify a move.

    Empty for a symbol: moving a function to another file **is** a rename, and the whole graph of
    indexed symbols is the candidate set. A section's own *file* for ``mdsec-v1``, because a section
    cannot attest that it moved documents — and unlike symbols, docs are deliberately not indexed, so
    the candidate set is not "every section that exists" but "the few some assertion happens to
    govern". A `## License` deleted from one governed doc then matched the identically-worded section
    of an unrelated one and reported ``renamed`` (D1): a belief silently relocated onto prose it never
    governed, in a file it never named. ``artifacts.section_locator_for_anchor`` already scoped to one
    file; this is the same rule where the lookup actually happens.
    """
    return parse_file_target(locator)[0] if algo == SECTION_ANCHOR_ALGO else ""


def _hash_index(graph: nx.DiGraph) -> dict[tuple[str, str, str], list[str]]:
    """Map each rename-capable structure node's ``(algo, scope, content_hash)`` to its ids (sorted).

    Keyed by algo so a match can only ever be found in the hash space that produced the anchor — the
    same "compare like against like" rule :func:`compute_drift` applies to soft drift, and what keeps
    the ``astnorm-v2``-bump protection intact now that a second rename-capable algo exists. Keyed by
    scope for the reason :func:`_rename_scope` gives.
    """
    index: dict[tuple[str, str, str], list[str]] = {}
    for node_id, attrs in graph.nodes(data=True):
        algo = attrs.get("hash_algo", ANCHOR_ALGO)
        content = attrs.get("content_hash")
        if (attrs.get("family") != "structure" or content is None
                or algo not in _RENAMEABLE_ALGOS):
            continue
        if algo == SECTION_ANCHOR_ALGO and content == EMPTY_SECTION_HASH:
            continue  # a body-less section identifies nothing (astnorm.EMPTY_SECTION_HASH)
        index.setdefault((algo, _rename_scope(algo, node_id), content), []).append(node_id)
    for ids in index.values():
        ids.sort()
    return index


def resolve_renames(graph: nx.DiGraph) -> None:
    """Re-anchor rename/move dangling drift-bearing edges in place (mutates ``graph``).

    For each node's ``dangling_implements`` / ``dangling_concerns`` entry, look its anchor up among
    structure nodes: a unique hit is a rename → add the edge to the new locator (tagged
    ``renamed_from``) and clear the entry. Zero hits = real hard drift; multiple hits = ambiguous →
    left dangling, not guessed (§3). The same logic serves both relations (``concerns`` for free).

    It also serves a **renamed markdown heading**, which reaches here the same way a renamed symbol
    does even though docs carry no index: ``artifacts.mint_locus_node`` puts the moved section into the
    graph under its new locator when the stored anchor still matches it, and the lookup below finds it.

    The re-anchor is **in-memory only** and stays that way by design; :func:`yigraf.cli._settle_renames`
    is what makes it durable, and the ``renamed_from`` tag this leaves behind is exactly the proof that
    settle path (and ``link``'s) is allowed to act on.
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
                matches = (index.get((algo, _rename_scope(algo, entry["sym"]), anchor), [])
                           if anchor and algo in _RENAMEABLE_ALGOS else [])
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
                                   relation=relation, stamped_at=attrs.get("stamped_at")))

    for node_id, node_attrs in graph.nodes(data=True):
        if node_id in superseded:  # a superseded decision's dangling concern is historical — no nag
            continue
        for relation, attr in _DRIFT_RELATIONS.items():
            for entry in node_attrs.get(attr, []):
                items.append(DriftItem("hard", node_id, entry["sym"], detail="symbol not found",
                                       relation=relation, stamped_at=entry.get("stamped_at")))

    items.sort(key=lambda it: (it.kind, it.task_id, it.locator))
    return items


def is_surfaced(graph: nx.DiGraph, item: DriftItem) -> bool:
    """Whether a drift item belongs in the *surfaced* signal — the ``yigraf drift`` report, the
    ``context`` drift lines, and the statusline drift count — as opposed to the full set
    :func:`compute_drift` returns for internal use.

    int:drift-done-suppression: ``implements``-edge drift on a task the plan marks **done** is
    provenance, not a re-verify prompt — a closed task has no honest re-verification, and relinking it
    only rubber-stamps the anchor (the dishonesty mem:031/mem:039 guard against). So it is withheld from
    what the agent sees. :func:`compute_drift` still emits it: the full set feeds
    ``retrieval._verified_reconcile``, which needs a done task's stale link to flag its ``satisfied``
    intent as no-longer-verified. Done-ness is the build-derived ``state`` attr (checkboxes are truth,
    R6) — never stored drift state.
    """
    if item.relation == "implements" and item.task_id in graph.nodes:
        if graph.nodes[item.task_id].get("state") == "done":
            return False
    # SOFT ``grounded_by`` drift defends the *empirical tier* — "the evidence changed, so that certainty
    # is now unearned" (mem:054). Once the author has honestly downgraded to `inferred`, the demotion it
    # exists to trigger has already happened, so continuing to nag makes the downgrade — one of the two
    # exits the line itself offers — a no-op, and trains the reader to clear a badge no verb can clear
    # (feedback-v4 #2). HARD drift still surfaces at any tier: a citation pointing at something that no
    # longer exists is broken regardless of how strongly it was claimed, and `unlink` reaches it.
    if (item.relation == "grounded_by" and item.kind == "soft"
            and graph.nodes.get(item.task_id, {}).get("grounding") != "empirical"):
        return False
    return True


def is_reverifiable(graph: nx.DiGraph, node_id: str) -> bool:
    """Whether asking a principal to "re-verify this still holds" about ``node_id`` is an honest prompt.

    The node-shaped counterpart to :func:`is_surfaced`, which answers the same question about an *edge*.
    Both exist because a drifted symbol reaches governed nodes two ways — the anchored edge that drifted
    (``is_surfaced``) and the typed reverse-reachability ripple in ``cli._blast_reconcile_lines`` — and
    the ripple must not re-surface what the direct path deliberately withheld.

    Three states have no honest re-verification, one per authored family:

    - a **done task** — int:drift-done-suppression: a closed task's drift is provenance, and re-``link``
      only rubber-stamps the anchor (the dishonesty mem:031/mem:039 guard against). This is the same
      rule :func:`is_surfaced` applies to ``implements``, restated per-node so it also covers a done task
      reached by a *derived* relation (``depends_on`` over ``implements ∘ calls``), which the edge form
      never sees. It is also already counted, once, as a STALE completion.
    - a **superseded memory** (``superseded_in > 0``) — a retracted belief. Reaffirming it would re-assert
      a claim its own successor withdrew; it stays readable as a rejected alternative (memory.py) but is
      not a live obligation. A *pending* supersede does not count, matching ``retrieval._premise_holds``.
    - an **archived intent** — the goal that justified the governance is retired.

    Non-authored nodes (``sym:``/``file:``) and anything unrecognized pass: never invent a suppression
    for a family whose liveness this module does not model.
    """
    if node_id not in graph.nodes:
        return False
    attrs = graph.nodes[node_id]
    family = attrs.get("family")
    if family == "plan":
        return attrs.get("state") != "done"
    if family == "memory":
        return attrs.get("status", "active") == "active" and not attrs.get("superseded_in", 0)
    if family == "intent":
        return attrs.get("status") != "archived"
    return True


def is_stale_completion(graph: nx.DiGraph, item: DriftItem) -> bool:
    """Whether ``item`` is a STALE completion: a done task's ``implements`` drift (int:drift-as-stale).

    Named rather than derived as ``not is_surfaced(...)`` because those stopped being complements
    (feedback-v4 #2): ``is_surfaced`` now also withholds soft ``grounded_by`` drift on a belief that is
    no longer ``empirical`` — an item that belongs to *neither* list, the honest downgrade having
    already resolved it. Three callers partitioned on the inversion and would have relabelled it
    "stale", turning one fixed message into a wrong count on the surface that message points at.
    """
    return (item.relation == "implements" and item.kind in ("soft", "hard")
            and graph.nodes.get(item.task_id, {}).get("state") == "done")


def stale_completions(graph: nx.DiGraph) -> list[DriftItem]:
    """Done tasks whose implementing symbol drifted (int:drift-as-stale): the *completion* is STALE —
    the shipped work's evidence changed, so ``done`` is no longer verified.

    This is exactly the implements drift :func:`is_surfaced` withholds from the agent's edit hook
    (int:drift-done-suppression / mem:056): a closed task must not nag mid-edit or train the reflexive
    relink mem:031/mem:039 guard against. But it *is* a coherence signal for the principal, so the
    status / ``context`` query / SessionStart surfaces show it as STALE — never the action-moment edit
    hook (mem:81edb: belief-state bookkeeping is principal-facing). Derived, never stored (R6); STALE is
    not ``false`` — the completion is re-verifiable, cleared by re-``link`` re-anchoring (or reopened if
    the change regressed it), never auto-flipped to ``todo``.
    """
    return [it for it in compute_drift(graph) if is_stale_completion(graph, it)]
