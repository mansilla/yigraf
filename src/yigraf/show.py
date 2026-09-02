"""Read ONE node by id, in full — the unbudgeted counterpart to the budgeted slice.

Every other read surface in yigraf answers "what is relevant to X?" under a token budget. This one
answers "what does *this* say?", and it exists because the tool had opened a loop it could not close:
the drift lines, the conflict lines, and the manifest all hand the agent an id, and until now there
was no verb that took one. ``yigraf context "mem:<id>"`` semantic-searches the literal string and
returns proximity noise, which is worse than a refusal — it looks like an answer.

So this is deliberately NOT retrieval: no ranking, no traversal, no budget. One node, everything it
holds, plus the two things a caller acting on a drift line needs and the frontmatter alone doesn't
give — which of its anchors are currently drifting, and *which list* each drifted anchor lives in
(``concerns`` vs ``evidence``, cleared by different calls).
"""
from __future__ import annotations

from pathlib import Path

import networkx as nx

from yigraf.drift import compute_drift, is_surfaced, pending_renames
from yigraf.retrieval import RENAME_CLIFF, drift_tail, premise_holds, rename_verb

#: Prefixes that make a string a graph locator rather than a topic. ``yigraf context`` tests against
#: this too, so a query that is plainly an id is redirected here instead of being handed to the seeder.
LOCATOR_PREFIXES = ("mem:", "int:", "task:", "plan:", "sym:", "file:", "module:")


def looks_like_locator(text: str) -> bool:
    """Is ``text`` a bare graph locator (so a *query* for it is really a read-by-id)?

    Whitespace disqualifies it: ``"mem: what did we decide"`` is a question, not an id.
    """
    return text.startswith(LOCATOR_PREFIXES) and not any(c.isspace() for c in text)


def resolve(graph: nx.DiGraph, target: str) -> tuple[str | None, list[str]]:
    """Resolve ``target`` to one node id, returning ``(id, candidates)``.

    Exact hit wins. Otherwise try it as a **prefix** — of a full locator, and of a bare memory hash
    (``yigraf show 1678ce10``), because ids are 16 hex characters that nobody retypes correctly and a
    drift line the agent is copying from may well have been truncated by whatever printed it. A unique
    prefix resolves; an ambiguous one returns the candidates so the caller can print them rather than
    guess (the same never-guess rule ``drift.resolve_renames`` applies to an ambiguous rename).
    """
    if target in graph:
        return target, []
    lowered = target.casefold()
    matches = sorted(n for n in graph.nodes
                     if n.casefold().startswith(lowered)
                     or (n.startswith("mem:") and n[len("mem:"):].startswith(lowered)))
    if len(matches) == 1:
        return matches[0], []
    return None, matches


def _wrap(label: str, text: str, width: int = 96) -> list[str]:
    """A ``label: text`` field, soft-wrapped and hanging-indented under the label.

    Unlike everything in :mod:`yigraf.retrieval`, nothing here is truncated: a ``--why`` running to
    2500 characters is exactly what the caller came for — it is the content ``/clear`` destroys and the
    reason the node exists. Wrapping only makes it readable in a terminal.
    """
    import textwrap

    pad = " " * (len(label) + 2)
    body = textwrap.fill(text.strip(), width=width, initial_indent="", subsequent_indent=pad)
    return [f"{label}: {body}"]


def _drift_on(graph: nx.DiGraph, node_id: str) -> list:
    """Live drift items sourced from ``node_id`` (its own anchors), surfaced ones only."""
    return [i for i in compute_drift(graph)
            if i.task_id == node_id and i.kind != "renamed" and is_surfaced(graph, i)]


def _renames_on(graph: nx.DiGraph, node_id: str) -> list:
    """Unsettled renames sourced from ``node_id`` — the kind :func:`_drift_on` deliberately excludes.

    ``show`` reads one node rather than the obligation set, so excluding renames from its *drift* list is
    right: a rename is not drift, the content hash MATCHED. But excluding it from the node entirely made
    ``show`` the one agent-reachable surface that never mentioned the only signal with an **expiry**
    (feedback-v6 §8) — and worse than silent, because the artifact still names the locator the subject
    left, so :func:`_anchor_state` looked it up, missed, and called a rescued rename "hard drift — the
    locus is gone". That is the same false sentence F#2 removed from ``reaffirm``, on the surface an
    agent lands on holding an id from a drift line. So it gets its own block, with the settle verb.
    """
    return [i for i in pending_renames(graph) if i.task_id == node_id]


