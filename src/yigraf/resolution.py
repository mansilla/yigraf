"""Resolution artifacts: a principal's verdict on a knowledge-conflict, as a first-class append.

int:concurrent-write-model / mem:062 settled that resolving a conflict is *itself a later append* —
never an edit of either belief. This module gives that append a home, so a verdict can be authored by
whoever resolves rather than only by whoever wrote.

**Why a family of its own** rather than the ``equivalent_to`` frontmatter :mod:`yigraf.memory` already
renders: that field can only be written by whoever owns the memory's markdown file. Across a team the
resolving principal frequently owns *neither* belief — both arrived over the sync log and have no local
artifact to edit — and a conflict only its authors may close deadlocks the moment one of them leaves.
A resolution names both operands by id and projects the resolving edge *between* them (the fold's
``projections``, see :func:`yigraf.fold._apply_projection`), so it needs write access to neither.

**Three verdicts**, mirroring what :mod:`yigraf.contradiction` asks a principal to decide:

- ``reconcile`` → ``equivalent_to``: both true, at different altitudes. Both stay live and fully
  weighted; only the finding goes away.
- ``supersede``  → ``supersedes``: ``left`` is a mind-change that retracts ``right`` (the fold's
  supersede discipline drops the target's ``accepted``).
- ``dispute``   → ``disputes``: an open, *nominated* conflict. This is the one verdict that adds a
  finding rather than closing one, and it is why the family exists at all. Detection
  (:func:`yigraf.contradiction.detect_conflicts`) is derived and fails open to silence when there is
  no embedding index, so across a team a conflict is otherwise visible only to whoever happens to have
  one. A nomination is durable and distributes over the log, so every client sees the same open set —
  index or not. It is the "open a PR" step of the git-shaped flow: it blocks nothing, it just makes
  the disagreement a fact of the graph with an actor's name on it.

Content-addressed like every other assertion: the id hashes ``(kind, left, right)``, so two principals
independently reaching the same verdict collapse to one node rather than forking (mem:060/mem:063).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from yigraf.log import assertion_id

RESOLUTION_FAMILY = "resolution"
CONF = "EXTRACTED"  # an authored verdict is asserted truth, not inferred

#: The verdicts a principal may record, and the relation each projects between the two operands.
PROJECTED_RELATION = {
    "reconcile": "equivalent_to",
    "supersede": "supersedes",
    "dispute": "disputes",
}
RESOLUTION_KINDS = tuple(PROJECTED_RELATION)

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


def _split_frontmatter(text: str) -> tuple[dict, str]:
    match = _FRONTMATTER.match(text)
    if match is None:
        return {}, text
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValueError("resolution frontmatter must be a YAML mapping")
    return meta, match.group(2)


def _compose(meta: dict, body: str) -> str:
    front = yaml.safe_dump(meta, sort_keys=True, allow_unicode=True, default_flow_style=False)
    body = body if body.endswith("\n") or not body else body + "\n"
    return f"---\n{front}---\n{body}"


def resolution_id(kind: str, left: str, right: str) -> str:
    """Content-address a verdict by ``(kind, left, right)`` — ``res:<16-hex>``.

    Deliberately excludes ``why`` and provenance, exactly as ``memid-v1``/``assertid-v1`` exclude
    parents and attribution (mem:063): two principals reaching the same verdict on the same pair are
    asserting the *same thing*, so the log collapses them and unions their provenance rather than
    recording a fork. Their reasons differing is not a different claim.
    """
    return "res:" + assertion_id(RESOLUTION_FAMILY, {"kind": kind, "left": left, "right": right})


@dataclass
class Resolution:
    """One authored verdict on a pair of beliefs."""

    id: str
    kind: str  # reconcile | supersede | dispute
    left: str
    right: str
    why: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    source_file: str | None = None

    @property
    def relation(self) -> str:
        """The edge this verdict projects from ``left`` to ``right``."""
        return PROJECTED_RELATION[self.kind]


def resolutions_dir(root: Path) -> Path:
    return Path(root) / "yigraf" / "resolutions"


def resolution_path(root: Path, res: Resolution) -> Path:
    """``resolutions/<kind>-<hash>.md`` — hash-named like a memory, so the filename is stable."""
    if res.source_file:
        return Path(root) / "yigraf" / res.source_file
    return resolutions_dir(root) / f"{res.kind}-{res.id.split(':', 1)[1]}.md"


def render_resolution(res: Resolution) -> str:
    meta: dict[str, Any] = {
        "id": res.id,
        "family": RESOLUTION_FAMILY,
        "kind": res.kind,
        "left": res.left,
        "right": res.right,
    }
    if res.provenance:
        meta["provenance"] = dict(res.provenance)
    body = f"## Why\n\n{res.why.strip()}\n" if res.why.strip() else ""
    return _compose(meta, body)


def read_resolution(path: Path) -> Resolution:
    meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    kind = str(meta.get("kind") or "")
    if kind not in PROJECTED_RELATION:
        raise ValueError(f"{path.name}: unknown resolution kind {kind!r} "
                         f"(expected one of {', '.join(RESOLUTION_KINDS)})")
    why = ""
    match = re.search(r"^##\s+Why\s*$\n(.*)\Z", body, re.MULTILINE | re.DOTALL)
    if match:
        why = match.group(1).strip()
    return Resolution(
        id=str(meta.get("id") or resolution_id(kind, meta.get("left", ""), meta.get("right", ""))),
        kind=kind,
        left=str(meta.get("left") or ""),
        right=str(meta.get("right") or ""),
        why=why,
        provenance=dict(meta.get("provenance") or {}),
        source_file=f"resolutions/{path.name}",
    )


def iter_resolutions(root: Path) -> list[Resolution]:
    d = resolutions_dir(root)
    return [read_resolution(p) for p in sorted(d.glob("*.md"))] if d.is_dir() else []


def find_resolution(root: Path, kind: str, left: str, right: str) -> Resolution | None:
    """An existing verdict of ``kind`` over the pair, in either operand order."""
    for res in iter_resolutions(root):
        if res.kind != kind:
            continue
        if (res.left, res.right) in ((left, right), (right, left)):
            return res
    return None


def resolved_pairs(root: Path) -> dict[str, set[tuple[str, str]]]:
    """Every authored verdict as ``{kind: {(left, right), …}}`` with each pair normalized to sorted
    order — the shape :mod:`yigraf.contradiction` wants for set membership regardless of who was
    named first."""
    out: dict[str, set[tuple[str, str]]] = {kind: set() for kind in RESOLUTION_KINDS}
    for res in iter_resolutions(root):
        pair = (res.left, res.right) if res.left <= res.right else (res.right, res.left)
        out[res.kind].add(pair)
    return out
