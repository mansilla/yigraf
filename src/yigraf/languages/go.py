"""Go structure extractor (tree-sitter-go).

Go doesn't fit the class/method shape the declarative path assumes — there are no classes; methods
bind to a *receiver type* and are declared as top-level siblings of the type, and types live in
``type_declaration``/``type_spec``. So this is a bespoke extractor (as Graphify's Go support is too),
implementing :meth:`discover` directly while reusing the base orchestration for hashing, signatures,
``contains`` edges, and the :class:`FileProjection`.

Mapping (file-scoped ids, consistent with the Python extractor):
- ``function_declaration`` → ``sym:<path>#Name`` (kind ``function``), contained by the module.
- ``method_declaration``   → ``sym:<path>#Recv.Name`` (kind ``method``); contained by the receiver
  type node when that type is declared in the *same file*, else by the module.
- ``type_declaration``/``type_spec`` → ``sym:<path>#Name`` (kind ``type``), contained by the module.

Imports are recorded on the file node; resolving Go import *edges* (needs the ``go.mod`` module path
to map an import path to a package directory) is a documented follow-up — symbols, calls, and drift
are the token-win that lands now. astnorm uses empty knobs: Go has no docstrings and no quote-style
ambiguity, so neither normalization applies (comments are still dropped generically).
"""
from __future__ import annotations

from pathlib import Path

from tree_sitter import Language, Node

from yigraf.languages.base import AstnormSpec, Discovery, LanguageExtractor, Symbol, edge

#: Go has neither docstrings nor quote-style ambiguity, so every astnorm knob is empty.
GO_ASTNORM = AstnormSpec(quote_tokens=frozenset(), body_containers=frozenset(),
                         docstring_types=frozenset())


