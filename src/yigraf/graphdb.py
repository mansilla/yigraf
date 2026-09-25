"""The gitignored SQLite **materialized view** of the graph — replaces the committed ``graph.json``
(task concurrent-write-v1/5, int:yigraf-local-v1).

Truth is the content-addressed markdown assertion files (mem:059); this is the *derived, gitignored*
projection those files fold into. It replaces ``graph.json`` for two reasons mem:059 settled: a
committed ``.db`` is a binary blob git can't textual-merge (every concurrent branch conflicts on the
whole database — the "whole-graph lock" this task retires), and the projection should never be a write
target anyway (R1/R6). So the view lives under the gitignored ``yigraf/.local/`` and is never committed.

The view is keyed by a cheap **content fingerprint** of the graph's inputs — the source files
:func:`yigraf.extract.build_graph` walks plus the authored intent/plan/memory markdown plus
``config.yaml`` plus, for a workspace bound to a project, the synced ``replica.db``. A read path
(:func:`load_or_build`) loads the persisted view when the fingerprint still matches, skipping the
tree-sitter rebuild; otherwise it rebuilds and re-materializes. This is *correct* because the persisted
graph is a pure function of those inputs: the volatile / git-HEAD overlays (``survival``, telemetry, the
``settled`` verdict) are stripped at store time (:data:`yigraf.graph._VOLATILE_NODE_ATTRS`,
:data:`~yigraf.graph._VOLATILE_GRAPH_ATTRS`) and re-applied on the in-memory graph after a load, exactly
as after a build. Never truth, always recomputable: any corruption / schema mismatch falls open to a
full rebuild, and a view that cannot be *written* falls open to an uncached one (:class:`ViewUnwritable`).

"Pure function of those inputs" is the whole warrant, and the replica is in the list because two things
the view carries come from it and from nowhere else: a teammate's pulled assertion, folded onto the same
base as the local artifacts, and the divergence verdict over the revisions that fold declined
(:func:`yigraf.extract._fold_replica`). Leaving it out did not make the view cheaper — it made the
cached read serve a *snapshot* of both, taken whenever the view was last materialized. The count that
reached the agent was measured against a replica that had since moved, and the one action yigraf
advertises for clearing a phantom count (``yigraf whoami``, which teaches the workspace its own actor)
writes only the replica, so it could never invalidate the view it was trying to correct.
"""
from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Sequence
from pathlib import Path

import networkx as nx

from yigraf.astnorm import ANCHOR_ALGO, parse_file_target
from yigraf.config import replica_path
from yigraf.graph import _EDGES_KEY, _VOLATILE_NODE_ATTRS, empty_graph, to_node_link

#: Bumped when the SQLite schema or the fingerprint recipe changes incompatibly (⇒ every existing view
#: is treated as absent and rebuilt). Distinct from :data:`yigraf.graph.SCHEMA_VERSION` (the node-link
#: shape) — this guards the DB layout + fingerprint, so either changing invalidates cached views.
DB_SCHEMA_VERSION = 3

#: Where an *unresolved* ``file:`` locus is stashed. These are inputs whose ARRIVAL matters, so the
#: fingerprint must watch them even though no node exists for them yet (see :func:`governed_file_paths`).
_DANGLING_ATTRS = ("dangling_implements", "dangling_concerns", "dangling_grounded_by")

#: Rejection-applicability premises: node attrs, not edges, and a ``file:`` one is a pure presence check.
_PREMISE_ATTRS = ("rejected_valid_when", "rejected_invalidated_when")

#: The authored-artifact subdirectories the fold reads (mirrors scaffold's ``_ARTIFACT_DIRS``); each
#: ``.md`` under them is one assertion, so it feeds the fingerprint like a source file.
_ARTIFACT_SUBDIRS = ("intents", "plans/active", "plans/completed", "memory")

_SCHEMA = """
CREATE TABLE meta  (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE nodes (id TEXT PRIMARY KEY, family TEXT, attrs TEXT NOT NULL);
CREATE TABLE edges (source TEXT NOT NULL, target TEXT NOT NULL, relation TEXT,
                    attrs TEXT NOT NULL, PRIMARY KEY (source, target));
"""

#: Guidance from a materialize that failed, parked on ``graph.graph`` for a *write* seam's caller to
#: surface. A property of this run and not of the projection, so it is stripped at serialization
#: (:data:`yigraf.graph._VOLATILE_GRAPH_ATTRS`) and can never land in the persisted view (design law
#: #6). ``diverged`` and ``survival_measurable`` used to be named here as the other two members of that
#: channel, and neither is one: both are properties of the *inputs* — see the reasons in that set's
#: docstring. Misfiling ``diverged`` is what let a stale count reach the agent, since believing it was
#: stripped at store time is also believing it could not be served from the view.
_UNWRITABLE_KEY = "view_unwritable"


