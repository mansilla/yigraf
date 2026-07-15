"""The gitignored SQLite **materialized view** of the graph — replaces the committed ``graph.json``
(task concurrent-write-v1/5, int:yigraf-local-v1).

Truth is the content-addressed markdown assertion files (mem:059); this is the *derived, gitignored*
projection those files fold into. It replaces ``graph.json`` for two reasons mem:059 settled: a
committed ``.db`` is a binary blob git can't textual-merge (every concurrent branch conflicts on the
whole database — the "whole-graph lock" this task retires), and the projection should never be a write
target anyway (R1/R6). So the view lives under the gitignored ``yigraf/.local/`` and is never committed.

The view is keyed by a cheap **content fingerprint** of the graph's inputs — the source files
:func:`yigraf.extract.build_graph` walks plus the authored intent/plan/memory markdown plus
``config.yaml``. A read path (:func:`load_or_build`) loads the persisted view when the fingerprint
still matches, skipping the tree-sitter rebuild; otherwise it rebuilds and re-materializes. This is
*correct* because the persisted graph is a pure function of those inputs: the volatile / git-HEAD
overlays (``survival``, telemetry, the ``settled`` verdict) are stripped at store time
(:data:`yigraf.graph._VOLATILE_NODE_ATTRS`) and re-applied on the in-memory graph after a load, exactly
as after a build. Never truth, always recomputable: any corruption / schema mismatch falls open to a
full rebuild.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import networkx as nx

from yigraf.astnorm import ANCHOR_ALGO
from yigraf.graph import _EDGES_KEY, _VOLATILE_NODE_ATTRS, empty_graph, to_node_link

#: Bumped when the SQLite schema or the fingerprint recipe changes incompatibly (⇒ every existing view
#: is treated as absent and rebuilt). Distinct from :data:`yigraf.graph.SCHEMA_VERSION` (the node-link
#: shape) — this guards the DB layout + fingerprint, so either changing invalidates cached views.
DB_SCHEMA_VERSION = 1

#: The authored-artifact subdirectories the fold reads (mirrors scaffold's ``_ARTIFACT_DIRS``); each
#: ``.md`` under them is one assertion, so it feeds the fingerprint like a source file.
_ARTIFACT_SUBDIRS = ("intents", "plans/active", "plans/completed", "memory")

_SCHEMA = """
CREATE TABLE meta  (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE nodes (id TEXT PRIMARY KEY, family TEXT, attrs TEXT NOT NULL);
CREATE TABLE edges (source TEXT NOT NULL, target TEXT NOT NULL, relation TEXT,
                    attrs TEXT NOT NULL, PRIMARY KEY (source, target));
"""


def db_path(root: Path) -> Path:
    """The gitignored materialized-view path: ``yigraf/.local/graph.db`` (``.local/`` is gitignored)."""
    return Path(root) / "yigraf" / ".local" / "graph.db"


def load_workspace(root: Path) -> nx.DiGraph | None:
    """Load the materialized view at ``root``'s standard workspace path, or ``None`` if not built yet."""
    return load(db_path(root))


# --------------------------------------------------------------------------------------------------
# Content fingerprint — the cache key over the graph's inputs (stat-only, so it never reads a file)
# --------------------------------------------------------------------------------------------------


def _input_files(root: Path, config: dict) -> list[Path]:
    """Every file whose content the materialized graph depends on: the source files
    :func:`yigraf.extract.build_graph` walks (same discovery + ignore rules) + the authored
    intent/plan/memory markdown + ``config.yaml``. Returned as absolute paths.
    """
    from yigraf.extract import _iter_source_files  # local: avoid an import cycle at module load
    from yigraf.languages import available_extractors, extension_map

    root = Path(root)
    ignore_dirs = {p.rstrip("/").strip() for p in config.get("ignore", [])}
    ext_map = extension_map(available_extractors(config))
    paths = [root / rel for rel in _iter_source_files(root, ignore_dirs, set(ext_map))]

    ws = root / "yigraf"
    for sub in _ARTIFACT_SUBDIRS:
        d = ws / sub
        if d.is_dir():
            paths.extend(sorted(d.glob("*.md")))
    config_path = ws / "config.yaml"
    if config_path.is_file():
        paths.append(config_path)
    return paths


def source_fingerprint(root: Path, config: dict) -> str:
    """A cheap, deterministic content fingerprint of the graph's inputs (stat-only — no file reads).

    Hashes ``(relpath, st_mtime_ns, st_size)`` for every input file, tagged with the DB schema and the
    anchor algorithm so a bump of either invalidates the view. Fail-open per file: a stat error folds
    into the digest as a sentinel, so a vanished/unreadable file just changes the fingerprint (⇒ rebuild)
    rather than raising. mtime+size is the standard build-cache key; a content change that preserves both
    is astronomically rare on a real editor write, and ``yigraf build`` is the hard-refresh escape hatch.
    """
    root = Path(root)
    h = hashlib.sha256()
    h.update(f"schema={DB_SCHEMA_VERSION};anchor={ANCHOR_ALGO}\n".encode())
    for path in sorted(_input_files(root, config)):
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = str(path)
        try:
            st = path.stat()
            h.update(f"{rel}\0{st.st_mtime_ns}\0{st.st_size}\n".encode())
        except OSError:
            h.update(f"{rel}\0MISSING\n".encode())
    return h.hexdigest()


# --------------------------------------------------------------------------------------------------
# Materialize / load — the SQLite projection (nodes + edges + meta), volatile attrs stripped
# --------------------------------------------------------------------------------------------------


def materialize(graph: nx.DiGraph, path: Path, fingerprint: str) -> None:
    """Write ``graph`` to the SQLite view at ``path`` (created fresh), stamped with ``fingerprint``.

    Uses :func:`yigraf.graph.to_node_link` so the persisted node/edge shape is exactly the one the
    retired ``graph.json`` carried — volatile attrs stripped, nodes/edges deterministically sorted. The
    ``g.graph`` attrs (``schema_version``/``anchor_algo``) ride ``meta`` so a load restores them. Written
    to a temp file and atomically renamed, so a concurrent reader never sees a half-written view.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = to_node_link(graph)
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(_SCHEMA)
        conn.executemany(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            [("db_schema_version", str(DB_SCHEMA_VERSION)),
             ("fingerprint", fingerprint),
             ("graph_attrs", json.dumps(data.get("graph", {}), sort_keys=True))],
        )
        conn.executemany(
            "INSERT INTO nodes (id, family, attrs) VALUES (?, ?, ?)",
            [(n["id"], n.get("family"), json.dumps(n, sort_keys=True)) for n in data["nodes"]],
        )
        conn.executemany(
            "INSERT INTO edges (source, target, relation, attrs) VALUES (?, ?, ?, ?)",
            [(e["source"], e["target"], e.get("relation"), json.dumps(e, sort_keys=True))
             for e in data[_EDGES_KEY]],
        )
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp, path)


def stored_fingerprint(path: Path) -> str | None:
    """The fingerprint the view at ``path`` was materialized with, or ``None`` (absent/corrupt/wrong
    schema) — cheap (one indexed row read), so a read path can decide load-vs-rebuild without opening
    the whole graph."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if rows.get("db_schema_version") != str(DB_SCHEMA_VERSION):
        return None
    return rows.get("fingerprint")


def load(path: Path) -> nx.DiGraph | None:
    """Rebuild the in-memory :class:`~networkx.DiGraph` from the view at ``path``, or ``None`` if it's
    absent / corrupt / a stale schema (so the caller falls open to a full rebuild)."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
            if meta.get("db_schema_version") != str(DB_SCHEMA_VERSION):
                return None
            node_rows = conn.execute("SELECT attrs FROM nodes").fetchall()
            edge_rows = conn.execute("SELECT attrs FROM edges").fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return None

    graph = empty_graph()
    graph.graph.clear()
    graph.graph.update(json.loads(meta.get("graph_attrs", "{}")))
    for (attrs_json,) in node_rows:
        n = json.loads(attrs_json)
        node_id = n.pop("id")
        graph.add_node(node_id, **n)
    for (attrs_json,) in edge_rows:
        e = json.loads(attrs_json)
        source, target = e.pop("source"), e.pop("target")
        graph.add_edge(source, target, **e)
    return graph


# --------------------------------------------------------------------------------------------------
# Orchestration — the two seams the CLI uses: rebuild (write paths) + load_or_build (read paths)
# --------------------------------------------------------------------------------------------------


def rebuild(root: Path, config: dict):
    """Build the graph fresh and re-materialize the view. The write-path seam (``build`` / ``_rebuild``):
    an authored artifact just landed, so the projection must reflect it. Returns ``(graph, BuildStats)``."""
    from yigraf.extract import build_graph  # local: avoid an import cycle at module load

    root = Path(root)
    graph, stats = build_graph(root, config)
    materialize(graph, db_path(root), source_fingerprint(root, config))
    return graph, stats


def load_or_build(root: Path, config: dict) -> tuple[nx.DiGraph, bool]:
    """The read-path seam: load the materialized view when its fingerprint still matches the inputs,
    else rebuild + re-materialize. Returns ``(graph, was_cached)``.

    On a cache hit the git-derived ``survival`` overlay is re-stamped only when the optional survival
    floor is armed (``maturity_survival_floor > 0``) — the landed tier is already persisted, and the
    telemetry / ``settled``-verdict overlays are re-applied by the caller (``_ranked_with_telemetry``)
    just as on a fresh build, so a loaded graph and a built one are query-equivalent.
    """
    from yigraf import counters  # local: avoid an import cycle at module load
    from yigraf.extract import build_graph

    root = Path(root)
    db = db_path(root)
    if stored_fingerprint(db) == source_fingerprint(root, config):
        graph = load(db)
        if graph is not None:
            if int(config.get("maturity_survival_floor", 0)) > 0:
                counters.apply_maturity(graph, root, config)
            return graph, True
    graph, _ = build_graph(root, config)
    materialize(graph, db, source_fingerprint(root, config))
    return graph, False