class GoExtractor(LanguageExtractor):
    name = "go"
    extensions = (".go",)
    language_label = "go"
    astnorm_spec = GO_ASTNORM

    def __init__(self) -> None:
        super().__init__()
        self._lang: Language | None = None

    def ts_language(self) -> Language:
        if self._lang is None:
            import tree_sitter_go as tsgo  # lazy: optional grammar, only loaded when Go is enabled

            self._lang = Language(tsgo.language())
        return self._lang

    def discover(self, root: Node, pid: str, module_id: str, source: bytes) -> Discovery:
        type_names = _declared_type_names(root)
        symbols: list[Symbol] = []

        for child in root.children:
            t = child.type
            if t == "function_declaration":
                name = _field_text(child, "name")
                if not name:
                    continue
                symbols.append(
                    Symbol(id=f"sym:{pid}#{name}", kind="function", name=name, qualname=name,
                           stmt=child, defn=child, container=module_id)
                )
            elif t == "method_declaration":
                name = _field_text(child, "name")
                if not name:
                    continue
                recv = _receiver_type(child)
                if recv:
                    sym_id = f"sym:{pid}#{recv}.{name}"
                    qualname = f"{recv}.{name}"
                    container = f"sym:{pid}#{recv}" if recv in type_names else module_id
                else:
                    sym_id, qualname, container = f"sym:{pid}#{name}", name, module_id
                symbols.append(
                    Symbol(id=sym_id, kind="method", name=name, qualname=qualname,
                           stmt=child, defn=child, container=container)
                )
            elif t == "type_declaration":
                for spec in child.children:
                    if spec.type != "type_spec":
                        continue
                    name = _field_text(spec, "name")
                    if not name:
                        continue
                    symbols.append(
                        Symbol(id=f"sym:{pid}#{name}", kind="type", name=name, qualname=name,
                               stmt=spec, defn=spec, container=module_id)
                    )

        # Every extracted declaration is a top-level node, so masking each one's body keeps the
        # module hash sensitive to *which* declarations exist, not to their bodies (qualname markers
        # avoid a func/method name collision).
        module_boundaries = {s.stmt.id: s.qualname for s in symbols}
        # Struct/interface embedding is Go's inheritance. module_spec is always "" — Go resolution is
        # package-aware (same directory), done in add_inheritance_edges, not import-aware.
        inherits = [[s.id, "", emb] for s in symbols if s.kind == "type" for emb in _embeds(s.defn)]
        return Discovery(symbols=symbols, module_boundaries=module_boundaries, imports=_imports(root),
                         inherits=inherits or None)

    def add_inheritance_edges(self, graph, file_inherits: dict[str, list[list]],
                              file_sources: dict[str, str], root) -> None:
        """Resolve Go embedding (``inherits``) **package-aware**: a simple-name embed resolves to a
        ``type`` declared in any file of the *same directory* (a Go package == a directory). Qualified
        ``pkg.X`` embeds were already dropped — mapping an import path to a package dir needs ``go.mod``
        resolution that isn't built yet. Edge only when the base type exists (no phantom, no false edge)."""
        dir_types: dict[str, dict[str, str]] = {}  # dir -> {type name -> symbol id}
        for nid in sorted(graph.nodes):
            attrs = graph.nodes[nid]
            if attrs.get("kind") == "type" and attrs.get("language") == self.language_label:
                pid = nid[len("sym:"):].rsplit("#", 1)[0]
                d = pid.rsplit("/", 1)[0] if "/" in pid else ""
                dir_types.setdefault(d, {}).setdefault(attrs["label"], nid)
        for file_id in sorted(file_inherits):
            pid = file_id[len("file:"):]
            d = pid.rsplit("/", 1)[0] if "/" in pid else ""
            for subclass_id, _spec, base_name in file_inherits[file_id]:
                base_id = dir_types.get(d, {}).get(base_name)
                if base_id is not None and base_id != subclass_id:
                    graph.add_edge(subclass_id, base_id, **edge("inherits"))

    def add_import_edges(self, graph, file_imports: dict[str, list[str]],
                         file_sources: dict[str, str], root) -> None:
        """Resolve Go imports to edges. A Go import is a **package path** (``myrepo/pkg/sub``), and a Go
        package is a **directory**, so the import maps to *every* file in that dir. The module prefix comes
        from ``go.mod`` (``module myrepo``); only imports under it are intra-repo — the rest (``fmt``,
        ``github.com/...``) are external and dropped. Needs ``root`` to read ``go.mod``; without it, no-op."""
        module_path = _module_path(root)
        if not module_path:
            return
        dir_files: dict[str, list[str]] = {}  # package dir (repo-relative) → its file ids
        for fid, rel in file_sources.items():
            d = rel.rsplit("/", 1)[0] if "/" in rel else ""
            dir_files.setdefault(d, []).append(fid)
        for file_id in sorted(file_imports):
            for imp in file_imports[file_id]:
                if imp == module_path or imp.startswith(module_path + "/"):
                    pkg_dir = imp[len(module_path):].lstrip("/")
                    for target in sorted(dir_files.get(pkg_dir, [])):
                        if target != file_id:
                            graph.add_edge(file_id, target, **edge("imports"))

    def call_edges(self, symbols: list[Symbol], pid: str, symbol_ids: set[str]) -> list[tuple[str, str]]:
        """Resolve intra-file bare-identifier calls to same-file functions/types (conservative).

        Selector calls (``pkg.Fn``, ``recv.M``) need package/type resolution we don't track in v0, so
        they're dropped rather than guessed — matching the Python extractor's "exact or nothing".
        """
        found: set[tuple[str, str]] = set()
        for s in symbols:
            body = s.defn.child_by_field_name("body")
            if body is None:
                continue
            for call in _collect_calls(body, []):
                fn = call.child_by_field_name("function")
                if fn is None or fn.type != "identifier":
                    continue
                candidate = f"sym:{pid}#{fn.text.decode()}"
                if candidate in symbol_ids and candidate != s.id:
                    found.add((s.id, candidate))
        return sorted(found)