def _conflicts_on(graph: nx.DiGraph, node_id: str, root: Path | None, config: dict | None) -> list[str]:
    """Open knowledge-conflicts this node is a side of — the natural second home for the finding
    (feedback-v3 #1): a reader holding an id is the one most able to resolve a conflict that node is
    in, and until now six `show`s on candidate memories printed no conflict line while `status` read
    `⚠ 1 conflict`. Same wording as the Stop-hook notice (one wording, every surface)."""
    if root is None or config is None:
        return []
    from yigraf import obligations
    from yigraf.contradiction import detect_conflicts

    out: list[str] = []
    for c in detect_conflicts(graph, root, config):
        if node_id not in (c.left, c.right):
            continue
        ob = obligations._conflict(c, graph)
        other = c.right if c.left == node_id else c.left
        anchor = f" at {c.anchor}" if c.anchor else ""
        out.append(f"  ⟂ {other}{anchor}: {ob.detail}")
        out.append(f"    → {ob.verb}")
    return out


def _edges_out(graph: nx.DiGraph, node_id: str, relation: str) -> list[str]:
    return sorted(d for _, d, a in graph.out_edges(node_id, data=True) if a.get("relation") == relation)


def _edges_in(graph: nx.DiGraph, node_id: str, relation: str) -> list[str]:
    """Sources pointing at ``node_id`` over ``relation``, a held-pending supersede marked as such.

    The outbound list has always marked ``pending`` (the successor knows it is waiting); the inbound
    one built a plain string and never checked (feedback-v4 #3). That is the wrong half to leave
    silent: the still-authoritative predecessor is the node someone auditing the belief *in force*
    inspects, and it could not tell them a replacement was sitting there awaiting their endorsement.
    """
    out = []
    for src, _, a in graph.in_edges(node_id, data=True):
        if a.get("relation") != relation:
            continue
        out.append(f"{src}   (PENDING — {src} awaits `yigraf attest`; this node still holds)"
                   if a.get("pending") else src)
    return sorted(out)


def _memory_detail(graph: nx.DiGraph, node_id: str, attrs: dict) -> list[str]:
    tiers = [attrs.get("kind", "memory"), attrs.get("grounding", "inferred"),
             attrs.get("maturity", "working"), attrs.get("attestation", "agent")]
    if attrs.get("pinned"):
        tiers.append("pinned")
    if attrs.get("superseded_in", 0):
        tiers.append("SUPERSEDED")
    out = [f"{node_id}  [{' · '.join(str(t) for t in tiers)}]"]
    if attrs.get("source_file"):
        out.append(f"  yigraf/{attrs['source_file']}")
    out.append("")
    out += _wrap("  Statement", attrs.get("statement") or attrs.get("label", ""))
    if attrs.get("why"):
        out += _wrap("  Why      ", attrs["why"])
    if attrs.get("alternatives"):
        out += _wrap("  Rejected ", attrs["alternatives"])
        # Say whether the rejection is *currently in force*: a conditioned one whose premise lapsed is
        # still on the artifact but no longer steers, and retrieval silently drops it — so a reader of
        # the raw node would otherwise draw the opposite conclusion from what the packet shows.
        for field, verdict in (("rejected_valid_when", True), ("rejected_invalidated_when", False)):
            for ref in attrs.get(field, []):
                held = premise_holds(graph, ref)
                state = "holds" if held else "does not hold"
                effect = ("still applies" if held is verdict else "is withdrawn")
                out.append(f"    ({field.replace('_', '-')} {ref} {state} ⇒ the rejection {effect})")
    return out


def _anchor_state(graph: nx.DiGraph, ref: str, anchor: str | None, algo: str | None,
                  renamed: dict | None = None) -> str:
    """Whether one stored anchor still matches its target — the per-anchor form of ``compute_drift``.

    Computed here rather than read off an edge because a memory's two anchor lists can name the *same*
    symbol and ``nx.DiGraph`` keeps one edge per node pair: project ``concerns sym:X`` and then
    ``grounded_by sym:X`` and the second silently overwrites the first. That collapse is why the two
    ``reaffirm`` forms could each report success while the memory went on drifting — one of the two
    anchors was invisible to every edge-derived surface. The artifact holds both, so this compares
    against the artifact and the one surface whose job is "tell me everything about this node" tells
    the truth. The algo guard mirrors ``compute_drift``: a ``file:`` anchor is only ever compared
    against a file node's raw SHA, never an astnorm symbol hash.
    """
    from yigraf.astnorm import ANCHOR_ALGO

    # A rescued rename reaches this function looking exactly like hard drift — the artifact names the
    # old locator and no such node exists — so it must be tested FIRST or the node's own report calls a
    # repairable move permanent (feedback-v6 §8; the same confusion F#2 removed from `reaffirm`).
    item = (renamed or {}).get(ref)
    if item is not None:
        return f"   ⚠ renamed ⇒ {item.new_locator} — re-anchored in the graph, not yet in this file"
    if ref not in graph:
        return "   ⚠ hard drift — the locus is gone"
    if anchor is None:
        return ""  # never anchored (an opaque ref, or a pre-anchor artifact) ⇒ nothing to compare
    if (algo or ANCHOR_ALGO) != graph.nodes[ref].get("hash_algo", ANCHOR_ALGO):
        return ""
    current = graph.nodes[ref].get("content_hash")
    return "" if current is None or current == anchor else "   ⚠ soft drift — body changed since anchored"


