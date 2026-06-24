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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from yigraf.astnorm import ANCHOR_ALGO

if TYPE_CHECKING:
    from yigraf.extract import FileProjection

#: Bumped when the on-disk cache layout changes incompatibly (separate from the astnorm algo).
CACHE_FORMAT = 1


def file_sha(data: bytes) -> str:
    """SHA-256 hex of raw file bytes — the cache key (a file changed at all)."""
    return hashlib.sha256(data).hexdigest()


@dataclass
class StructureCache:
    """Reusable per-file extraction projections, keyed by relative path then content SHA."""

    algo: str
    entries: dict[str, dict]

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
                return cls(algo=ANCHOR_ALGO, entries=dict(data.get("files", {})))
        return cls(algo=ANCHOR_ALGO, entries={})

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
        out = {"format": CACHE_FORMAT, "algo": self.algo, "files": self.entries}
        p.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
