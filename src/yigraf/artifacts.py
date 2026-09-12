"""Intent & plan artifacts: the authored ``.md`` truth for the intent/plan node families (M2).

Intents and plans live as one-file-per-node markdown under ``yigraf/intents/`` and
``yigraf/plans/`` (``docs/graph-design.md`` §4, ``docs/m2-notes.md``). Bodies are human-authored;
the plan's ``edges`` frontmatter is machine-written by ``yigraf link``. This module reads them into
dataclasses, projects those into the graph (intent/plan/task nodes + ``contains``/``tracks``/
``requires``/``implements`` edges), and writes new artifacts for the authoring verbs.

A target id that doesn't resolve to a node is **not** added as a phantom edge — it's stashed on the
task node (``dangling_implements`` / ``dangling_tracks``) for M3 to surface as hard drift.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx
import yaml

from yigraf import relations
from yigraf.astnorm import (ANCHOR_ALGO, SECTION_ANCHOR_ALGO, locus_hash, parse_file_target,
                            parse_section_target, section_locator_for_anchor)

INTENT_FAMILY = "intent"
PLAN_FAMILY = "plan"
CONF = "EXTRACTED"  # authored artifacts are asserted truth, not inferred

INTENT_TYPES = ("requirement", "goal", "capability")
INTENT_STATUSES = ("proposed", "active", "satisfied", "archived")

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
_TASK_LINE = re.compile(r"^- \[([ xX])\]\s*\{#(\d+)\}\s*(.*)$")
_HEADING = re.compile(r"^##\s+(.*?)\s*$")


# --------------------------------------------------------------------------------------------------
# Frontmatter + section parsing
# --------------------------------------------------------------------------------------------------


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Return ``(metadata, body)`` for a ``---``-fenced markdown file (empty meta if none)."""
    match = _FRONTMATTER.match(text)
    if match is None:
        return {}, text
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValueError("artifact frontmatter must be a YAML mapping")
    return meta, match.group(2)


def _compose(meta: dict, body: str) -> str:
    """Inverse of :func:`_split_frontmatter`: deterministic frontmatter + body."""
    front = yaml.safe_dump(meta, sort_keys=True, allow_unicode=True, default_flow_style=False)
    body = body if body.endswith("\n") or not body else body + "\n"
    return f"---\n{front}---\n{body}"


def _sections(body: str) -> dict[str, str]:
    """Split a markdown body into ``{heading_lower: text}`` keyed by ``## Heading``.

    The heading key is lowercased and trimmed of a trailing parenthetical (``Design (how)`` →
    ``design``), so authored variants still map to a stable field.
    """
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        heading = _HEADING.match(line)
        if heading is not None:
            key = heading.group(1).split("(")[0].strip().casefold()
            current = key
            out.setdefault(current, [])
        elif current is not None:
            out[current].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def _bullets(text: str) -> list[str]:
    """The ``- `` bullet items in a section, in order (used for scenarios)."""
    return [ln[2:].strip() for ln in text.splitlines() if ln.lstrip().startswith("- ")]


# --------------------------------------------------------------------------------------------------
# Intent
# --------------------------------------------------------------------------------------------------


@dataclass
class Intent:
    id: str
    slug: str
    type: str
    status: str
    statement: str
    scenarios: list[str] = field(default_factory=list)
    design: str | None = None
    supersedes: list[str] = field(default_factory=list)  # int:<slug> ids this reversal replaces
    attestation: str = "agent"  # agent | human — a human-elicited spec is a trust floor (int:intent-elicitation)


def read_intent(path: Path) -> Intent:
    """Parse an ``intents/<slug>.md`` file into an :class:`Intent`."""
    path = Path(path)
    meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    slug = path.stem
    sections = _sections(body)
    design = sections.get("design") or None
    return Intent(
        id=meta.get("id", f"int:{slug.casefold()}"),
        slug=slug,
        type=meta.get("type", "requirement"),
        status=meta.get("status", "proposed"),
        statement=sections.get("requirement", "").strip(),
        scenarios=_bullets(sections.get("scenarios", "")),
        design=design,
        supersedes=list(meta.get("supersedes") or []),
        attestation=meta.get("attestation", "agent"),
    )