class ViewUnwritable(Exception):
    """The materialized view could not be written. ``guidance`` hands back the fix (design law #1).

    Never a stop-condition: the view is a *derived, recomputable* projection of the markdown (design law
    #6), so a failed write costs a cache entry, not an answer — the graph the caller just built is
    intact in memory and both seams here (:func:`rebuild`, :func:`load_or_build`) degrade to an uncached
    rebuild rather than failing the agent's command. Mirrors :class:`yigraf.online.LinkError`: the layer
    that knows *why* the write failed writes the sentence, the CLI decides where it lands. Raised in
    place of the raw ``sqlite3``/``OSError`` so no caller has to interpret a storage error to stay
    fail-open.
    """

    def __init__(self, path: Path, cause: BaseException) -> None:
        self.path = Path(path)
        self.cause = cause
        self.guidance = _unwritable_guidance(self.path, cause)
        super().__init__(self.guidance)


def _unwritable_guidance(path: Path, cause: BaseException) -> str:
    """Name what blocked the write and the one thing that fixes it (design law #1).

    Every case is an environment problem the caller can correct, and none of them cost the answer, so
    the message leads with *that*: an agent told only "could not write the database" concludes yigraf is
    broken and stops calling it — the abandonment design law #1 exists to prevent. Saying the view is a
    cache over markdown that is still the truth is what makes the next call happen anyway.
    """
    detail = str(cause)
    if getattr(cause, "errno", None) == errno.ENOSPC or "disk is full" in detail:
        why, fix = f"the disk holding {path.parent} is full", "free some space"
    elif (getattr(cause, "errno", None) in (errno.EACCES, errno.EPERM)
            or "readonly database" in detail or "unable to open database" in detail):
        why = f"{path.parent} isn't writable by this user"
        fix = (f"check the permissions on {path.parent} — and on {path.name} itself, if an earlier "
               f"`sudo yigraf` run left it owned by root")
    else:
        why, fix = f"writing {path} failed ({detail})", f"check that {path.parent} is writable"
    return (f"Couldn't cache the graph: {why}. Nothing was lost — {path.name} is a derived, gitignored "
            f"view (the markdown under yigraf/ is the truth), so this command's answer is still correct; "
            f"it just wasn't saved, and the next command will recompute it instead of loading it. "
            f"To make it stick: {fix}.")


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
    intent/plan/memory markdown + ``config.yaml`` + the synced replica, when there is one. Returned as
    absolute paths.

    The replica is an input for the same reason every other entry here is: the build reads it
    (:func:`yigraf.extract._fold_replica` folds a teammate's assertions onto the local base and records
    which declined revisions diverge), so a view materialized before it moved is a view of different
    inputs. It is named whether or not it exists yet — a bound workspace that has never synced has no
    replica file, and its *arrival* is what starts the fold, exactly like a governed ``file:`` locus
    (:func:`governed_file_paths`). Offline there is nothing to name: no ``online.project`` ⇒
    :func:`~yigraf.config.replica_path` returns ``None`` ⇒ the digest is what it always was.
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
    replica = replica_path(root, config)
    if replica is not None:
        paths.append(replica)
    return paths


def governed_file_paths(graph: nx.DiGraph) -> list[str]:
    """The repo-relative paths this graph's ``file:`` anchors point at (sorted, deduplicated).

    These are graph inputs that :func:`_input_files` cannot discover: a governed Dockerfile, buildspec
    or doc is neither an extractable source file nor a yigraf artifact, so nothing else in the
    fingerprint moves when one is edited. Without them the cache-backed read paths — ``context`` and the
    PostToolUse hook — serve a *stale* hash for the very file the agent just changed, so the edit hook
    goes silent about the locus it was called for while ``status``, which always rebuilds, reports the
    drift: two surfaces disagreeing about the same file, with the quiet one on the hot path.

    Read off the last built graph rather than rediscovered, because parsing every assertion file to find
    them would cost far more than the stat walk the fingerprint exists to be. A locus that is *added* or
    *removed* arrives by an edited assertion file, which is already an input — so the set refreshes on
    the same rebuild that changed it.

    **Dangling** loci count too, and that half is not symmetric with the rest: a node is minted only for
    a locus that resolves, so reading the minted nodes alone watched exactly the files whose *content*
    can change and none of the ones whose *arrival* matters. A forward reference told the caller "it
    governs once that section is written" and then the writing of it did not invalidate the view, so the
    edit hook stayed silent on the very edit that fulfilled it; a ``file:`` rejection premise
    ("withdraws this the moment that file appears") kept reporting absent on the cached read path after
    the file appeared. So the dangling edges and the ``file:`` premises are swept as well.
    """
    paths = {attrs["source_file"] for _, attrs in graph.nodes(data=True)
             if attrs.get("kind") == "file-anchor" and attrs.get("source_file")}
    for _node, attrs in graph.nodes(data=True):
        pending = [entry.get("sym") for key in _DANGLING_ATTRS for entry in attrs.get(key) or []]
        pending += [ref for key in _PREMISE_ATTRS for ref in attrs.get(key) or []]
        for locus in pending:
            if isinstance(locus, str) and locus.startswith("file:"):
                paths.add(parse_file_target(locus)[0])
    return sorted(p for p in paths if p)