def _memory_links(graph: nx.DiGraph, node_id: str, root: Path | None,
                  renamed: dict | None = None) -> list[str] | None:
    """A memory's anchors read from its ARTIFACT (files are truth, R6), or ``None`` if unreadable.

    See :func:`_anchor_state` for why the graph alone cannot answer this for a memory.
    """
    if root is None:
        return None
    from yigraf import memory as memory_mod

    path = memory_mod.find_memory(root, node_id)
    if path is None:
        return None
    node = memory_mod.read_memory(path)
    from yigraf.memory import GOVERNS_ALGO

    out = [f"  {'serves':<13} {t}" for t in node.serves]
    out += [f"  {'concerns':<13} {c.sym}"
            + ("   (governs — a policy anchor, never drifts)"
               if (c.anchor_algo or "") == GOVERNS_ALGO
               else _anchor_state(graph, c.sym, c.anchor, c.anchor_algo, renamed))
            for c in node.concerns]
    for ev in node.evidence:
        if ev.anchor is None and not ev.ref.startswith(("sym:", "file:")):
            out.append(f"  {'grounded_by':<13} {ev.ref}   (opaque — never drifts)")
        else:
            out.append(f"  {'grounded_by':<13} {ev.ref}"
                       f"{_anchor_state(graph, ev.ref, ev.anchor, ev.anchor_algo, renamed)}")
    out += [f"  {'supersedes':<13} {t}" for t in node.supersedes]
    out += [f"  {'supersedes':<13} {t}   (PENDING — needs `yigraf attest`)" for t in node.pending_supersedes]
    out += [f"  {'equivalent_to':<13} {t}" for t in node.equivalent_to]
    return out


def _links(graph: nx.DiGraph, node_id: str, drifting: dict[tuple[str, str], object]) -> list[str]:
    """The node's typed edges, each annotated when that specific anchor is the one drifting.

    The annotation is the point. A memory can carry the *same* symbol under ``concerns`` and under
    ``evidence``, and each list is re-anchored by a different call — so a report that says only "this
    node is drifting" sends the caller to re-run the form they already ran. Naming the relation is
    what turns the drift line into an action.
    """
    out: list[str] = []
    for relation in ("serves", "concerns", "grounded_by", "supersedes", "equivalent_to",
                     "tracks", "implements", "contains"):
        for target in _edges_out(graph, node_id, relation):
            mark = ""
            item = drifting.get((node_id, target))
            if item is not None:
                mark = f"   ⚠ {item.kind} drift"
            out.append(f"  {relation:<13} {target}{mark}")
    # Dangling targets live on the node, not on an edge — they are precisely the hard-drift cases, so
    # omitting them would hide the half of the picture the caller is most likely acting on.
    for attr, relation in (("dangling_concerns", "concerns"), ("dangling_grounded_by", "grounded_by"),
                           ("dangling_implements", "implements"), ("dangling_serves", "serves"),
                           ("dangling_supersedes", "supersedes")):
        for entry in attrs_list(graph, node_id, attr):
            ref = entry["sym"] if isinstance(entry, dict) else entry
            out.append(f"  {relation:<13} {ref}   ⚠ unresolved")
    for ref in attrs_list(graph, node_id, "opaque_evidence"):
        out.append(f"  {'grounded_by':<13} {ref}   (opaque — never drifts)")
    return out


def attrs_list(graph: nx.DiGraph, node_id: str, attr: str) -> list:
    value = graph.nodes[node_id].get(attr) or []
    return value if isinstance(value, list) else [value]


def _intent_detail(graph: nx.DiGraph, node_id: str, attrs: dict) -> list[str]:
    tag = attrs.get("status", "?")
    if attrs.get("attestation") == "human":
        tag += " · human"
    out = [f"{node_id}  [{tag}]"]
    if attrs.get("source_file"):
        out.append(f"  yigraf/{attrs['source_file']}")
    out.append("")
    out += _wrap("  Statement", attrs.get("statement") or attrs.get("label", ""))
    for scenario in attrs.get("scenarios") or []:
        out += _wrap("  Scenario ", scenario)
    if attrs.get("design"):
        out += _wrap("  Design   ", str(attrs["design"]))
    return out


def _task_detail(graph: nx.DiGraph, node_id: str, attrs: dict) -> list[str]:
    box = "☑ done" if attrs.get("state") == "done" else "☐ todo"
    return [f"{node_id}  [{box}]", "", *_wrap("  Label    ", attrs.get("label", ""))]