def render_intent(slug: str, statement: str, scenarios: list[str], design: str | None,
                  type: str = "requirement", status: str = "proposed",
                  supersedes: list[str] | None = None) -> str:
    """Render the markdown for a new intent artifact."""
    meta: dict[str, Any] = {"id": f"int:{slug.casefold()}", "family": INTENT_FAMILY,
                            "type": type, "status": status}
    if supersedes:
        meta["supersedes"] = list(supersedes)
    lines = ["## Requirement", statement, "", "## Scenarios"]
    lines += [f"- {s}" for s in scenarios] or ["- "]
    if design:
        lines += ["", "## Design (how)", design]
    return _compose(meta, "\n".join(lines) + "\n")


def update_intent_frontmatter(path: Path, *, status: str | None = None,
                              superseded_by: str | None = None,
                              attestation: str | None = None) -> None:
    """Flip an existing intent's ``status``/``attestation`` (and optionally stamp ``superseded_by``) in place.

    The legitimate metadata edits to an authored intent: retiring/reversing it, and recording a human
    endorsement (``attestation``). The body (the SHALL contract, scenarios, design) is never touched —
    a *changed* contract is a new intent that ``supersedes`` this one, not an edit (that's what
    ``supersede-intent`` writes). ``superseded_by`` is human-legibility only; the traversable edge lives
    on the *successor's* ``supersedes`` field.
    """
    path = Path(path)
    meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    if status is not None:
        meta["status"] = status
    if superseded_by is not None:
        meta["superseded_by"] = superseded_by
    if attestation is not None:
        meta["attestation"] = attestation
    path.write_text(_compose(meta, body), encoding="utf-8")


# --------------------------------------------------------------------------------------------------
# Plan + tasks
# --------------------------------------------------------------------------------------------------


@dataclass
class Implements:
    sym: str
    anchor: str | None = None
    anchor_algo: str | None = None
    #: The commit ``HEAD`` pointed at when ``yigraf link`` last stamped this anchor — the answer to
    #: "when did this completion go stale", which nothing else in the repo can give (feedback-v4 #14).
    #: The field reported reasoning from ``git log`` to a wrong conclusion, because the anchor is
    #: re-stamped on every ``link`` and git history is therefore a *different timeline* from anchor
    #: history: an earlier commit touching the file says nothing about when the anchor was last taken.
    #: A sha rather than a wall-clock time so the value is derived from the repo rather than the
    #: machine, and so two agents linking the same symbol at the same commit still mint the same task
    #: revision (:func:`yigraf.filelog._plan_assertions` hashes this body) instead of a phantom
    #: divergence. ``None`` on every anchor stamped before this existed, and on a repo with no commits.
    stamped_at: str | None = None


@dataclass
class Task:
    id: str
    num: int
    description: str
    state: str  # todo | done
    tracks: str | None = None
    requires: list[str] = field(default_factory=list)
    implements: list[Implements] = field(default_factory=list)
    #: Closed with ``--force``: this completion deliberately names no implementing symbol, because the
    #: work shipped none to name (prose in a module-level constant, a config key, a refusal). Recorded
    #: because ``--force`` used to write *nothing*: the checkbox moved and the capture-gap warning —
    #: whose own guidance offers ``--force`` as the exit — went on firing at every SessionStart with no
    #: verb that could clear it. While the task names no symbol it still can never go STALE; the marker
    #: asserts that is intended, so the signal stops being noise instead of the completion pretending to
    #: evidence it does not have. It is a claim about the task NOW, not a historical fact about how it
    #: was closed, so ``link`` retires it the moment the work grows a symbol (feedback-v9 H#2).
    unanchored: bool = False


@dataclass
class Plan:
    id: str
    slug: str
    title: str
    tasks: list[Task] = field(default_factory=list)
    phase: str = "active"  # active | completed (from the plans/<phase>/ subdir)


