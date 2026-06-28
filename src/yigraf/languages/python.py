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
        return Discovery(symbols=symbols, module_boundaries=module_boundaries, imports=_imports(root),
                         inherits=_inherits(symbols, root) or None)

    def add_inheritance_edges(self, graph, file_inherits: dict[str, list[list]],
                              file_sources: dict[str, str], root) -> None:
        """Resolve ``class C(Base)`` to ``C --inherits--> sym:<base's module>#Base`` (import-aware).

        ``module_spec == ""`` means the base wasn't imported → look in the subclass's own file. Otherwise
        the base name was bound by ``from <spec> import Base`` and ``spec`` resolves (absolute or relative,
        via :func:`_resolve_import`) to the defining file. An edge is added only when that base *symbol*
        actually exists — no phantom node, no edge to an unresolved/external base (precision over recall).
        """
        module_to_file = _module_path_map(file_sources)
        for file_id in sorted(file_inherits):
            importer = file_sources.get(file_id, "")
            for subclass_id, spec, base_name in file_inherits[file_id]:
                target_file = file_id if spec == "" else _resolve_import(spec, importer, module_to_file)
                if target_file is None:
                    continue
                base_id = f"sym:{target_file[len('file:'):]}#{base_name}"
                if base_id in graph and base_id != subclass_id:
                    graph.add_edge(subclass_id, base_id, **edge("inherits"))

    def call_edges(self, symbols: list[Symbol], pid: str, symbol_ids: set[str]) -> list[tuple[str, str]]:
        return _call_edges(symbols, pid, symbol_ids)

    def add_import_edges(self, graph, file_imports: dict[str, list[str]],
                         file_sources: dict[str, str], root) -> None:
        module_to_file = _module_path_map(file_sources)
        for file_id in sorted(file_imports):
            importer = file_sources.get(file_id, "")
            for module in file_imports[file_id]:
                target = _resolve_import(module, importer, module_to_file)
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
    """Module references imported at file top level (sorted).

    Absolute imports are recorded as dotted names (``os``, ``pkg.mod``); **relative** imports keep their
    leading dots (``.base``, ``..astnorm``, ``.sub``) so :func:`_resolve_relative` can later resolve them
    against the *importing* file's package — the file node alone can't, since ``.`` means different
    modules in different packages. (#16 — relative imports were skipped entirely in v0.)
    """
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
            if module is None:
                continue
            if module.type == "dotted_name":
                out.add(module.text.decode())
            elif module.type == "relative_import":
                out.update(_relative_import_specs(stmt, module))
    return sorted(out)


def _relative_import_specs(stmt: Node, relative_node: Node) -> set[str]:
    """Dot-prefixed specs for one ``from .… import …`` statement.

    ``from .base import X`` / ``from ..pkg.mod import Y`` → the relative module carries its own name, so
    the spec is the whole node text (``.base``, ``..pkg.mod``). ``from . import a, b`` has only dots for
    the module, so each *imported name* is a sibling submodule of the current package → ``.a``, ``.b``.
    """
    text = relative_node.text.decode()  # ".", "..", ".base", "..pkg.mod"
    dots = len(text) - len(text.lstrip("."))
    if len(text) > dots:  # the relative module already names a submodule
        return {text}
    specs: set[str] = set()  # bare dots: targets are the imported names, joined onto the dots
    for child in stmt.named_children:
        if child is relative_node:
            continue
        if child.type == "dotted_name":
            specs.add(text + child.text.decode())
        elif child.type == "aliased_import":
            name = child.child_by_field_name("name")
            if name is not None and name.type == "dotted_name":
                specs.add(text + name.text.decode())
    return specs


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
# Inheritance discovery (class bases → import-resolved cross-file)
# --------------------------------------------------------------------------------------------------


