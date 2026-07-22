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
from yigraf.astnorm import ANCHOR_ALGO, FILE_ANCHOR_ALGO, file_content_hash, parse_file_target

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


@dataclass
class Task:
    id: str
    num: int
    description: str
    state: str  # todo | done
    tracks: str | None = None
    requires: list[str] = field(default_factory=list)
    implements: list[Implements] = field(default_factory=list)


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
            )
        )
    tasks.sort(key=lambda t: t.num)
    return Plan(id=meta.get("id", f"plan:{slug.casefold()}"), slug=slug, title=title, tasks=tasks)


def _read_impl(entry: Any) -> Implements:
    if isinstance(entry, str):
        return Implements(sym=entry)
    return Implements(sym=entry["sym"], anchor=entry.get("anchor"), anchor_algo=entry.get("anchor_algo"))


def render_plan(slug: str, title: str, tasks: list[str]) -> str:
    """Render the markdown for a new plan with todo tasks (no edges yet)."""
    meta = {"id": f"plan:{slug.casefold()}", "family": PLAN_FAMILY, "edges": {}}
    lines = [f"# {title}", "", "## Tasks"]
    lines += [f"- [ ] {{#{i}}} {desc}" for i, desc in enumerate(tasks, start=1)]
    return _compose(meta, "\n".join(lines) + "\n")


def add_edge_to_plan(path: Path, task_id: str, relation: str, target: str,
                     anchor: str | None = None, anchor_algo: str | None = None) -> None:
    """Write a ``tracks`` or ``implements`` edge for ``task_id`` into the plan's frontmatter.

    ``tracks`` is a single intent id; ``implements`` appends a (deduplicated) ``sym:``/``file:`` entry
    carrying its stamped ``anchor`` + ``anchor_algo`` (astnorm for a symbol, file-sha256 for a file —
    friend-review #12). Re-linking the same target re-stamps its anchor.
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
        for existing in impls:
            if existing.get("sym") == target:
                existing.update(entry)
                break
        else:
            impls.append(entry)
    else:
        raise ValueError(f"unsupported relation for a plan edge: {relation}")

    path.write_text(_compose(meta, body), encoding="utf-8")


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
            graph.add_node(
                task.id, family=PLAN_FAMILY, kind="task", label=task.description,
                confidence=CONF, state=task.state, order=task.num,
            )
            graph.add_edge(plan.id, task.id, relation="contains", confidence=CONF)
            _project_task_edges(graph, task)


def _project_file_anchor_nodes(graph: nx.DiGraph, root: Path, plans: list[Plan]) -> None:
    """Inject a node for each ``file:`` target a task ``implements``, carrying its current hash (#12).

    The task counterpart of :func:`yigraf.memory._project_file_anchor_nodes`: an infra/glue file has
    no extracted symbol, so we add its node with the file's current SHA-256 here — then the
    ``implements`` edge resolves and drift compares like a symbol. A missing file stays absent → the
    edge dangles → hard drift.
    """
    for plan in plans:
        for task in plan.tasks:
            for impl in task.implements:
                if not impl.sym.startswith("file:") or impl.sym in graph:
                    continue
                current = file_content_hash(root, impl.sym)
                if current is None:
                    continue
                relpath, _s, _e = parse_file_target(impl.sym)
                graph.add_node(impl.sym, family="structure", kind="file-anchor",
                               label=impl.sym[len("file:"):], confidence=CONF,
                               content_hash=current, hash_algo=FILE_ANCHOR_ALGO, source_file=relpath)


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
            graph.add_edge(task.id, impl.sym, **attrs)
        else:
            # Keep the anchor so M3 can re-anchor a rename by content match (docs/m3-notes.md §3).
            _stash(graph, task.id, "dangling_implements",
                   {"sym": impl.sym, "anchor": impl.anchor, "anchor_algo": impl.anchor_algo})


def _stash(graph: nx.DiGraph, node_id: str, attr: str, value: str) -> None:
    graph.nodes[node_id].setdefault(attr, []).append(value)