def read_plan(path: Path) -> Plan:
    """Parse a plan file (frontmatter ``edges`` + ``## Tasks`` checkboxes) into a :class:`Plan`."""
    path = Path(path)
    meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    slug = path.stem
    edges = meta.get("edges") or {}
    unanchored = set(meta.get("unanchored") or ())

    title = slug
    for line in body.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    tasks: list[Task] = []
    for line in body.splitlines():
        m = _TASK_LINE.match(line.strip())
        if m is None:
            continue
        num = int(m.group(2))
        task_id = f"task:{slug.casefold()}/{num}"
        spec = edges.get(task_id) or {}
        tasks.append(
            Task(
                id=task_id,
                num=num,
                description=m.group(3).strip(),
                state="done" if m.group(1).lower() == "x" else "todo",
                tracks=spec.get("tracks"),
                requires=list(spec.get("requires") or []),
                implements=[_read_impl(e) for e in (spec.get("implements") or [])],
                unanchored=task_id in unanchored,
            )
        )
    tasks.sort(key=lambda t: t.num)
    return Plan(id=meta.get("id", f"plan:{slug.casefold()}"), slug=slug, title=title, tasks=tasks)


def _read_impl(entry: Any) -> Implements:
    if isinstance(entry, str):
        return Implements(sym=entry)
    return Implements(sym=entry["sym"], anchor=entry.get("anchor"),
                      anchor_algo=entry.get("anchor_algo"), stamped_at=entry.get("stamped_at"))


def set_task_state(path: Path, num: int, done: bool) -> bool:
    """Flip one task's checkbox in the committed plan file; ``False`` if it was already in that state.

    R6 says the FILE is truth for the authored families — it does not say a verb may not write the
    file, and yigraf already ships exactly such a verb for the sibling authored family
    (``intent <slug> --status``). Tasks were the only authored family whose mutable state had no verb
    that writes it, so an agent that had correctly internalised "never hand-edit an artifact" was
    structurally unable to close a task: the field measured an open count that was 67% false, on the
    line ``yigraf status`` makes the pre-done authority (feedback-v4 #1).

    Only the checkbox moves. The description, the edges, and every other line are re-emitted verbatim —
    a state change is not a rewrite, the same rule ``memory.render_memory`` follows for a body.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    out, changed = [], False
    for line in text.splitlines(keepends=True):
        m = _TASK_LINE.match(line.strip())
        if m is not None and int(m.group(2)) == num:
            was_done = m.group(1).lower() == "x"
            if was_done != done:
                out.append(line.replace(f"- [{m.group(1)}]", "- [x]" if done else "- [ ]", 1))
                changed = True
                continue
        out.append(line)
    if changed:
        path.write_text("".join(out), encoding="utf-8")
    return changed


def mark_task_unanchored(path: Path, task_id: str, unanchored: bool = True) -> bool:
    """Record (or clear) "this completion deliberately implements nothing"; ``False`` if unchanged.

    A top-level ``unanchored:`` list, not a key inside the task's ``edges`` spec, for two reasons. The
    naming one: ``edges`` holds edges, and this marker asserts the *absence* of one. The load-bearing
    one: :func:`remove_edge_from_plan` deletes a task's spec once its last edge is gone, so a marker
    parked in there would be collected by unlinking something unrelated — and its silent loss would
    look exactly like the nag returning on its own.
    """
    path = Path(path)
    meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    current = set(meta.get("unanchored") or ())
    after = (current | {task_id}) if unanchored else (current - {task_id})
    if after == current:
        return False
    if after:
        meta["unanchored"] = sorted(after)
    else:
        meta.pop("unanchored", None)
    path.write_text(_compose(meta, body), encoding="utf-8")
    return True


def append_tasks(path: Path, descriptions: list[str]) -> list[int]:
    """Append todo tasks to a live plan's ``## Tasks`` list; returns the numbers assigned.

    Numbers continue past the highest existing one and are never reused, so an id already recorded on
    a ``link`` edge or a memory can't come to mean a different task (feedback-v4 #1).
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    nums = [int(m.group(2)) for m in (_TASK_LINE.match(ln.strip()) for ln in lines) if m]
    last = max((i for i, ln in enumerate(lines) if _TASK_LINE.match(ln.strip())), default=None)
    if last is None:  # no task list yet — start one at the end
        lines += ["", "## Tasks"] if "## Tasks" not in text else []
        last = len(lines) - 1
    start = max(nums, default=0) + 1
    assigned = list(range(start, start + len(descriptions)))
    new_lines = [f"- [ ] {{#{n}}} {d}" for n, d in zip(assigned, descriptions)]
    lines[last + 1:last + 1] = new_lines
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return assigned


