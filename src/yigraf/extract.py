"""Structure extraction: a Python repo's source → the structure family of the yigraf graph.

tree-sitter parses each ``.py`` file into ``file`` / ``module`` / ``symbol`` nodes and
``contains`` / ``calls`` / ``imports`` edges, stamping every symbol (and the module) with an
AST-normalized ``content_hash`` (the drift anchor — :mod:`yigraf.astnorm`). A per-file SHA cache
(:mod:`yigraf.cache`) skips re-parsing unchanged files; extraction is otherwise deterministic, so a
no-change rebuild reproduces a byte-identical ``graph.json`` (the M1 done-test).

Scope is pinned in ``docs/m1-notes.md`` §2: Python only; the extracted symbols are top-level
functions, classes, and methods (functions directly inside a class body). Nested/local defs,
comprehensions, and lambdas are *not* separate nodes — their tokens ride the enclosing symbol's hash.
Locator ids casefold the *path* for stability on case-insensitive filesystems while preserving the
symbol *name* exactly (Python is case-sensitive); case-insensitive matching is a retrieval concern.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import networkx as nx
import tree_sitter_python as tsp
from tree_sitter import Language, Node, Parser

from yigraf import artifacts, drift
from yigraf.astnorm import ANCHOR_ALGO, content_hash
from yigraf.cache import StructureCache, file_sha
from yigraf.graph import empty_graph

FAMILY = "structure"
LANGUAGE = "python"
CONF_EXTRACTED = "EXTRACTED"

_PY_LANGUAGE = Language(tsp.language())


@dataclass
class FileProjection:
    """One file's contribution to the graph: structure nodes + intra-file edges (cacheable)."""

    nodes: dict[str, dict]
    #: edges as ``[source, target, attrs]`` (lists, not tuples, so they JSON round-trip identically)
    edges: list[list]

    def to_cache(self) -> dict[str, Any]:
        return {"nodes": self.nodes, "edges": self.edges}

    @classmethod
    def from_cache(cls, entry: dict[str, Any]) -> "FileProjection":
        return cls(nodes=entry["nodes"], edges=entry["edges"])


@dataclass
class BuildStats:
    """How a build broke down across files (for the CLI and the cache-hit done-test)."""

    files: int = 0
    extracted: int = 0
    cached: int = 0


# --------------------------------------------------------------------------------------------------
# Per-file extraction
# --------------------------------------------------------------------------------------------------


def extract_file(relpath: str, source: bytes, parser: Parser) -> FileProjection:
    """Project a single Python file into structure nodes + intra-file ``contains``/``calls`` edges.

    ``imports`` are recorded as a sorted attribute on the file node here; resolving them into edges
    needs the whole repo's module map and happens in :func:`build_graph`.
    """
    rel = PurePosixPath(relpath).as_posix()
    pid = rel.casefold()  # path casefolded for id stability; symbol names stay exact
    file_id = f"file:{pid}"
    module_id = f"module:{pid}"

    root = parser.parse(source).root_node
    nodes: dict[str, dict] = {}
    edges: list[list] = []

    # Discover symbols first so the module/class hashes know their nested-symbol boundaries.
    symbols = _discover_symbols(root, pid, module_id)
    top_boundaries = {s.stmt.id: s.name for s in symbols if s.container == module_id}

    module_hash = content_hash(root, source, top_boundaries)
    nodes[module_id] = _struct_node("module", rel, rel, module_hash, _range(root))
    nodes[file_id] = _struct_node("file", rel, rel, module_hash, _range(root))
    nodes[file_id]["imports"] = _imports(root)
    edges.append([file_id, module_id, _edge("contains")])

    symbol_ids = {s.id for s in symbols}
    for s in symbols:
        h = content_hash(s.stmt, source, s.boundaries, exclude=_own_name_ids(s.defn))
        nodes[s.id] = _struct_node(s.kind, s.qualname, rel, h, _range(s.stmt))
        signature = _signature(s.defn, source)
        if signature is not None:
            nodes[s.id]["signature"] = signature  # for "locator + signature, not source" render (M4)
        edges.append([s.container, s.id, _edge("contains")])

    for src, dst in _call_edges(symbols, pid, symbol_ids):
        edges.append([src, dst, _edge("calls")])

    return FileProjection(nodes=nodes, edges=edges)


