"""Python structure extractor (tree-sitter-python).

The reference implementation of the language framework: it reproduces yigraf's original Python-only
extractor exactly — same node ids, content hashes, ``contains``/``calls`` edges, and import-edge
resolution — so the M1 "no-change rebuild ⇒ byte-identical graph.json" done-test still holds.

Scope (docs/m1-notes.md §2): top-level functions, classes, and methods (functions directly inside a
class body). Nested/local defs, comprehensions, and lambdas ride the enclosing symbol's hash.
"""
from __future__ import annotations

import tree_sitter_python as tsp
from tree_sitter import Language, Node

from yigraf.languages.base import Discovery, LanguageExtractor, Symbol, edge

PY_LANGUAGE = Language(tsp.language())


class PythonExtractor(LanguageExtractor):
    name = "python"
    extensions = (".py",)
    language_label = "python"
    # astnorm_spec defaults to Python's sets (see base.AstnormSpec) → byte-identical anchors.

    def ts_language(self) -> Language:
        return PY_LANGUAGE

    def discover(self, root: Node, pid: str, module_id: str, source: bytes) -> Discovery:
        symbols = _discover_symbols(root, pid, module_id)
        # Top-level def/class statements mask their bodies in the module hash (methods are masked
        # one level down, via each class's own boundaries).
        module_boundaries = {s.stmt.id: s.name for s in symbols if s.container == module_id}
        return Discovery(symbols=symbols, module_boundaries=module_boundaries, imports=_imports(root))

    def call_edges(self, symbols: list[Symbol], pid: str, symbol_ids: set[str]) -> list[tuple[str, str]]:
        return _call_edges(symbols, pid, symbol_ids)

    def add_import_edges(self, graph, file_imports: dict[str, list[str]],
                         file_sources: dict[str, str], root) -> None:
        module_to_file = _module_path_map(file_sources)
        for file_id in sorted(file_imports):
            for module in file_imports[file_id]:
                target = module_to_file.get(module.casefold())
                if target is not None and target != file_id:
                    graph.add_edge(file_id, target, **edge("imports"))


# --------------------------------------------------------------------------------------------------
# Symbol discovery
# --------------------------------------------------------------------------------------------------


def _discover_symbols(root: Node, pid: str, module_id: str) -> list[Symbol]:
    """Find every extracted symbol (top-level defs/classes + their methods) in declaration order."""
    out: list[Symbol] = []
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
                Symbol(
                    id=f"sym:{pid}#{name}", kind="class", name=name, qualname=name,
                    stmt=stmt, defn=defn, container=module_id, enclosing_class=None,
                    boundaries=boundaries,
                )
            )
            out.extend(methods)
        else:
            out.append(
                Symbol(
                    id=f"sym:{pid}#{name}", kind="function", name=name, qualname=name,
                    stmt=stmt, defn=defn, container=module_id, enclosing_class=None,
                )
            )
    return out


def _discover_methods(class_defn: Node, pid: str, class_name: str) -> list[Symbol]:
    """Functions declared directly in a class body — the only nested symbols extracted in v0."""
    out: list[Symbol] = []
    body = class_defn.child_by_field_name("body")
    for stmt in body.children if body is not None else []:
        defn = _definition(stmt)
        if defn is None or defn.type != "function_definition":
            continue
        name = _name(defn)
        if name is None:
            continue
        out.append(
            Symbol(
                id=f"sym:{pid}#{class_name}.{name}", kind="method", name=name,
                qualname=f"{class_name}.{name}", stmt=stmt, defn=defn,
                container=f"sym:{pid}#{class_name}", enclosing_class=class_name,
            )
        )
    return out


# --------------------------------------------------------------------------------------------------
# Call resolution
# --------------------------------------------------------------------------------------------------


def _call_edges(symbols: list[Symbol], pid: str, symbol_ids: set[str]) -> list[tuple[str, str]]:
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


# --------------------------------------------------------------------------------------------------
# Imports
# --------------------------------------------------------------------------------------------------


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


# --------------------------------------------------------------------------------------------------
# Import-edge resolution (Python module system)
# --------------------------------------------------------------------------------------------------


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