def render_plan(slug: str, title: str, tasks: list[str]) -> str:
    """Render the markdown for a new plan with todo tasks (no edges yet)."""
    meta = {"id": f"plan:{slug.casefold()}", "family": PLAN_FAMILY, "edges": {}}
    lines = [f"# {title}", "", "## Tasks"]
    lines += [f"- [ ] {{#{i}}} {desc}" for i, desc in enumerate(tasks, start=1)]
    return _compose(meta, "\n".join(lines) + "\n")


def add_edge_to_plan(path: Path, task_id: str, relation: str, target: str,
                     anchor: str | None = None, anchor_algo: str | None = None,
                     stamped_at: str | None = None, replaces: str | None = None) -> None:
    """Write a ``tracks`` or ``implements`` edge for ``task_id`` into the plan's frontmatter.

    ``tracks`` is a single intent id; ``implements`` appends a (deduplicated) ``sym:``/``file:`` entry
    carrying its stamped ``anchor`` + ``anchor_algo`` (astnorm for a symbol, file-sha256 for a file —
    friend-review #12). Re-linking the same target re-stamps its anchor.

    ``replaces`` moves an existing entry's locator instead of appending a second one — passed only when
    the caller can *prove* the subject moved rather than guessing. :func:`remove_edge_from_plan` argues
    (correctly) that ``link`` must never auto-replace, because a task may legitimately implement several
    symbols and yigraf cannot tell "this one moved" from "this is a second implementer". That argument
    is about a *blind* link. It does not hold once :func:`yigraf.drift.resolve_renames` has matched the
    old locator's anchor to exactly one symbol in its own scope — that is a proof, not a guess, and it
    is the only thing this parameter accepts as one. Without it the settle path would leave the dead
    locator behind as future hard drift, making its own guidance wrong.
    """
    # The edge grammar is enforced at this write boundary (relations.well_typed_ids): a mistyped plan
    # edge (e.g. implements→int:, tracks→sym:) is an internal routing bug, so it raises here — never
    # reaching disk — rather than landing an ill-typed edge the read-time audit would later flag.
    if not relations.well_typed_ids(relation, task_id, target):
        raise ValueError(f"ill-typed plan edge: {task_id} —{relation}→ {target} "
                         f"violates the edge grammar (relations.SIGNATURES[{relation!r}])")
    path = Path(path)
    meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    edges = meta.setdefault("edges", {}) or {}
    meta["edges"] = edges
    spec = edges.setdefault(task_id, {})

    if relation == "tracks":
        spec["tracks"] = target
    elif relation == "implements":
        impls = spec.setdefault("implements", [])
        entry = {"sym": target, "anchor": anchor,
                 "anchor_algo": (anchor_algo or ANCHOR_ALGO) if anchor else None}
        if anchor and stamped_at:  # only meaningful alongside an anchor it dates (see Implements)
            entry["stamped_at"] = stamped_at
        if replaces and replaces != target:
            # Drop a pre-existing entry at the destination first, so a rename onto a locator the task
            # already declares collapses to one edge rather than leaving a duplicate behind.
            impls[:] = [e for e in impls if e.get("sym") != target]
        keys = (replaces, target) if replaces else (target,)
        for existing in impls:
            if existing.get("sym") in keys:
                existing.clear()
                existing.update(entry)
                break
        else:
            impls.append(entry)
    else:
        raise ValueError(f"unsupported relation for a plan edge: {relation}")

    path.write_text(_compose(meta, body), encoding="utf-8")