@dataclass
class _Symbol:
    """An extracted symbol and the facts needed to node-ify, hash, and resolve calls within it."""

    id: str
    kind: str  # function | class | method
    name: str  # local name (the marker name in a parent's hash)
    qualname: str  # graph label, e.g. "C.m"
    stmt: Node  # the statement node as it appears in its parent (decorated_definition if decorated)
    defn: Node  # the unwrapped function_definition / class_definition
    container: str  # id of the node that `contains` this one
    enclosing_class: str | None  # local class name, for resolving `self.m()` calls
    boundaries: dict[int, str]  # nested extracted symbols → marker names (empty for fn/method)


def _discover_symbols(root: Node, pid: str, module_id: str) -> list[_Symbol]:
    """Find every extracted symbol (top-level defs/classes + their methods) in declaration order."""
    out: list[_Symbol] = []
    for stmt in root.children:
        defn = _definition(stmt)
        if defn is None:
            continue
        name = _name(defn)
        if name is None:
            continue
        if defn.type == "class_definition":
            methods = _discover_methods(defn, pid, name)
            boundaries = {m.stmt.id: m.name for m in methods}
            out.append(
                _Symbol(
                    id=f"sym:{pid}#{name}", kind="class", name=name, qualname=name,
                    stmt=stmt, defn=defn, container=module_id, enclosing_class=None,
                    boundaries=boundaries,
                )
            )
            out.extend(methods)
        else:
            out.append(
                _Symbol(
                    id=f"sym:{pid}#{name}", kind="function", name=name, qualname=name,
                    stmt=stmt, defn=defn, container=module_id, enclosing_class=None,
                    boundaries={},
                )
            )
    return out


def _discover_methods(class_defn: Node, pid: str, class_name: str) -> list[_Symbol]:
    """Functions declared directly in a class body — the only nested symbols extracted in v0."""
    out: list[_Symbol] = []
    body = class_defn.child_by_field_name("body")
    for stmt in body.children if body is not None else []:
        defn = _definition(stmt)
        if defn is None or defn.type != "function_definition":
            continue
        name = _name(defn)
        if name is None:
            continue
        out.append(
            _Symbol(
                id=f"sym:{pid}#{class_name}.{name}", kind="method", name=name,
                qualname=f"{class_name}.{name}", stmt=stmt, defn=defn,
                container=f"sym:{pid}#{class_name}", enclosing_class=class_name, boundaries={},
            )
        )
    return out


def _call_edges(symbols: list[_Symbol], pid: str, symbol_ids: set[str]) -> list[tuple[str, str]]:
    """Resolve intra-file calls: bare names to top-level functions, ``self.m()`` to sibling methods.

    External / unresolvable calls are dropped rather than stored as phantom nodes. Returns a sorted,
    de-duplicated edge list (a caller→callee pair is recorded once regardless of call-site count).
    """
    found: set[tuple[str, str]] = set()
    for s in symbols:
        for call in _collect_calls(s.stmt, s.boundaries, []):
            target = _resolve_call(call, pid, s.enclosing_class, symbol_ids)
            if target is not None and target != s.id:
                found.add((s.id, target))
    return sorted(found)


def _collect_calls(node: Node, boundaries: dict[int, str], out: list[Node]) -> list[Node]:
    """Collect ``call`` nodes belonging to this symbol (not descending into nested symbols)."""
    if node.id in boundaries:
        return out  # a nested extracted symbol owns its own calls
    if node.type == "call":
        out.append(node)
    for child in node.children:
        _collect_calls(child, boundaries, out)
    return out


