"""Per-file SHA content cache for structure extraction (``yigraf/cache/structure.json``).

Keyed by the raw file bytes' SHA-256: a hit means the file is byte-for-byte unchanged since it was
last extracted, so its cached node/edge projection is reused verbatim and tree-sitter is skipped.
This is the *file cache SHA* of ``docs/m1-notes.md`` §3 — distinct from a symbol's astnorm
``content_hash``. The cache is gitignored and rebuildable; it never affects the output graph (which
is deterministic), only whether a file is re-parsed. It is invalidated wholesale when the astnorm
algorithm version changes, so a stale anchor can never survive a rule change.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from yigraf.astnorm import ANCHOR_ALGO

if TYPE_CHECKING:
    from yigraf.extract import FileProjection

#: Bumped when the on-disk cache layout changes incompatibly (separate from the astnorm algo).
#: 2: structure nodes gained a ``signature`` field (M4).
#: 3: file nodes gained an ``inherits`` field (import-aware inheritance edges) — a stale cache would
#:    otherwise serve pre-inheritance projections for files that haven't changed since the upgrade.
#: 4: the tags-tier extractors began populating ``inherits`` too (inheritance across the breadth
#:    languages), so a format-3 cache of e.g. a Java file lacks its inheritance — invalidate it.
#: 5: Kotlin/Scala began recording ``imports`` on the file node (import edges) — a format-4 cache of
#:    those files has an empty imports list.
CACHE_FORMAT = 5


def file_sha(data: bytes) -> str:
    """SHA-256 hex of raw file bytes — the cache key (a file changed at all)."""
    return hashlib.sha256(data).hexdigest()


@dataclass
class StructureCache:
    """Reusable per-file extraction projections, keyed by relative path then content SHA.

    Also carries a small HEAD-keyed ``maturity`` slot (R2 survival counts): recomputing maturity
    walks git history, but an edit never moves ``HEAD``, so this lets the hot ``PostToolUse`` rebuild
    skip the walk until a commit actually lands. Like the rest of the cache it's gitignored,
    rebuildable, and never alters the (deterministic) output graph — only how survival is obtained.
    """

    algo: str
    entries: dict[str, dict]
    maturity: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "StructureCache":
        """Load the cache, or start empty if absent, unreadable, or built by a different algo."""
        p = Path(path)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
            if data.get("format") == CACHE_FORMAT and data.get("algo") == ANCHOR_ALGO:
                return cls(algo=ANCHOR_ALGO, entries=dict(data.get("files", {})),
                           maturity=dict(data.get("maturity", {})))
        return cls(algo=ANCHOR_ALGO, entries={})

    def maturity_survival(self, head: str) -> dict | None:
        """Cached ``{path: survival}`` if it was computed at this ``HEAD``, else ``None`` (a miss)."""
        if self.maturity.get("head") == head:
            return dict(self.maturity.get("survival", {}))
        return None

    def set_maturity_survival(self, head: str, survival: dict) -> None:
        """Record the survival map computed at ``head`` (replaces any map from an earlier HEAD)."""
        self.maturity = {"head": head, "survival": dict(survival)}

    def get(self, relpath: str, sha: str) -> "FileProjection | None":
        """Return the cached projection for ``relpath`` iff its content SHA still matches."""
        from yigraf.extract import FileProjection

        entry = self.entries.get(relpath)
        if entry is not None and entry.get("sha") == sha:
            return FileProjection.from_cache(entry)
        return None

    def put(self, relpath: str, sha: str, projection: "FileProjection") -> None:
        """Record ``projection`` for ``relpath`` under its content SHA."""
        self.entries[relpath] = {"sha": sha, **projection.to_cache()}

    def prune(self, keep: set[str]) -> None:
        """Drop cached entries for files no longer present in the repo."""
        for relpath in list(self.entries):
            if relpath not in keep:
                del self.entries[relpath]

    def save(self, path: Path) -> None:
        """Write the cache as deterministic JSON (sorted keys)."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        out = {"format": CACHE_FORMAT, "algo": self.algo, "files": self.entries,
               "maturity": self.maturity}
        p.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
