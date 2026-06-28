"""Structure extraction: a repo's source → the structure family of the yigraf graph.

This module is the **orchestration layer**. Per-language knowledge lives in :mod:`yigraf.languages`
(a small framework: a declarative or bespoke extractor per language, dispatched by file suffix).
Here we walk the repo, run the right extractor per file through a per-file SHA cache
(:mod:`yigraf.cache`), let each language resolve its own import edges, and project the authored
intent / plan / memory artifacts on top. Extraction is deterministic, so a no-change rebuild
reproduces a byte-identical ``graph.json`` (the M1 done-test) — for Python the framework reproduces
the original output exactly.

Scope is gated by the workspace ``languages`` config (``docs/m1-notes.md`` §2). v0 ships Python and
Go extractors; the other core grammars are bundled and light up as their extractors land.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import networkx as nx

from yigraf import artifacts, counters, drift, memory
from yigraf.astnorm import ANCHOR_ALGO
from yigraf.cache import StructureCache, file_sha
from yigraf.graph import empty_graph
from yigraf.languages import (
    FileProjection,
    all_extractors,
    available_extractors,
    extension_map,
    extractor_for_path,
)
from yigraf.languages.python import PY_LANGUAGE as _PY_LANGUAGE  # noqa: F401 (back-compat re-export)

__all__ = ["FileProjection", "BuildStats", "build_graph", "extract_file", "symbol_content_hash"]


@dataclass
class BuildStats:
    """How a build broke down across files (for the CLI and the cache-hit done-test)."""

    files: int = 0
    extracted: int = 0
    cached: int = 0


def extract_file(relpath: str, source: bytes, parser=None) -> FileProjection:
    """Project a single file via the extractor for its suffix (back-compat dispatch).

    The optional ``parser`` argument is accepted for compatibility with older call sites and tests;
    each extractor manages its own parser, so it is ignored. Unknown suffixes yield an empty
    projection.
    """
    extractor = extractor_for_path(relpath, all_extractors())
    if extractor is None:
        return FileProjection(nodes={}, edges=[])
    return extractor.extract_file(relpath, source)


def build_graph(root: Path, config: dict) -> tuple[nx.DiGraph, BuildStats]:
    """Extract the structure graph for the repo at ``root``, using the on-disk cache.

    Walks every source file whose suffix maps to an *enabled, available* language extractor, reusing
    unchanged files from ``yigraf/cache/structure.json`` and re-parsing the rest. Then each language
    resolves its own intra-repo import edges, and the authored intent/plan and memory artifacts (and
    their cross-family edges) are projected on top — re-anchoring renames and recomputing counters.
    """
    root = Path(root)
    cache_path = root / "yigraf" / "cache" / "structure.json"
    cache = StructureCache.load(cache_path)
    ignore_dirs = {p.rstrip("/").strip() for p in config.get("ignore", [])}

    extractors = available_extractors(config)
    ext_map = extension_map(extractors)

    graph = empty_graph()
    graph.graph["anchor_algo"] = ANCHOR_ALGO
    stats = BuildStats()
    file_imports: dict[str, list[str]] = {}  # file_id -> imported module/package targets
    file_inherits: dict[str, list[list]] = {}  # file_id -> [subclass_id, module_spec, base_name] requests
    file_sources: dict[str, str] = {}  # file_id -> source_file relpath

    relpaths = _iter_source_files(root, ignore_dirs, set(ext_map))
    for relpath in relpaths:
        extractor = ext_map[PurePosixPath(relpath).suffix]
        data = (root / relpath).read_bytes()
        sha = file_sha(data)
        projection = cache.get(relpath, sha)
        if projection is None:
            projection = extractor.extract_file(relpath, data)
            cache.put(relpath, sha, projection)
            stats.extracted += 1
        else:
            stats.cached += 1
        stats.files += 1

        for node_id, attrs in projection.nodes.items():
            graph.add_node(node_id, **attrs)
            if attrs.get("kind") == "file":
                file_imports[node_id] = attrs.get("imports", [])
                file_sources[node_id] = attrs["source_file"]
                if attrs.get("inherits"):
                    file_inherits[node_id] = attrs["inherits"]
        for src, dst, attrs in projection.edges:
            graph.add_edge(src, dst, **attrs)

    # Each language resolves import edges only against its own files (suffixes don't cross-resolve).
    for extractor in extractors:
        exts = set(extractor.extensions)
        lang_sources = {fid: src for fid, src in file_sources.items()
                        if PurePosixPath(src).suffix in exts}
        lang_imports = {fid: imp for fid, imp in file_imports.items() if fid in lang_sources}
        extractor.add_import_edges(graph, lang_imports, lang_sources, root)
        lang_inherits = {fid: inh for fid, inh in file_inherits.items() if fid in lang_sources}
        extractor.add_inheritance_edges(graph, lang_inherits, lang_sources, root)

    artifacts.project_into(graph, root)
    memory.project_into(graph, root)  # memory nodes + serves/concerns/supersedes edges (M7)
    drift.resolve_renames(graph)  # re-anchor moved/renamed implements + concerns targets (M3/M7)
    memory.recompute_counters(graph)  # edge-derived superseded_in/out for the relevance prior
    counters.apply_maturity(graph, root, config, cache=cache)  # git-derived working/settled, HEAD-cached (R2)

    cache.prune(set(relpaths))
    cache.save(cache_path)
    return graph, stats


def symbol_content_hash(root: Path, symbol_id: str, config: dict) -> str | None:
    """The current ``astnorm`` ``content_hash`` of ``symbol_id``, or ``None`` if it doesn't resolve.

    Parses only the file the locator names (``sym:<path>#<name>``) via that file's language extractor,
    rather than the whole repo, so ``yigraf link`` can stamp an anchor cheaply (docs/m2-notes.md §4).
    """
    if not symbol_id.startswith("sym:"):
        return None
    path_cf = symbol_id[len("sym:") :].split("#", 1)[0]
    ignore_dirs = {p.rstrip("/").strip() for p in config.get("ignore", [])}
    extractors = available_extractors(config)
    ext_map = extension_map(extractors)
    for relpath in _iter_source_files(Path(root), ignore_dirs, set(ext_map)):
        if PurePosixPath(relpath).as_posix().casefold() != path_cf:
            continue
        extractor = ext_map[PurePosixPath(relpath).suffix]
        return extractor.content_hash_of(symbol_id, relpath, (Path(root) / relpath).read_bytes())
    return None


def _iter_source_files(root: Path, ignore_dirs: set[str], extensions: set[str]) -> list[str]:
    """Sorted POSIX relpaths of files under ``root`` with a handled suffix, skipping ignored dirs.

    An ignore entry prunes a directory either by **bare name at any depth** (``origins``, ``.git``) or by
    **exact repo-relative path prefix** (``scripts/eval/runs``) — matching the config's documented
    "path prefixes" intent (a bare name is just the one-segment case).
    """
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        reldir = Path(dirpath).relative_to(root).as_posix()
        prefix = "" if reldir == "." else reldir + "/"
        dirnames[:] = sorted(
            d for d in dirnames if d not in ignore_dirs and (prefix + d) not in ignore_dirs
        )
        for filename in sorted(filenames):
            if PurePosixPath(filename).suffix in extensions:
                rel = (Path(dirpath) / filename).relative_to(root).as_posix()
                out.append(rel)
    return out