def _inherits(symbols: list[Symbol], root: Node) -> list[list]:
    """Per-class inheritance requests ``[subclass_id, module_spec, base_name]`` (resolved cross-file later).

    A base bound by ``from <M> import Base`` carries ``M`` as the spec (resolves to that module); an
    unbound base gets ``""`` (look in the same file). Dotted bases (``mod.Base``) and keyword args
    (``metaclass=``) are skipped — only simple-identifier bases resolve precisely (no-false-edge policy)."""
    bindings = _from_bindings(root)
    out: list[list] = []
    for s in symbols:
        if s.kind != "class":
            continue
        for base in _base_names(s.defn):
            spec, name = bindings.get(base, ("", base))
            out.append([s.id, spec, name])
    return out


def _base_names(class_defn: Node) -> list[str]:
    """Simple-identifier base classes (skips dotted ``mod.Base`` and keyword args like ``metaclass=``)."""
    supers = class_defn.child_by_field_name("superclasses")  # argument_list, or None for `class C:`
    if supers is None:
        return []
    return [c.text.decode() for c in supers.named_children if c.type == "identifier"]


def _from_bindings(root: Node) -> dict[str, tuple[str, str]]:
    """``from <M> import N [as L]`` → ``{local_name: (module_spec, original_name)}`` for base resolution.

    ``module_spec`` keeps relative dots (``.base``). Bare ``from . import sub`` binds a *submodule* (not a
    class), so it's skipped; plain ``import pkg`` isn't captured either — both only yield dotted bases,
    which :func:`_base_names` already drops."""
    bindings: dict[str, tuple[str, str]] = {}
    for stmt in root.children:
        if stmt.type != "import_from_statement":
            continue
        module = stmt.child_by_field_name("module_name")
        if module is None:
            continue
        if module.type == "dotted_name":
            spec = module.text.decode()
        elif module.type == "relative_import":
            spec = module.text.decode()
            if spec.lstrip(".") == "":  # bare dots → submodule import, not a class binding
                continue
        else:
            continue
        for child in stmt.named_children:
            if child is module:
                continue
            if child.type == "dotted_name":
                bindings[child.text.decode()] = (spec, child.text.decode())
            elif child.type == "aliased_import":
                name = child.child_by_field_name("name")
                alias = child.child_by_field_name("alias")
                if name is not None and alias is not None:
                    bindings[alias.text.decode()] = (spec, name.text.decode())
    return bindings


# --------------------------------------------------------------------------------------------------
# Import-edge resolution (Python module system)
# --------------------------------------------------------------------------------------------------


def _resolve_import(module: str, importer_relpath: str, module_to_file: dict[str, str]) -> str | None:
    """The file id ``module`` resolves to — handling both absolute and relative specs.

    Absolute: a direct lookup. Relative (``.base``): resolved to absolute module(s) against the importer's
    package first (a dotted name can't be relative). First match in sorted order wins (determinism)."""
    if not module.startswith("."):
        return module_to_file.get(module.casefold())
    for absolute in sorted(_resolve_relative(module, importer_relpath)):
        target = module_to_file.get(absolute.casefold())
        if target is not None:
            return target
    return None


def _resolve_relative(spec: str, importer_relpath: str) -> set[str]:
    """Absolute dotted module(s) a relative ``spec`` names, from the importer's path.

    ``L`` leading dots drop ``L`` trailing components off the importer's own module (1 dot = the importer's
    package, 2 = its parent, …), then the tail is appended. Resolved against every module candidate of the
    importer (so ``src``-layout works), e.g. ``.base`` from ``src/yigraf/x.py`` → ``yigraf.base`` (and
    ``src.yigraf.base``). Over-relative specs (more dots than the path is deep) yield nothing."""
    level = len(spec) - len(spec.lstrip("."))
    if level == 0:
        return set()
    tail = spec[level:]
    out: set[str] = set()
    for base in _module_candidates(importer_relpath):
        parts = base.split(".")
        if level > len(parts):
            continue
        abs_parts = parts[:-level] + (tail.split(".") if tail else [])
        if abs_parts:
            out.add(".".join(abs_parts))
    return out


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