def remove_edge_from_plan(path: Path, task_id: str, target: str) -> str | None:
    """Retire one declared edge from ``task_id``; returns the relation removed, or ``None`` if absent.

    The counterpart :func:`add_edge_to_plan` lacked. ``link`` keys ``implements`` entries by their
    exact ``sym`` string, so a symbol that MOVES is a different string: re-linking appends rather than
    replaces, and the old entry keeps pointing at a locator that no longer resolves. ``resolve_renames``
    rescues that automatically while the body is untouched (a moved symbol keeps its content hash), but
    a move *plus* an edit is honest hard drift — and until now no verb could retire it, so a file move
    left permanent, unclearable drift that had to be fixed by hand-editing this frontmatter.

    Deliberately NOT folded into ``link`` as an auto-replace *on a guess*: a task may legitimately
    implement several symbols, so replacing whenever a link lands would silently delete a real edge.
    Retirement is an explicit act. The one case that is not a guess is a rename
    :func:`yigraf.drift.resolve_renames` already proved, which ``link`` settles through
    ``add_edge_to_plan(replaces=...)`` — see :func:`yigraf.cli._renamed_predecessor` for why that proof
    is admissible where a bare locator match is not.
    """
    path = Path(path)
    meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    spec = (meta.get("edges") or {}).get(task_id) or {}
    removed: str | None = None

    if spec.get("tracks") == target:
        del spec["tracks"]
        removed = "tracks"
    else:
        impls = spec.get("implements") or []
        kept = [e for e in impls if e.get("sym") != target]
        if len(kept) != len(impls):
            removed = "implements"
            if kept:
                spec["implements"] = kept
            else:
                spec.pop("implements", None)

    if removed is None:
        return None
    if not spec:  # a task with no edges left carries no empty husk in the frontmatter
        del meta["edges"][task_id]
    path.write_text(_compose(meta, body), encoding="utf-8")
    return removed


# --------------------------------------------------------------------------------------------------
# Projection into the graph
# --------------------------------------------------------------------------------------------------


def iter_intents(root: Path) -> list[Intent]:
    intents_dir = Path(root) / "yigraf" / "intents"
    return [read_intent(p) for p in sorted(intents_dir.glob("*.md"))] if intents_dir.is_dir() else []


def iter_plans(root: Path) -> list[Plan]:
    plans_dir = Path(root) / "yigraf" / "plans"
    out = []
    for sub in ("active", "completed"):
        d = plans_dir / sub
        if d.is_dir():
            for p in sorted(d.glob("*.md")):
                plan = read_plan(p)
                plan.phase = sub
                out.append(plan)
    return out


def project_into(graph: nx.DiGraph, root: Path) -> None:
    """Add intent/plan/task nodes and their cross-family edges to ``graph`` from the artifacts."""
    intents = iter_intents(root)
    for intent in intents:
        graph.add_node(
            intent.id, family=INTENT_FAMILY, kind=intent.type, label=intent.statement or intent.slug,
            confidence=CONF, status=intent.status, statement=intent.statement,
            scenarios=intent.scenarios, design=intent.design, attestation=intent.attestation,
            source_file=f"intents/{intent.slug}.md",
        )
    # Second pass: an intent reversal (int → int supersedes) resolves only once every intent node
    # exists (a successor may sort before the intent it replaces). This is the traversable edge that
    # `superseded_by:` frontmatter alone never produced (friend-review #1).
    for intent in intents:
        for old in intent.supersedes:
            if old in graph:
                graph.add_edge(intent.id, old, relation="supersedes", confidence=CONF)
            else:
                _stash(graph, intent.id, "dangling_supersedes", old)

    plans = iter_plans(root)
    _project_file_anchor_nodes(graph, root, plans)
    for plan in plans:
        graph.add_node(plan.id, family=PLAN_FAMILY, kind="plan", label=plan.title,
                       confidence=CONF, phase=plan.phase)
        for task in plan.tasks:
            # Set only when true, so the 156 anchored tasks keep the exact attrs (and therefore the
            # exact stored projection and task revision) they had before the marker existed.
            marker = {"unanchored": True} if task.unanchored else {}
            graph.add_node(
                task.id, family=PLAN_FAMILY, kind="task", label=task.description,
                confidence=CONF, state=task.state, order=task.num, **marker,
            )
            graph.add_edge(plan.id, task.id, relation="contains", confidence=CONF)
            _project_task_edges(graph, task)