def _resolve_call(call: Node, pid: str, enclosing_class: str | None, symbol_ids: set[str]) -> str | None:
    fn = call.child_by_field_name("function")
    if fn is None:
        return None
    if fn.type == "identifier":
        candidate = f"sym:{pid}#{fn.text.decode()}"
        return candidate if candidate in symbol_ids else None
    if fn.type == "attribute" and enclosing_class is not None:
        obj = fn.child_by_field_name("object")
        attr = fn.child_by_field_name("attribute")
        if obj is not None and attr is not None and obj.type == "identifier" and obj.text == b"self":
            candidate = f"sym:{pid}#{enclosing_class}.{attr.text.decode()}"
            return candidate if candidate in symbol_ids else None
    return None


def _imports(root: Node) -> list[str]:
    """Dotted module names imported at file top level (sorted). Relative imports skipped in v0."""
    out: set[str] = set()
    for stmt in root.children:
        if stmt.type == "import_statement":
            for child in stmt.named_children:
                if child.type == "dotted_name":
                    out.add(child.text.decode())
                elif child.type == "aliased_import":
                    name = child.child_by_field_name("name")
                    if name is not None and name.type == "dotted_name":
                        out.add(name.text.decode())
        elif stmt.type == "import_from_statement":
            module = stmt.child_by_field_name("module_name")
            if module is not None and module.type == "dotted_name":
                out.add(module.text.decode())
    return sorted(out)


def _definition(stmt: Node) -> Node | None:
    """The function/class definition a top-level statement declares, unwrapping any decorators."""
    if stmt.type in ("function_definition", "class_definition"):
        return stmt
    if stmt.type == "decorated_definition":
        return stmt.child_by_field_name("definition")
    return None


def _name(defn: Node) -> str | None:
    name = defn.child_by_field_name("name")
    return name.text.decode() if name is not None else None


def _own_name_ids(defn: Node) -> frozenset[int]:
    """The node id of a def's own name identifier — excluded from its hash so renames re-anchor."""
    name = defn.child_by_field_name("name")
    return frozenset({name.id}) if name is not None else frozenset()


def _signature(defn: Node, source: bytes) -> str | None:
    """The one-line declaration (``def f(a) -> b:`` / ``class C(Base):``) for compact rendering.

    The text from the def keyword to the body, whitespace-collapsed — decorators excluded (``defn``
    is the unwrapped definition). Returns ``None`` if the node has no body field.
    """
    body = defn.child_by_field_name("body")
    if body is None:
        return None
    raw = source[defn.start_byte : body.start_byte].decode("utf-8", "surrogatepass")
    return " ".join(raw.split())


def _range(node: Node) -> list[int]:
    start, end = node.start_point, node.end_point
    return [start.row, start.column, end.row, end.column]


def _struct_node(kind: str, label: str, source_file: str, content_hash_: str, source_range: list[int]) -> dict:
    return {
        "family": FAMILY,
        "kind": kind,
        "label": label,
        "language": LANGUAGE,
        "confidence": CONF_EXTRACTED,
        "content_hash": content_hash_,
        "source_file": source_file,
        "source_range": source_range,
    }


def _edge(relation: str) -> dict:
    return {"relation": relation, "confidence": CONF_EXTRACTED}


# --------------------------------------------------------------------------------------------------
# Whole-repo build
# --------------------------------------------------------------------------------------------------