def source_fingerprint(root: Path, config: dict, extra: Sequence[str] = ()) -> str:
    """A cheap, deterministic content fingerprint of the graph's inputs (stat-only — no file reads).

    Hashes ``(relpath, st_mtime_ns, st_size)`` for every input file, tagged with the DB schema and the
    anchor algorithm so a bump of either invalidates the view. Fail-open per file: a stat error folds
    into the digest as a sentinel, so a vanished/unreadable file just changes the fingerprint (⇒ rebuild)
    rather than raising. mtime+size is the standard build-cache key; a content change that preserves both
    is astronomically rare on a real editor write, and ``yigraf build`` is the hard-refresh escape hatch.

    ``extra`` names additional repo-relative inputs to stat — the governed ``file:`` loci from
    :func:`governed_file_paths`. Paths are deduplicated before hashing, so a locus that *is* also a
    source file (a line range in indexed code) counts once and the digest stays independent of how a
    path was discovered.
    """
    root = Path(root)
    h = hashlib.sha256()
    h.update(f"schema={DB_SCHEMA_VERSION};anchor={ANCHOR_ALGO}\n".encode())
    rels = {str(rel) for rel in extra}
    for path in _input_files(root, config):
        try:
            rels.add(path.relative_to(root).as_posix())
        except ValueError:
            rels.add(str(path))
    for rel in sorted(rels):
        try:
            st = (root / rel).stat()
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

    Raises :class:`ViewUnwritable` — carrying the operator-facing fix, never a raw storage error — when
    the environment refuses the write (unwritable dir, root-owned db, full disk). The catch is
    deliberately narrow: ``sqlite3.OperationalError`` is *this* module's environment channel because the
    SQL here is fixed and schema-checked, so a programming error (``IntegrityError`` on a duplicate node
    id, say) is a real bug and must still surface as itself rather than be dressed up as bad permissions.
    """
    path = Path(path)
    # The serializer strips the per-run graph attr (`view_unwritable`) along with the volatile node
    # ones, so there is nothing left to pop here. It has to be there rather than here:
    # `status._freshness` compares this same projection against a rebuild, and a key stripped only on
    # the way to disk makes the two differ over a property neither the source nor the fold produced.
    data = to_node_link(graph)  # detached from ``graph`` — never edits the live graph
    # Per-process temp name: two hooks rebuilding at once shared one `graph.db.tmp`, so one could unlink
    # the other's half-written file or rename it into place mid-write (feedback-v12, L#1's class).
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _sweep_orphan_temps(path)
        if tmp.exists():
            tmp.unlink()
        conn = sqlite3.connect(tmp)
        try:
            conn.executescript(_SCHEMA)
            conn.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                [("db_schema_version", str(DB_SCHEMA_VERSION)),
                 ("fingerprint", fingerprint),
                 # The governed file: loci this fingerprint accounted for. A reader cannot recompute
                 # them without the graph it is deciding whether to load, so they ride the view.
                 ("governed_files", json.dumps(governed_file_paths(graph))),
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
    except (OSError, sqlite3.OperationalError) as exc:
        try:  # never leave a half-written .tmp behind to be mistaken for the view
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise ViewUnwritable(path, exc) from exc


#: A temp view older than this belongs to a writer that died (a host SIGKILL at its timeout) — a live
#: materialize takes seconds. Generous, because sweeping a live writer's file would fail its rename.
_ORPHAN_TEMP_SECONDS = 600


def _sweep_orphan_temps(path: Path) -> None:
    """Remove temp views left by killed writers. Per-pid names are never reused, so nothing else would."""
    cutoff = time.time() - _ORPHAN_TEMP_SECONDS
    for stale in path.parent.glob(f"{path.name}.*.tmp*"):  # `*` after: sqlite's `-journal` siblings too
        try:
            if stale.stat().st_mtime < cutoff:
                stale.unlink()
        except OSError:
            pass


def view_state(path: Path) -> str:
    """Why the view at ``path`` is (un)loadable: ``"present"`` | ``"missing"`` | ``"old-schema"`` |
    ``"unreadable"``.

    :func:`load` collapses all three failures into ``None``, which is right for a *read path* — every
    one of them means "rebuild" — but wrong for a surface that has to **name** the state. ``yigraf
    status`` reported all three as ``absent``, and after a version upgrade the true state is neither
    missing nor damaged: the previous yigraf wrote a lower ``db_schema_version``, this one declines it,
    and :func:`load_or_build` rebuilds it on the next read. Told "absent", a reader diagnoses a lost
    graph; told the schema is old, they know an upgrade did it and that nothing is lost (feedback-v5 A).

    Cheap by construction — one small ``meta`` read, no nodes, no edges — so the statusline can afford
    it on every refresh.
    """
    path = Path(path)
    if not path.is_file():
        return "missing"
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        finally:
            conn.close()
    except sqlite3.Error:
        return "unreadable"
    if rows.get("db_schema_version") != str(DB_SCHEMA_VERSION):
        return "old-schema"
    return "present"


def stored_meta(path: Path) -> tuple[str | None, list[str]]:
    """``(fingerprint, governed_files)`` for the view at ``path``; ``(None, [])`` if it's absent, corrupt
    or a stale schema — cheap (one small table read), so a read path can decide load-vs-rebuild without
    opening the whole graph.

    Both come back together because the comparison needs both: the stored fingerprint accounted for
    those governed loci, so recomputing it without them would never match and every read would rebuild.
    """
    path = Path(path)
    if not path.is_file():
        return None, []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        finally:
            conn.close()
    except sqlite3.Error:
        return None, []
    if rows.get("db_schema_version") != str(DB_SCHEMA_VERSION):
        return None, []
    try:
        governed = json.loads(rows.get("governed_files") or "[]")
    except (TypeError, ValueError):
        governed = []
    return rows.get("fingerprint"), (governed if isinstance(governed, list) else [])


def stored_fingerprint(path: Path) -> str | None:
    """The fingerprint the view at ``path`` was materialized with, or ``None``; see :func:`stored_meta`."""
    return stored_meta(path)[0]


def current_fingerprint(root: Path, config: dict) -> str:
    """The inputs' fingerprint, computed the way the *stored* view computed it — governed loci included.

    The seam for a caller that only wants "did anything the graph depends on change?" without loading
    the graph (the Stop hook's obligation latch). Comparing a bare :func:`source_fingerprint` against a
    stored one that counted governed files would report "unchanged" for a governed-doc edit, which is
    exactly the silence :func:`governed_file_paths` exists to end.
    """
    return source_fingerprint(root, config, stored_meta(db_path(root))[1])


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


def view_unwritable(graph: nx.DiGraph) -> bool:
    """Did the last :func:`_materialize_or_flag` on ``graph`` fail to persist it?"""
    return _UNWRITABLE_KEY in graph.graph


def _materialize_or_flag(graph: nx.DiGraph, root: Path, config: dict,
                         fingerprint: str | None = None) -> bool:
    """Materialize the view, or park the guidance on ``graph.graph`` and carry on. Returns whether it stuck.

    Both seams below degrade identically, for the same reason: the view is derived (design law #6), so
    an unwritable cache must never fail the command that only *incidentally* refreshes it — a
    ``remember`` whose artifact already landed on disk, or a ``context`` query whose answer is already
    computed. Failing either would report a write that succeeded as a crash, and teach the agent to stop
    calling the tool (design law #1) over a stale cache entry. What differs is who speaks: a write seam's
    caller surfaces the flag as guidance, a read seam's stays silent — never nag the hot edit path
    (design law #4).

    The flag is owned here, both ways: set on failure, cleared on success. Clearing it is stated rather
    than inherited — it used to happen only because :func:`~yigraf.graph.to_node_link` handed back
    ``graph.graph`` itself and ``materialize`` popped the key out of it, so a serializer's aliasing was
    load-bearing for this function's state. That serializer is pure now, so the write that fixes the
    condition is the one that retracts the guidance.

    ``fingerprint``, when given, is a digest the caller took **before** the build over the same governed
    set; without it this walks every input again — on a 22k-file tree, as long as the walk that decided
    to rebuild (feedback-v12 L#3: ``graph.materialize`` measured about equal to ``graph.fingerprint``).
    The earlier digest is also the *safer* stamp: a file that changes while the build runs leaves the
    view keyed to the pre-change tree, so the next read rebuilds, where a digest taken after the build
    would label pre-change content with post-change stats and serve it as current.
    """
    try:
        materialize(graph, db_path(root),
                    fingerprint or source_fingerprint(root, config, governed_file_paths(graph)))
        graph.graph.pop(_UNWRITABLE_KEY, None)  # the view is current again ⇒ earlier guidance is stale
        return True
    except ViewUnwritable as exc:
        graph.graph[_UNWRITABLE_KEY] = exc.guidance
        return False


def rebuild(root: Path, config: dict):
    """Build the graph fresh and re-materialize the view. The write-path seam (``build`` / ``_rebuild``):
    an authored artifact just landed, so the projection must reflect it. Returns ``(graph, BuildStats)``.

    Fail-open (design law #5): a view that can't be written leaves the built graph untouched and the fix
    on ``graph.graph["view_unwritable"]`` for the caller to surface — see :func:`_materialize_or_flag`."""
    from yigraf.extract import build_graph  # local: avoid an import cycle at module load

    root = Path(root)
    graph, stats = build_graph(root, config)
    _materialize_or_flag(graph, root, config)
    return graph, stats


def load_or_build(root: Path, config: dict, *, budget=None,
                  fingerprint: str | None = None) -> tuple[nx.DiGraph, bool]:
    """The read-path seam: load the materialized view when its fingerprint still matches the inputs,
    else rebuild + re-materialize. Returns ``(graph, was_cached)``.

    ``budget`` is an optional :class:`~yigraf.hookbudget.Budget`. This function is the whole cost of a
    hook's ``graph`` phase, so a breakdown that stops at ``graph`` cannot say whether a slow run was
    stat-walking its inputs, reading the view, or re-extracting — three answers with three different
    remedies. Given a budget, each step names itself as a ``graph.*`` sub-phase: dotted, because the
    report prints one flat row of phases and siblings there read as addends, while these sit *inside*
    ``graph`` and summing them with it would double-count.

    ``fingerprint`` lets a caller that already computed one — the way :func:`current_fingerprint` does,
    over the view's own governed loci — hand it over instead of having the walk repeated (the ``Stop``
    hook, which walked for its latch). It is the most expensive step here on a large working tree. Taken
    a moment earlier, it can only cost a needless rebuild or a view one read staler, never a wrong graph.
    Both ``graph.*`` sub-phases and this pass-through are the field's patch (feedback-v12 L#3).

    On a cache hit the git-derived ``survival`` overlay is re-stamped only when the optional survival
    floor is armed (``maturity_survival_floor > 0``) — the landed tier is already persisted, and the
    telemetry / ``settled``-verdict overlays are re-applied by the caller (``_ranked_with_telemetry``)
    just as on a fresh build, so a loaded graph and a built one are query-equivalent.

    A view that can't be persisted degrades to ``(graph, False)`` — the query is answered from the
    build, uncached — rather than raising: a *read* must never fail because its cache couldn't be
    refreshed (design law #5), and the caller is a hook or a `context` query whose answer is already in
    hand. It stays silent here (design law #4); the write seams carry the guidance.
    """
    from yigraf import counters  # local: avoid an import cycle at module load
    from yigraf.extract import build_graph

    def timed(name: str):
        return budget.phase(name) if budget is not None else contextlib.nullcontext()

    root = Path(root)
    db = db_path(root)
    with timed("graph.fingerprint"):
        stored, governed = stored_meta(db)
        # Only when there is a stored fingerprint to compare against: with no view yet the walk cannot
        # change the outcome, and the original short-circuit skipped it for exactly that reason.
        current = (None if stored is None else
                   fingerprint if fingerprint is not None else
                   source_fingerprint(root, config, governed))
    if stored is not None and stored == current:
        with timed("graph.load"):
            graph = load(db)
        if graph is not None:
            # Named even though it is inert at the default floor of 0: an unnamed stretch inside a timed
            # phase is an unattributed residual, and this one makes git calls across every memory path, so
            # it is exactly the term that would silently absorb the difference on a store that arms it.
            if int(config.get("maturity_survival_floor", 0)) > 0:
                with timed("graph.maturity"):
                    counters.apply_maturity(graph, root, config)
            return graph, True
    with timed("graph.build"):
        graph, _ = build_graph(root, config)
    with timed("graph.materialize"):
        # The pre-build digest is reusable only if the build found the same governed loci it covered.
        reuse = current if current is not None and governed_file_paths(graph) == governed else None
        _materialize_or_flag(graph, root, config, fingerprint=reuse)
    return graph, False