def mint_locus_node(graph: nx.DiGraph, root: Path, locus: str, anchor: str | None) -> None:
    """Add the structure node a ``file:`` edge attaches to, carrying that locus's *current* hash (#12).

    Shared by the plan and memory projectors, so the two cannot drift apart. The extractor never
    produces these nodes — an infra/glue file has no symbol, and docs are deliberately not indexed
    (mem:a65f1ccad03b765e) — so without this the edge would dangle. A locus that does not resolve is
    left absent: the edge dangles and reports hard drift, matching a gone symbol.

    The one exception is a **renamed heading**. A section anchor excludes the heading's own text, so a
    rename leaves the hash intact; when exactly one section in that file still hashes to the *stored*
    ``anchor``, the node is minted under the heading's NEW locator instead.
    :func:`yigraf.drift.resolve_renames` then re-anchors the edge onto it by that same hash, so the
    move reports as ``renamed`` rather than hard drift (int:drift-detection: SHALL NOT flag a pure
    rename). Symbols need no equivalent — the extractor already indexes the renamed one.
    """
    if locus in graph:
        return
    current, algo = locus_hash(root, locus)
    if current is None:
        relpath, slug = parse_section_target(locus)
        if slug is None or anchor is None:
            return  # a missing file or line range does not "rename" by content match
        moved = section_locator_for_anchor(root, relpath, anchor)
        if moved is None or moved in graph:
            return
        locus, current, algo = moved, anchor, SECTION_ANCHOR_ALGO
    graph.add_node(locus, family="structure", kind="file-anchor",
                   label=locus[len("file:"):], confidence=CONF, content_hash=current,
                   hash_algo=algo, source_file=parse_file_target(locus)[0])


def _project_file_anchor_nodes(graph: nx.DiGraph, root: Path, plans: list[Plan]) -> None:
    """Inject a node for each ``file:`` target a task ``implements`` (#12) via :func:`mint_locus_node`."""
    for plan in plans:
        for task in plan.tasks:
            for impl in task.implements:
                if impl.sym.startswith("file:"):
                    mint_locus_node(graph, root, impl.sym, impl.anchor)


def _project_task_edges(graph: nx.DiGraph, task: Task) -> None:
    """Add a task's tracks/requires/implements edges, stashing unresolved targets for M3."""
    if task.tracks is not None:
        if task.tracks in graph:
            graph.add_edge(task.id, task.tracks, relation="tracks", confidence=CONF)
        else:
            _stash(graph, task.id, "dangling_tracks", task.tracks)

    for req in task.requires:
        if req in graph:
            graph.add_edge(task.id, req, relation="requires", confidence=CONF)
        else:
            _stash(graph, task.id, "dangling_requires", req)

    for impl in task.implements:
        if impl.sym in graph:
            attrs = {"relation": "implements", "confidence": CONF}
            if impl.anchor is not None:
                attrs["anchor"] = impl.anchor
                attrs["anchor_algo"] = impl.anchor_algo or ANCHOR_ALGO
                if impl.stamped_at:
                    attrs["stamped_at"] = impl.stamped_at  # dates a STALE line (retrieval._stale_line)
            graph.add_edge(task.id, impl.sym, **attrs)
        else:
            # Keep the anchor so M3 can re-anchor a rename by content match (docs/m3-notes.md §3).
            _stash(graph, task.id, "dangling_implements",
                   {"sym": impl.sym, "anchor": impl.anchor, "anchor_algo": impl.anchor_algo,
                    "stamped_at": impl.stamped_at})


def _stash(graph: nx.DiGraph, node_id: str, attr: str, value: str) -> None:
    graph.nodes[node_id].setdefault(attr, []).append(value)


_TASK_LOCATOR = re.compile(r"^task:(.+)/\d+$")