# --------------------------------------------------------------------------------------------------
# Go node helpers
# --------------------------------------------------------------------------------------------------


def _embeds(type_spec: Node) -> list[str]:
    """Simple-name embedded types of a struct/interface ``type_spec`` (Go's inheritance).

    Struct: a ``field_declaration`` with no ``field_identifier`` is embedded — its ``type_identifier``
    is the base (``Base``, or ``*Ptr`` where ``*`` is a sibling token). Interface: a ``type_elem`` whose
    child is a ``type_identifier``. Qualified ``pkg.X`` embeds (``qualified_type``) are skipped — they're
    cross-package and Go import resolution isn't built yet."""
    ty = type_spec.child_by_field_name("type")
    if ty is None:
        return []
    out: list[str] = []
    if ty.type == "struct_type":
        fields = next((c for c in ty.children if c.type == "field_declaration_list"), None)
        for fd in (fields.children if fields is not None else []):
            if fd.type != "field_declaration" or any(c.type == "field_identifier" for c in fd.children):
                continue  # not a field, or a *named* field (not embedded)
            ti = next((c for c in fd.children if c.type == "type_identifier"), None)
            if ti is not None:  # plain or pointer embed; qualified_type has no top-level type_identifier
                out.append(ti.text.decode())
    elif ty.type == "interface_type":
        for elem in ty.children:
            if elem.type == "type_elem":
                ti = next((c for c in elem.children if c.type == "type_identifier"), None)
                if ti is not None:
                    out.append(ti.text.decode())
    return out


def _module_path(root) -> str | None:
    """The module path from ``<root>/go.mod`` (the ``module <path>`` line), or ``None`` if unreadable."""
    if root is None:
        return None
    try:
        text = (Path(root) / "go.mod").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("module "):
            return stripped[len("module "):].strip()
    return None


def _declared_type_names(root: Node) -> set[str]:
    """Names of types declared at the top level of this file (so methods can nest under them)."""
    names: set[str] = set()
    for child in root.children:
        if child.type != "type_declaration":
            continue
        for spec in child.children:
            if spec.type == "type_spec":
                name = _field_text(spec, "name")
                if name:
                    names.add(name)
    return names


def _receiver_type(method_node: Node) -> str | None:
    """The receiver's base type name: ``(s *Stack[T])`` → ``Stack`` (drop pointer + type params)."""
    receiver = method_node.child_by_field_name("receiver")
    if receiver is None:
        return None
    for param in receiver.children:
        if param.type != "parameter_declaration":
            continue
        type_node = param.child_by_field_name("type")
        if type_node is None:
            continue
        text = type_node.text.decode().lstrip("*").strip()
        return text.split("[", 1)[0].strip() or None
    return None


def _field_text(node: Node, field: str) -> str | None:
    child = node.child_by_field_name(field)
    return child.text.decode() if child is not None else None


def _imports(root: Node) -> list[str]:
    """Imported package paths (sorted), from grouped or single ``import`` declarations."""
    out: set[str] = set()
    for child in root.children:
        if child.type != "import_declaration":
            continue
        for sub in child.children:
            if sub.type == "import_spec":
                _add_import(sub, out)
            elif sub.type == "import_spec_list":
                for spec in sub.children:
                    if spec.type == "import_spec":
                        _add_import(spec, out)
    return sorted(out)


def _add_import(spec: Node, out: set[str]) -> None:
    path_node = spec.child_by_field_name("path")
    if path_node is not None:
        raw = path_node.text.decode().strip('"')
        if raw:
            out.add(raw)


def _collect_calls(node: Node, out: list[Node]) -> list[Node]:
    """Collect ``call_expression`` nodes in a body (func literals share the enclosing symbol)."""
    if node.type == "call_expression":
        out.append(node)
    for child in node.children:
        _collect_calls(child, out)
    return out