def _structure_detail(graph: nx.DiGraph, node_id: str, attrs: dict) -> list[str]:
    out = [f"{node_id}  [{attrs.get('kind', 'symbol')}]"]
    if attrs.get("signature"):
        out += _wrap("  Signature", str(attrs["signature"]))
    rng = attrs.get("source_range")
    if attrs.get("source_file"):
        where = attrs["source_file"] + (f":{rng[0] + 1}" if rng else "")
        out.append(f"  Source:    {where}")
    return out


def _hollow_why(graph: nx.DiGraph, node_id: str, attrs: dict, root: Path,
                config: dict | None) -> list[str]:
    """Say so when this node's ``Why`` is a pointer at an argument that was never written.

    ``show`` is where anyone holding an id reads the reasoning, so it is where a hollow pointer is
    found — the field found four of them by hand, years after they were filed. Capture refuses new
    ones (``cli._hollow_why_guard``); this is the surface for the ones already in the store, and it
    names ``amend`` because that is the verb that repairs a record without filing a mind-change.
    Silent whenever the argument is really there.
    """
    from yigraf.memory import deferral_verdict

    supersedes = [t for _, t, r in graph.out_edges(node_id, data="relation") if r == "supersedes"]
    found = deferral_verdict(root, attrs.get("why") or "", supersedes,
                             max_words=(config or {}).get("hollow_why_words", 25))
    if found is None:
        return []
    _target, verdict, chain = found
    end = chain[-1]
    lands = {"missing": f"no node {end} exists",
             "archived": f"{end} is archived — out of the active graph",
             "hollow": f"{end} carries no Why of its own",
             "loop": f"{end} defers back here"}[verdict]
    return ["", "⚠ Hollow Why:",
            f"  it defers to {' → '.join(chain)}, and {lands} — so this node's stated reasoning "
            f"resolves to nothing.",
            f"  Write it down where it is read: `yigraf amend {node_id} --why \"<the argument>\"` "
            f"(no supersedes trail)."]


def node_detail(graph: nx.DiGraph, node_id: str, root: Path | None = None,
                config: dict | None = None) -> str:
    """The full, unbudgeted rendering of one node: content, links, live drift, and open conflicts."""
    attrs = graph.nodes[node_id]
    family = attrs.get("family")
    if family == "memory":
        out = _memory_detail(graph, node_id, attrs)
    elif family == "intent":
        out = _intent_detail(graph, node_id, attrs)
    elif family == "plan" and attrs.get("kind") == "task":
        out = _task_detail(graph, node_id, attrs)
    elif family == "structure":
        out = _structure_detail(graph, node_id, attrs)
    else:
        out = [f"{node_id}  [{family or 'node'}]", "", *_wrap("  Label    ", attrs.get("label", ""))]

    if family == "memory" and root is not None:
        out += _hollow_why(graph, node_id, attrs, root, config)

    items = _drift_on(graph, node_id)
    renames = _renames_on(graph, node_id)
    by_old = {i.locator: i for i in renames}
    links = None
    if family == "memory":
        # the artifact, which holds both anchor lists — and still names any renamed locus by its old id
        links = _memory_links(graph, node_id, root, by_old)
    if links is None:
        links = _links(graph, node_id, {(i.task_id, i.locator): i for i in items})
    if links:
        out += ["", "Links:", *links]

    # Who points AT this node — the half no frontmatter records. For an intent this is the tasks and
    # decisions that serve it; for a symbol it is everything that governs it, which is the question an
    # agent about to edit that symbol is actually asking.
    inbound = [f"  {rel:<13} {src}" for rel in ("concerns", "grounded_by", "implements", "tracks",
                                                "serves", "supersedes", "contains")
               for src in _edges_in(graph, node_id, rel)]
    if inbound:
        out += ["", "Referenced by:", *inbound]

    if items:
        out += ["", f"⚠ Drift ({len(items)}):"]
        out += [f"  {i.locator}: {drift_tail(i)}" for i in items]

    if renames:
        # Uncapped, unlike the packet's `_rename_block`: `show` is the unbudgeted read, and a node
        # carrying five renamed anchors needs all five verbs, not four and a pointer at `gc`.
        out += ["", f"⚠ Unsettled rename ({len(renames)}) — the graph re-anchored it; the file did not:"]
        out += [f"  {i.locator} ⇒ {i.new_locator} — `{rename_verb(i)}`" for i in renames]
        out += [f"  {RENAME_CLIFF}"]

    conflict_lines = _conflicts_on(graph, node_id, root, config)
    if conflict_lines:
        out += ["", f"⚠ Conflict ({len(conflict_lines) // 2}):", *conflict_lines]
    return "\n".join(out).rstrip() + "\n"