def plan_of(task_locator: str) -> str | None:
    match = _TASK_LOCATOR.match(task_locator)
    return f"plan:{match.group(1)}" if match else None


def retracted_tasks(stating: Sequence[Assertion]) -> Callable[[Assertion], bool]:
    """Is this assertion a task that the plan owning it no longer lists?

    ``stating`` is whatever speaks for the plans' current ``contains`` sets — and naming that rather
    than assuming it is the whole generalization. In a WORKSPACE it is local truth, and the predicate
    is applied to the replica (:func:`yigraf.extract._fold_replica`). In a LOG-ONLY fold — a server,
    which holds no files at all — it is the log's own live assertions, applied to that same set: after
    :func:`yigraf.log._live_revisions` the live plan revision is the newest its author wrote, so its
    ``contains`` set is the current one and the rule reads identically. The original version took the
    workspace's ``local`` sequence as a parameter *name*, which quietly made "a plan this workspace
    holds" the only expressible scope; a server's ``held`` was therefore always empty and a deleted task
    came back forever. Found on the deployed console: ``plan:divergence-ledger``'s five removed tasks
    were still rendering as open there long after the workspace had stopped counting them.

    ``defer_families`` answers "the local file wins" only where a local node EXISTS to win. Deleting a
    task from a plan asserts nothing — absence is invisible to an append-only log — so the replica's
    copy met no local claim, was folded rather than declined, and came back as a live ``state: todo``
    node contained by nothing and reachable from nothing. Found on yigraf's own graph while retiring
    ``plan:divergence-ledger``: five tasks removed from the artifact, zero in-edges, and ``yigraf
    status`` still counting them as open while ``yigraf tasks --open`` (which reads the plan files) said
    there were none. Two surfaces, one question, opposite answers — and the count was unclearable,
    because nothing the principal could edit would ever reach it.

    Files are truth for this family, and a plan artifact's ``contains`` set is that family's statement
    of which tasks the plan HAS — the same reasoning
    :meth:`~yigraf.onlinelog.pending_local_revisions` applies to a locator held with an unpushed edit.
    So the scope is the guard: only a plan **this workspace holds** speaks for its own contents. A
    teammate-only plan is not in ``local`` at all and arrives whole, exactly as
    ``test_a_teammate_only_intent_still_arrives_over_the_log`` requires.

    The loss is never silent where it could be real. If a teammate ADDED the task, their plan revision
    disagrees with mine about the ``contains`` set, so ``plan:<slug>`` itself lands in ``diverged`` —
    reported at the granularity the disagreement actually has. If I removed it, my revision is the
    newest and mine, so no divergence is reported, which is correct: nobody disagrees.

    Filtering here rather than inside :func:`~yigraf.fold.fold_assertions` is deliberate — mem:ea843907
    settled that a family-shaped rule belongs to the CALLER, and the fold stays family-agnostic.
    """
    def _locator(a: Assertion) -> str:
        """The locator this assertion speaks for — mirroring :func:`yigraf.fold._node_id`, because the
        set of nodes this rule reasons about has to be the set the fold will materialize. A revisioned
        assertion carries it in the body; one written before revisioning existed (and a real log holds
        both eras) *is* its locator. Reading ``body["locator"]`` directly was safe only while the input
        was the FileLog, which always writes one — a log-only fold hits the older shape immediately."""
        return (a.body or {}).get("locator") or a.id

    contained: set[str] = set()
    held: set[str] = set()
    for a in stating:
        body = a.body or {}
        attrs = body.get("attrs") or {}
        if body.get("family") != PLAN_FAMILY or attrs.get("kind") != "plan":
            continue
        held.add(_locator(a))
        contained.update(e["target"] for e in body.get("edges") or []
                         if e.get("relation") == "contains")

    def is_retracted(assertion: Assertion) -> bool:
        body = assertion.body or {}
        if body.get("family") != PLAN_FAMILY or (body.get("attrs") or {}).get("kind") != "task":
            return False
        locator = _locator(assertion)
        plan_id = plan_of(locator)
        return plan_id in held and locator not in contained

    return is_retracted