def build_graph(root: Path, config: dict) -> tuple[nx.DiGraph, BuildStats]:
    """Extract the structure graph for the repo at ``root`` (Python only), using the on-disk cache.

    Reuses unchanged files from ``yigraf/cache/structure.json`` and re-parses the rest, then resolves
    intra-repo ``imports`` edges across the full file set, and finally projects the authored
    intent/plan artifacts (and their cross-family edges) on top. The memory family arrives later.
    """
    root = Path(root)
    cache_path = root / "yigraf" / "cache" / "structure.json"
    cache = StructureCache.load(cache_path)
    ignore_dirs = {p.rstrip("/").strip() for p in config.get("ignore", [])}

    parser = Parser(_PY_LANGUAGE)
    graph = empty_graph()
    graph.graph["anchor_algo"] = ANCHOR_ALGO
    stats = BuildStats()
    file_imports: dict[str, list[str]] = {}  # file_id -> imported dotted modules
    file_sources: dict[str, str] = {}  # file_id -> source_file relpath

    relpaths = _iter_python_files(root, ignore_dirs)
    for relpath in relpaths:
        data = (root / relpath).read_bytes()
        sha = file_sha(data)
        projection = cache.get(relpath, sha)
        if projection is None:
            projection = extract_file(relpath, data, parser)
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
        for src, dst, attrs in projection.edges:
            graph.add_edge(src, dst, **attrs)

    _add_import_edges(graph, file_imports, file_sources)
    artifacts.project_into(graph, root)
    drift.resolve_renames(graph)  # re-anchor moved/renamed implements targets in-memory (M3)

    cache.prune(set(relpaths))
    cache.save(cache_path)
    return graph, stats


def symbol_content_hash(root: Path, symbol_id: str, config: dict) -> str | None:
    """The current ``astnorm`` ``content_hash`` of ``symbol_id``, or ``None`` if it doesn't resolve.

    Parses only the file the locator names (``sym:<path>#<name>``) rather than the whole repo, so
    ``yigraf link`` can stamp an anchor cheaply against working-tree content (docs/m2-notes.md §4).
    """
    if not symbol_id.startswith("sym:"):
        return None
    path_cf = symbol_id[len("sym:") :].split("#", 1)[0]
    ignore_dirs = {p.rstrip("/").strip() for p in config.get("ignore", [])}
    parser = Parser(_PY_LANGUAGE)
    for relpath in _iter_python_files(Path(root), ignore_dirs):
        if PurePosixPath(relpath).as_posix().casefold() != path_cf:
            continue
        projection = extract_file(relpath, (Path(root) / relpath).read_bytes(), parser)
        node = projection.nodes.get(symbol_id)
        return node.get("content_hash") if node else None
    return None


def _iter_python_files(root: Path, ignore_dirs: set[str]) -> list[str]:
    """Sorted POSIX relpaths of ``.py`` files under ``root``, skipping ignored directories."""
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in ignore_dirs)
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                rel = (Path(dirpath) / filename).relative_to(root).as_posix()
                out.append(rel)
    return out


def _add_import_edges(graph: nx.DiGraph, file_imports: dict[str, list[str]], file_sources: dict[str, str]) -> None:
    """Add ``imports`` edges between files for intra-repo (resolvable) imports only.

    External imports (stdlib, third-party) stay recorded on the file node's ``imports`` attribute but
    produce no edge — adding one would conjure a phantom node for code we don't index.
    """
    module_to_file = _module_path_map(file_sources)
    for file_id in sorted(file_imports):
        for module in file_imports[file_id]:
            target = module_to_file.get(module.casefold())
            if target is not None and target != file_id:
                graph.add_edge(file_id, target, **_edge("imports"))


def _module_path_map(file_sources: dict[str, str]) -> dict[str, str]:
    """Map each importable dotted module path (casefolded) to its file node id.

    Handles ``src``-layout by also offering the ``src``-stripped path, and packages by mapping
    ``pkg/__init__.py`` to ``pkg``. On collision the first id in sorted order wins (determinism).
    """
    mapping: dict[str, str] = {}
    for file_id in sorted(file_sources):
        for candidate in _module_candidates(file_sources[file_id]):
            mapping.setdefault(candidate.casefold(), file_id)
    return mapping


def _module_candidates(relpath: str) -> set[str]:
    stem = relpath[:-3] if relpath.endswith(".py") else relpath
    parts = stem.split("/")
    out: set[str] = set()

    def add(segs: list[str]) -> None:
        if segs and segs[-1] == "__init__":
            segs = segs[:-1]
        if segs:
            out.add(".".join(segs))

    add(parts)
    if parts and parts[0] == "src":
        add(parts[1:])
    return out
