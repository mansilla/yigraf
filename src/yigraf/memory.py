"""The memory node family: the authored ``.md`` truth for captured reasoning (M7).

A memory node is a durable, versioned record of a *reasoning event* — a decision, constraint,
rationale, rejected alternative, learned fact, or preference — captured at a commit boundary and
linked into the graph (``docs/memory-model.md``, ``docs/capture-flow.md``). It is the persisted
``T`` (the *why*) that chat history loses on ``/clear``.

Like intents and plans (``docs/graph-design.md`` §4), memory is one-file-per-node markdown under
``yigraf/memory/<seq>-<slug>.md`` — body authored for humans, frontmatter machine-written by the
``remember`` / ``supersede`` / ``note-constraint`` verbs. This module reads those files into a
dataclass, writes new ones, and projects them into the graph with their cross-family edges:

- ``serves`` → an intent/plan node (this decision works toward that goal),
- ``concerns`` → a structure node, carrying a **drift anchor** (this decision governs that code; edit
  the code and drift surfaces a "re-verify" reconcile — handled by :mod:`yigraf.drift`),
- ``supersedes`` → another memory node (a mind-change; the predecessor sinks in ranking but stays
  available as a rejected alternative if it was ever referenced).

An unresolved target is **not** added as a phantom edge — ``serves``/``supersedes`` stash a
``dangling_*`` marker; ``concerns`` stashes ``dangling_concerns`` so :mod:`yigraf.drift` can
rename-re-anchor or surface it as hard drift, exactly as it does for a task's ``implements``.

v0 capture is deterministic and agent-asserted (memory-model §5 option A): no embedding dedup yet
(that's M8), so write-time collision handling is the trivial "does this exact node already exist".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx
import yaml

from yigraf.astnorm import ANCHOR_ALGO, FILE_ANCHOR_ALGO, file_content_hash, parse_file_target

MEMORY_FAMILY = "memory"
CONF = "EXTRACTED"  # agent-asserted at a commit boundary, not inferred

#: Memory node types (graph-design §1 / memory-model §1). ``constraint`` is the promotable one.
MEMORY_TYPES = (
    "decision",
    "constraint",
    "rationale",
    "rejected-alternative",
    "learned-fact",
    "preference",
)

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
_HEADING = re.compile(r"^##\s+(.*?)\s*$")
_WHY = re.compile(r"^\*\*Why:\*\*\s*(.*)$")
_REJECTED = re.compile(r"^\*\*Rejected:\*\*\s*(.*)$")
_SLUG_STOP = re.compile(r"[^a-z0-9]+")


# --------------------------------------------------------------------------------------------------
# Frontmatter helpers (mirrors artifacts.py; kept local so the modules stay decoupled)
# --------------------------------------------------------------------------------------------------


def _split_frontmatter(text: str) -> tuple[dict, str]:
    match = _FRONTMATTER.match(text)
    if match is None:
        return {}, text
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValueError("memory frontmatter must be a YAML mapping")
    return meta, match.group(2)


def _compose(meta: dict, body: str) -> str:
    front = yaml.safe_dump(meta, sort_keys=True, allow_unicode=True, default_flow_style=False)
    body = body if body.endswith("\n") or not body else body + "\n"
    return f"---\n{front}---\n{body}"


# --------------------------------------------------------------------------------------------------
# Dataclasses
# --------------------------------------------------------------------------------------------------


@dataclass
class Concern:
    """A ``concerns`` edge target: the governed symbol + the drift anchor stamped at capture time."""

    sym: str
    anchor: str | None = None
    anchor_algo: str | None = None


@dataclass
class Memory:
    id: str
    seq: int
    slug: str
    type: str
    statement: str
    why: str = ""
    alternatives: str | None = None
    serves: list[str] = field(default_factory=list)
    concerns: list[Concern] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    status: str = "active"
    maturity: str = "working"  # working → settled by survival (M9); always working in M7
    promotable: bool = False  # a constraint flagged as a candidate enforced check (capture-flow §0a)
    provenance: dict = field(default_factory=dict)


# --------------------------------------------------------------------------------------------------
# Read / render
# --------------------------------------------------------------------------------------------------


def _read_concern(entry: Any) -> Concern:
    if isinstance(entry, str):
        return Concern(sym=entry)
    return Concern(sym=entry["sym"], anchor=entry.get("anchor"), anchor_algo=entry.get("anchor_algo"))


def _parse_body(body: str) -> tuple[str, str, str | None]:
    """Return ``(statement, why, alternatives)`` from a memory body.

    The first ``## `` heading is the one-line statement; ``**Why:**`` and ``**Rejected:**`` lines (the
    reasoning ``T`` and the rejected alternative — the most perishable content) follow.
    """
    statement = why = ""
    alternatives: str | None = None
    for line in body.splitlines():
        heading = _HEADING.match(line)
        if heading is not None and not statement:
            statement = heading.group(1).strip()
            continue
        m = _WHY.match(line.strip())
        if m is not None:
            why = m.group(1).strip()
            continue
        m = _REJECTED.match(line.strip())
        if m is not None:
            alternatives = m.group(1).strip()
    return statement, why, alternatives


def read_memory(path: Path) -> Memory:
    """Parse a ``memory/<seq>-<slug>.md`` file into a :class:`Memory`."""
    path = Path(path)
    meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    statement, why, alternatives = _parse_body(body)
    stem = path.stem
    seq = _seq_from_stem(stem)
    slug = stem.split("-", 1)[1] if "-" in stem and stem.split("-", 1)[0].isdigit() else stem
    return Memory(
        id=meta.get("id", f"mem:{seq:03d}"),
        seq=seq,
        slug=slug,
        type=meta.get("type", "decision"),
        statement=statement,
        why=why,
        alternatives=alternatives,
        serves=list(meta.get("serves") or []),
        concerns=[_read_concern(e) for e in (meta.get("concerns") or [])],
        supersedes=list(meta.get("supersedes") or []),
        status=meta.get("status", "active"),
        maturity=meta.get("maturity", "working"),
        promotable=bool(meta.get("promotable", False)),
        provenance=dict(meta.get("provenance") or {}),
    )


def render_memory(memory: Memory) -> str:
    """Render the markdown for a memory artifact (frontmatter machine-written, body authored)."""
    meta: dict[str, Any] = {
        "id": memory.id,
        "family": MEMORY_FAMILY,
        "type": memory.type,
        "status": memory.status,
        "maturity": memory.maturity,
        "serves": list(memory.serves),
        "concerns": [
            {"sym": c.sym, "anchor": c.anchor, "anchor_algo": c.anchor_algo} for c in memory.concerns
        ],
        "supersedes": list(memory.supersedes),
    }
    if memory.promotable:
        meta["promotable"] = True
    if memory.provenance:
        meta["provenance"] = dict(memory.provenance)

    lines = [f"## {memory.statement}"]
    if memory.why:
        lines += ["", f"**Why:** {memory.why}"]
    if memory.alternatives:
        lines += ["", f"**Rejected:** {memory.alternatives}"]
    return _compose(meta, "\n".join(lines) + "\n")


# --------------------------------------------------------------------------------------------------
# Sequence allocation + slugs
# --------------------------------------------------------------------------------------------------


def _seq_from_stem(stem: str) -> int:
    head = stem.split("-", 1)[0]
    return int(head) if head.isdigit() else 0


def memory_dir(root: Path) -> Path:
    return Path(root) / "yigraf" / "memory"


def next_seq(root: Path) -> int:
    """The next memory sequence number (1-based), one past the highest already on disk."""
    d = memory_dir(root)
    if not d.is_dir():
        return 1
    highest = 0
    for path in d.glob("*.md"):
        highest = max(highest, _seq_from_stem(path.stem))
    return highest + 1


def slugify(text: str, max_words: int = 6) -> str:
    """A short, stable filename slug from a statement (lowercase, hyphenated, first few words)."""
    words = [w for w in _SLUG_STOP.split(text.lower()) if w]
    slug = "-".join(words[:max_words])
    return slug[:48].strip("-") or "memory"


def memory_path(root: Path, seq: int, slug: str) -> Path:
    return memory_dir(root) / f"{seq:03d}-{slug}.md"


# --------------------------------------------------------------------------------------------------
# Projection into the graph
# --------------------------------------------------------------------------------------------------


def iter_memories(root: Path) -> list[Memory]:
    d = memory_dir(root)
    return [read_memory(p) for p in sorted(d.glob("*.md"))] if d.is_dir() else []


def find_memory(root: Path, mem_id: str) -> Path | None:
    """The artifact path for a memory id (``mem:NNN``), or ``None`` if no such node exists."""
    for path in sorted(memory_dir(root).glob("*.md")) if memory_dir(root).is_dir() else []:
        meta, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
        if meta.get("id") == mem_id:
            return path
    return None


def project_into(graph: nx.DiGraph, root: Path) -> None:
    """Add memory nodes + their ``serves``/``concerns``/``supersedes`` edges to ``graph``.

    Run *after* structure + intent/plan projection so ``serves``/``concerns`` targets resolve, and
    *before* :func:`yigraf.drift.resolve_renames` so a renamed ``concerns`` target re-anchors. An
    unresolved target stashes a ``dangling_*`` marker rather than conjuring a phantom node.
    """
    memories = iter_memories(root)
    _project_file_anchor_nodes(graph, root, memories)
    for memory in memories:
        graph.add_node(
            memory.id,
            family=MEMORY_FAMILY,
            kind=memory.type,
            label=memory.statement or memory.slug,
            confidence=CONF,
            status=memory.status,
            maturity=memory.maturity,
            statement=memory.statement,
            why=memory.why,
            alternatives=memory.alternatives,
            promotable=memory.promotable,
            source_file=f"memory/{memory.seq:03d}-{memory.slug}.md",
        )
        _project_memory_edges(graph, memory)


def _project_file_anchor_nodes(graph: nx.DiGraph, root: Path, memories: list[Memory]) -> None:
    """Inject a node for each ``file:`` target a memory ``concerns``, carrying its *current* hash (#12).

    Infra/glue files (Dockerfile, buildspec, ``*.sh``) have no code symbol to anchor to, so a decision
    about them targets ``file:<path>[:L<a>-L<b>]``. The extractor never produced such a node, so we add
    one here with the file's current SHA-256 — then the ``concerns`` edge resolves and :mod:`yigraf.drift`
    soft-compares the stored anchor against it, exactly as for a symbol. A missing file is left absent →
    the edge stays dangling → hard drift, matching a gone symbol.
    """
    for memory in memories:
        for concern in memory.concerns:
            if not concern.sym.startswith("file:") or concern.sym in graph:
                continue
            current = file_content_hash(root, concern.sym)
            if current is None:
                continue  # missing file → dangling concern → hard drift (handled downstream)
            relpath, _start, _end = parse_file_target(concern.sym)
            graph.add_node(concern.sym, family="structure", kind="file-anchor",
                           label=concern.sym[len("file:"):], confidence=CONF,
                           content_hash=current, hash_algo=FILE_ANCHOR_ALGO, source_file=relpath)


def _project_memory_edges(graph: nx.DiGraph, memory: Memory) -> None:
    for target in memory.serves:
        if target in graph:
            graph.add_edge(memory.id, target, relation="serves", confidence=CONF)
        else:
            _stash(graph, memory.id, "dangling_serves", target)

    for concern in memory.concerns:
        if concern.sym in graph:
            attrs = {"relation": "concerns", "confidence": CONF}
            if concern.anchor is not None:
                attrs["anchor"] = concern.anchor
                attrs["anchor_algo"] = concern.anchor_algo or ANCHOR_ALGO
            graph.add_edge(memory.id, concern.sym, **attrs)
        else:
            # Keep the anchor so drift.resolve_renames can re-anchor a rename by content match.
            _stash(graph, memory.id, "dangling_concerns",
                   {"sym": concern.sym, "anchor": concern.anchor, "anchor_algo": concern.anchor_algo})

    for old in memory.supersedes:
        if old in graph:
            graph.add_edge(memory.id, old, relation="supersedes", confidence=CONF)
        else:
            _stash(graph, memory.id, "dangling_supersedes", old)


def _stash(graph: nx.DiGraph, node_id: str, attr: str, value: Any) -> None:
    graph.nodes[node_id].setdefault(attr, []).append(value)


def recompute_counters(graph: nx.DiGraph) -> None:
    """Materialize the edge-derived supersession counters on memory nodes (graph-design §3).

    ``superseded_in`` / ``supersedes_out`` are recomputed on each build (self-healing) so retrieval's
    relevance prior can down-weight a superseded decision in O(1) without a traversal. A node with
    ``superseded_in > 0`` is stale: it sinks in ranking but stays available as a rejected alternative.
    Only memory nodes carry ``supersedes`` edges, so we stamp only them — non-memory nodes keep the
    implicit ``0`` (retrieval reads the counter with a default), keeping ``graph.json`` uncluttered.
    """
    for node_id, attrs in graph.nodes(data=True):
        if attrs.get("family") != MEMORY_FAMILY:
            continue
        attrs["superseded_in"] = sum(
            1 for _, _, a in graph.in_edges(node_id, data=True) if a.get("relation") == "supersedes"
        )
        attrs["supersedes_out"] = sum(
            1 for _, _, a in graph.out_edges(node_id, data=True) if a.get("relation") == "supersedes"
        )
