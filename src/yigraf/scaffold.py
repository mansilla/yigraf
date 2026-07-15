"""``yigraf init``: lay down the per-repo ``yigraf/`` workspace.

Creates the committed artifact tree (intents / plans / memory + ``config.yaml``) plus the gitignored
runtime dirs, and writes a self-contained ``.gitignore`` *inside* the workspace so any repo gets correct
ignore behavior. The queryable graph is a *derived, gitignored* SQLite materialized view
(``.local/graph.db``), never committed (mem:059) — so init lays down no committed projection and no
merge driver. The operation is idempotent: existing files are reported and left untouched.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from yigraf.config import DEFAULT_CONFIG_YAML

WORKSPACE_DIRNAME = "yigraf"

# Committed artifact dirs (one node per .md file lives under these).
_ARTIFACT_DIRS = ["intents", "plans/active", "plans/completed", "memory"]

# Rebuildable / volatile runtime dirs — gitignored (DESIGN.md R1).
_RUNTIME_DIRS = ["index", "cache", ".local"]

# NOTE: comments live on their own lines — git only treats a line as a comment when it *starts*
# with '#', so a trailing "# ..." after a pattern would corrupt the pattern.
_WORKSPACE_GITIGNORE = """\
# yigraf runtime state — rebuildable or machine-local, never committed (DESIGN.md R1).
# index/  : embedding index, rebuilt from memory+intent text
# cache/  : SHA256 content-extraction cache
# .local/ : machine-local runtime state — telemetry (usage / last_seen) + the SQLite materialized
#           view (graph.db). The graph is a derived projection of the committed assertion files
#           (mem:059), so it is never committed; a stale ``graph.json`` from a pre-v1 workspace is
#           ignored too, so it drops out of git once removed.
index/
cache/
.local/
graph.json
"""


@dataclass
class InitResult:
    """What ``init_workspace`` created vs. found already present."""

    root: Path
    workspace: Path
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def already_initialized(self) -> bool:
        """True when nothing new was created (every path already existed)."""
        return not self.created


def _ensure_dir(path: Path, root: Path, result: InitResult) -> None:
    rel = f"{path.relative_to(root)}/"
    if path.is_dir():
        result.skipped.append(rel)
    else:
        path.mkdir(parents=True, exist_ok=True)
        result.created.append(rel)


def _write_if_absent(path: Path, content: str, root: Path, result: InitResult) -> None:
    rel = str(path.relative_to(root))
    if path.exists():
        result.skipped.append(rel)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    result.created.append(rel)


def init_workspace(root: Path) -> InitResult:
    """Create (or top up) the ``yigraf/`` workspace under ``root``. Idempotent."""
    root = Path(root)
    ws = root / WORKSPACE_DIRNAME
    result = InitResult(root=root, workspace=ws)

    _ensure_dir(ws, root, result)
    for rel in (*_ARTIFACT_DIRS, *_RUNTIME_DIRS):
        _ensure_dir(ws / rel, root, result)

    _write_if_absent(ws / "config.yaml", DEFAULT_CONFIG_YAML, root, result)
    _write_if_absent(ws / ".gitignore", _WORKSPACE_GITIGNORE, root, result)

    # No committed projection: the graph materializes into the gitignored SQLite view (.local/graph.db)
    # on the first `yigraf build`/query. Truth is the assertion files under the artifact dirs (mem:059).
    return result
