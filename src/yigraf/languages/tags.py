"""Generic, query-driven extractor built on tree-sitter **tags queries** (``TAGS_QUERY``).

One extractor class serves any grammar that ships a tags query — the same mechanism behind ctags and
GitHub code navigation. Instead of hand-written per-language node walking, it runs the grammar's
``tags.scm`` (``@definition.*`` / ``@name`` / ``@reference.call``) and derives everything yigraf needs
from the captures plus generic tree-walking:

- **symbols** from ``@definition.{function,method,class,interface,type,module,macro}`` + ``@name``;
- **containment + qualnames** (``Outer.inner``) from node ancestry among the definitions;
- **per-symbol astnorm boundaries** (mask nested defs' bodies) likewise from ancestry;
- **the drift anchor** by hashing the captured definition node, excluding the ``@name`` node so
  renames re-anchor;
- **calls** from ``@reference.call``, attributed to the enclosing definition and resolved to an
  in-file symbol by unique simple name (exact-or-drop, like the hand-written extractors).

This is the cheap-breadth path: configure it per grammar (a few lines) and a language lights up.
The bespoke extractors (Python/Go/JS-TS) stay where they encode finer knowledge the tags can't —
see ``docs`` and the per-language modules.
"""
from __future__ import annotations

import importlib
from pathlib import PurePosixPath
from typing import Callable

from tree_sitter import Language, Node, Query, QueryCursor

from yigraf.languages.base import AstnormSpec, Discovery, LanguageExtractor, Symbol, edge
from yigraf.languages.resolve import resolve_relative, resolve_segments

#: ``definition.<kind>`` capture → yigraf node kind. Kinds absent here (``constant``, ``field``, …)
#: are intentionally skipped: like the hand-written extractors, we don't make every module variable
#: or class field a symbol.
_KIND_MAP = {
    "function": "function",
    "method": "method",
    "class": "class",
    "interface": "interface",
    "type": "type",
    "module": "module",
    "macro": "macro",
    "table": "table",  # SQL
    "view": "view",    # SQL
}


class TagExtractor(LanguageExtractor):
    """A :class:`LanguageExtractor` driven by a grammar's ``TAGS_QUERY`` (configured per language)."""

    def __init__(self, name: str, extensions: tuple[str, ...], language_label: str,
                 grammar: Callable[[], Language], tags_query: Callable[[], str],
                 astnorm_spec: AstnormSpec) -> None:
        super().__init__()
        self.name = name
        self.extensions = extensions
        self.language_label = language_label
        self.astnorm_spec = astnorm_spec
        self._grammar_loader = grammar
        self._query_loader = tags_query
        self._lang: Language | None = None
        self._compiled: Query | None = None

    def ts_language(self) -> Language:
        if self._lang is None:
            self._lang = self._grammar_loader()
            # Compile the query now too: a grammar that ships no/unsupported tags query then fails the
            # availability probe and is skipped, rather than crashing a build mid-run.
            self._compiled = Query(self._lang, self._query_loader())
        return self._lang

    def _query(self) -> Query:
        self.ts_language()  # ensures _compiled is built
        assert self._compiled is not None
        return self._compiled

    def discover(self, root: Node, pid: str, module_id: str, source: bytes) -> Discovery:
        raw_defs, raw_calls = self._run_query(root)
        raw_calls = raw_calls + self._extra_call_refs(root, source)  # subclass calls (tags lack them)
        entries, nodeid_to_entry = _dedup_definitions(raw_defs)
        name_to_entry: dict[str, dict] = {}
        for e in entries:
            name_to_entry.setdefault(e["name"], e)

        # Two notions of "enclosing", which usually coincide but diverge for e.g. Rust ``impl``:
        #  - syntactic: actual tree ancestry — drives astnorm body masking (what the hash walks);
        #  - logical: the subclass's view (impl method → its type) — drives qualname + contains edge.
        def syntactic(node):
            return _plain_ancestor(node, nodeid_to_entry)

        def logical(node):
            return self._logical_container(node, nodeid_to_entry, name_to_entry)

        qualname_of = _qualname_fn(logical)

        boundaries_of: dict[int, dict[int, str]] = {e["node"].id: {} for e in entries}
        module_boundaries: dict[int, str] = {}
        for e in entries:
            enc = syntactic(e["node"])
            if enc is None:
                module_boundaries[e["node"].id] = e["name"]
            else:
                boundaries_of[enc["node"].id][e["node"].id] = e["name"]

        symbols: list[Symbol] = []
        sym_id_of: dict[int, str] = {}
        seen_ids: set[str] = set()
        for e in entries:
            qn = qualname_of(e)
            sym_id = f"sym:{pid}#{qn}"
            if sym_id in seen_ids:
                continue  # duplicate qualname (e.g. overload) → first wins
            seen_ids.add(sym_id)
            sym_id_of[e["node"].id] = sym_id
            enc = logical(e["node"])
            container = f"sym:{pid}#{qualname_of(enc)}" if enc is not None else module_id
            symbols.append(Symbol(
                id=sym_id, kind=e["kind"], name=e["name"], qualname=qn,
                stmt=e["node"], defn=e["node"], container=container,
                boundaries=boundaries_of[e["node"].id], name_node=e["name_node"],
                signature_text=_signature(e["node"], source, self.body_field),
            ))

        calls = _resolve_calls(raw_calls, entries, logical, sym_id_of)
        imports = self._import_specs(root, source)
        return Discovery(symbols=symbols, module_boundaries=module_boundaries, imports=imports, calls=calls)

    # --- enrichment hooks (overridable by per-language subclasses) -------------

    def _normalize_def_node(self, node: Node) -> Node:
        """Map a captured definition node to the node that should be hashed/contained.

        Some tags capture a sub-node (C/C++ capture the ``function_declarator``, not the whole
        ``function_definition``); a subclass promotes it so the hash covers the body and call sites
        sit *inside* the definition. Default: the captured node unchanged.
        """
        return node

    def _logical_container(self, node: Node, nodeid_to_entry: dict[int, dict],
                           name_to_entry: dict[str, dict]) -> dict | None:
        """The definition that *logically* contains ``node`` (default: nearest ancestor definition)."""
        return _plain_ancestor(node, nodeid_to_entry)

    def _extra_call_refs(self, root: Node, source: bytes) -> list[tuple[Node, str]]:
        """Extra ``(call_node, callee_name)`` pairs for grammars whose tags lack ``@reference.call``."""
        return []

    def _import_specs(self, root: Node, source: bytes) -> list[str]:
        """Raw import specifiers recorded on the file node (resolved by :meth:`_resolve_import`)."""
        return []

    def _resolve_import(self, spec: str, base_dir: str, relset: set[str]) -> str | None:
        """Resolve one specifier to a repo relpath (default: none — language subclasses override)."""
        return None

    def add_import_edges(self, graph, file_imports, file_sources, root) -> None:
        relset = set(file_sources.values())
        by_relpath = {src: fid for fid, src in file_sources.items()}
        for file_id in sorted(file_imports):
            base_dir = PurePosixPath(file_sources[file_id]).parent.as_posix()
            for spec in file_imports[file_id]:
                target = self._resolve_import(spec, base_dir, relset)
                tgt_id = by_relpath.get(target) if target else None
                if tgt_id is not None and tgt_id != file_id:
                    graph.add_edge(file_id, tgt_id, **edge("imports"))

    def _run_query(self, root: Node) -> tuple[list, list]:
        """Split the single query run into (definition, name, kind) and (call_node, callee_name)."""
        raw_defs, raw_calls = [], []
        for _pattern, caps in QueryCursor(self._query()).matches(root):
            name_nodes = caps.get("name")
            name_node = name_nodes[0] if name_nodes else None
            def_node = def_kind = None
            for cap, nodes in caps.items():
                if cap.startswith("definition."):
                    kind = _KIND_MAP.get(cap.split(".", 1)[1])
                    if kind is not None and nodes:
                        def_node, def_kind = self._normalize_def_node(nodes[0]), kind
            if def_node is not None and name_node is not None:
                raw_defs.append((def_node, name_node, def_kind))
            elif "reference.call" in caps and name_node is not None:
                raw_calls.append((caps["reference.call"][0], name_node.text.decode()))
        return raw_defs, raw_calls


# --------------------------------------------------------------------------------------------------
# Capture processing (pure helpers)
# --------------------------------------------------------------------------------------------------


def _dedup_definitions(raw_defs: list) -> tuple[list[dict], dict[int, dict]]:
    entries: list[dict] = []
    nodeid_to_entry: dict[int, dict] = {}
    for def_node, name_node, kind in raw_defs:
        if def_node.id in nodeid_to_entry:
            continue
        name = name_node.text.decode()
        if not name:
            continue
        entry = {"node": def_node, "name_node": name_node, "kind": kind, "name": name}
        entries.append(entry)
        nodeid_to_entry[def_node.id] = entry
    return entries, nodeid_to_entry


def _plain_ancestor(node: Node, nodeid_to_entry: dict[int, dict]) -> dict | None:
    """The nearest ancestor that is itself a captured definition (syntactic containment)."""
    parent = node.parent
    while parent is not None:
        entry = nodeid_to_entry.get(parent.id)
        if entry is not None:
            return entry
        parent = parent.parent
    return None


def _qualname_fn(enclosing: Callable[[Node], dict | None]) -> Callable[[dict], str]:
    cache: dict[int, str] = {}

    def qualname_of(entry: dict) -> str:
        nid = entry["node"].id
        if nid not in cache:
            enc = enclosing(entry["node"])
            cache[nid] = f"{qualname_of(enc)}.{entry['name']}" if enc is not None else entry["name"]
        return cache[nid]

    return qualname_of


def _resolve_calls(raw_calls: list, entries: list[dict], enclosing, sym_id_of: dict[int, str]) -> list[tuple[str, str]]:
    by_simple: dict[str, set[str]] = {}
    for e in entries:
        sid = sym_id_of.get(e["node"].id)
        if sid is not None:
            by_simple.setdefault(e["name"], set()).add(sid)

    pairs: set[tuple[str, str]] = set()
    for call_node, callee in raw_calls:
        enc = enclosing(call_node)
        caller = sym_id_of.get(enc["node"].id) if enc is not None else None
        targets = by_simple.get(callee)
        if caller is not None and targets and len(targets) == 1:
            target = next(iter(targets))
            if target != caller:
                pairs.add((caller, target))
    return sorted(pairs)


def _signature(node: Node, source: bytes, body_field: str) -> str | None:
    """Declaration up to the body (whitespace-collapsed); first line if there's no body field."""
    body = node.child_by_field_name(body_field)
    if body is not None:
        raw = source[node.start_byte : body.start_byte].decode("utf-8", "surrogatepass")
        collapsed = " ".join(raw.split())
        if collapsed:
            return collapsed
    text = source[node.start_byte : node.end_byte].decode("utf-8", "surrogatepass")
    first_line = " ".join(text.splitlines()[0].split()) if text else ""
    return first_line or None


# --------------------------------------------------------------------------------------------------
# Per-language configuration → the generic extractor instances
# --------------------------------------------------------------------------------------------------

#: Generic astnorm: no quote-style normalization (these languages have one string quote, or treat
#: ``'``/``"`` as semantically distinct) and no docstrings. Comments are dropped via ``comment_types``.
_NO_QUOTE = dict(quote_tokens=frozenset(), body_containers=frozenset(), docstring_types=frozenset())
_SPEC_C_COMMENT = AstnormSpec(**_NO_QUOTE)  # comment_types defaults to {"comment"}
_SPEC_CXX_COMMENT = AstnormSpec(comment_types=frozenset({"line_comment", "block_comment", "comment"}), **_NO_QUOTE)
#: Broad comment set for the vendored-query languages (covers C#/Kotlin/Scala/Swift naming variants).
_SPEC_VENDORED_COMMENT = AstnormSpec(
    comment_types=frozenset({"comment", "line_comment", "block_comment", "multiline_comment"}), **_NO_QUOTE)


def _grammar(module: str, *attrs: str) -> Callable[[], Language]:
    """Lazy loader: import ``tree_sitter_<module>`` and call the first available language function."""
    def load() -> Language:
        mod = importlib.import_module(f"tree_sitter_{module}")
        for attr in attrs:
            fn = getattr(mod, attr, None)
            if fn is not None:
                return Language(fn())
        raise AttributeError(f"tree_sitter_{module}: none of {attrs} found")
    return load


def _tags_query(module: str) -> Callable[[], str]:
    def load() -> str:
        query = getattr(importlib.import_module(f"tree_sitter_{module}"), "TAGS_QUERY", None)
        if not query:
            raise AttributeError(f"tree_sitter_{module} ships no TAGS_QUERY")
        return query
    return load


def _walk(node: Node):
    """Pre-order walk over every node in the tree (for import/call extraction)."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


# Each dedicated extractor is the generic TagExtractor plus a thin "extra layer": import resolution,
# and where the tags query is short (Rust ``impl`` containment, C/C++ calls), a targeted hook.


class RustExtractor(TagExtractor):
    def __init__(self) -> None:
        super().__init__("rust", (".rs",), "rust", _grammar("rust", "language"),
                         _tags_query("rust"), _SPEC_CXX_COMMENT)

    def _logical_container(self, node, nodeid_to_entry, name_to_entry):
        # `impl Type { fn m }`: impl blocks aren't tag-definitions, so attach the method to its type.
        parent = node.parent
        while parent is not None:
            entry = nodeid_to_entry.get(parent.id)
            if entry is not None:
                return entry
            if parent.type == "impl_item":
                type_node = parent.child_by_field_name("type")
                if type_node is None:
                    return None
                base = type_node.text.decode().split("<", 1)[0].split("::")[-1].strip()
                return name_to_entry.get(base)
            parent = parent.parent
        return None

    def _import_specs(self, root, source):
        names = set()
        for child in root.children:  # `mod foo;` (file module) has no inline declaration_list body
            if child.type == "mod_item" and not any(c.type == "declaration_list" for c in child.children):
                name = child.child_by_field_name("name")
                if name is not None:
                    names.add(name.text.decode())
        return sorted(names)

    def _resolve_import(self, spec, base_dir, relset):
        return resolve_relative(base_dir, spec, relset, (".rs",))


class JavaExtractor(TagExtractor):
    def __init__(self) -> None:
        super().__init__("java", (".java",), "java", _grammar("java", "language"),
                         _tags_query("java"), _SPEC_CXX_COMMENT)

    def _import_specs(self, root, source):
        out = set()
        for child in root.children:
            if child.type == "import_declaration":
                for c in child.children:
                    if c.type in ("scoped_identifier", "identifier"):
                        out.add(c.text.decode())
        return sorted(out)

    def _resolve_import(self, spec, base_dir, relset):
        return resolve_segments(spec.split("."), relset, (".java",))


class _CFamilyExtractor(TagExtractor):
    """Shared C/C++: ``#include "x"`` import edges + ``call_expression`` calls (their tags ship none)."""

    def _normalize_def_node(self, node):
        # C/C++ tags capture the function_declarator; promote it to the function_definition (when one
        # exists — i.e. not a bare prototype) so the body is hashed and calls sit inside it.
        if node.type == "function_declarator":
            parent = node.parent
            while parent is not None:
                if parent.type == "function_definition":
                    return parent
                parent = parent.parent
        return node

    def _extra_call_refs(self, root, source):
        out = []
        for n in _walk(root):
            if n.type == "call_expression":
                fn = n.child_by_field_name("function")
                if fn is not None and fn.type == "identifier":
                    out.append((n, fn.text.decode()))
        return out

    def _import_specs(self, root, source):
        out = set()
        for n in _walk(root):
            if n.type == "preproc_include":
                path = n.child_by_field_name("path")
                if path is not None and path.type == "string_literal":  # "..."; <...> is external
                    out.add(path.text.decode().strip('"'))
        return sorted(out)

    def _resolve_import(self, spec, base_dir, relset):
        # include path already carries its extension; try relative to the file, then repo-root.
        return resolve_relative(base_dir, spec, relset, ()) or resolve_relative("", spec, relset, ())


class CExtractor(_CFamilyExtractor):
    def __init__(self) -> None:
        super().__init__("c", (".c", ".h"), "c", _grammar("c", "language"),
                         _tags_query("c"), _SPEC_C_COMMENT)


class CppExtractor(_CFamilyExtractor):
    def __init__(self) -> None:
        super().__init__("cpp", (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"), "cpp",
                         _grammar("cpp", "language"), _tags_query("cpp"), _SPEC_C_COMMENT)


class RubyExtractor(TagExtractor):
    def __init__(self) -> None:
        super().__init__("ruby", (".rb",), "ruby", _grammar("ruby", "language"),
                         _tags_query("ruby"), _SPEC_C_COMMENT)

    def _import_specs(self, root, source):
        out = set()
        for n in _walk(root):
            if n.type == "call":
                method = n.child_by_field_name("method")
                args = n.child_by_field_name("arguments")
                if method is not None and method.text.decode() == "require_relative" and args is not None:
                    for a in args.children:
                        if a.type == "string":
                            out.add(a.text.decode().strip("\"'"))
        return sorted(s for s in out if s)

    def _resolve_import(self, spec, base_dir, relset):
        return resolve_relative(base_dir, spec, relset, (".rb",))


class PhpExtractor(TagExtractor):
    def __init__(self) -> None:
        super().__init__("php", (".php",), "php", _grammar("php", "language_php", "language"),
                         _tags_query("php"), _SPEC_C_COMMENT)

    def _import_specs(self, root, source):
        out = set()
        for n in _walk(root):
            if n.type in ("require_expression", "require_once_expression",
                          "include_expression", "include_once_expression"):
                for c in n.children:
                    if c.type in ("string", "encapsed_string"):
                        out.add(c.text.decode().strip("\"'"))
        return sorted(s for s in out if s)

    def _resolve_import(self, spec, base_dir, relset):
        return resolve_relative(base_dir, spec, relset, (".php",))


#: Dedicated extractors for the tags-query languages (generic core + a per-language enrichment layer).
#: ``.h`` is given to C; C++ owns the unambiguous C++ suffixes (a documented heuristic).
GENERIC_EXTRACTORS: tuple[TagExtractor, ...] = (
    RustExtractor(), JavaExtractor(), CExtractor(), CppExtractor(), RubyExtractor(), PhpExtractor(),
)


# --------------------------------------------------------------------------------------------------
# Vendored tags queries — grammars bundled but shipping no usable TAGS_QUERY (c_sharp's is None;
# kotlin/scala/swift ship none). Authored against each grammar's verified node types/fields. Scope:
# definitions + names everywhere; calls where the grammar exposes a call function field (C#, Scala).
# Import edges aren't attempted here (these module systems don't map cleanly to files) — a follow-up.
# --------------------------------------------------------------------------------------------------

_CSHARP_TAGS = """
(class_declaration name: (identifier) @name) @definition.class
(struct_declaration name: (identifier) @name) @definition.class
(record_declaration name: (identifier) @name) @definition.class
(interface_declaration name: (identifier) @name) @definition.interface
(enum_declaration name: (identifier) @name) @definition.type
(namespace_declaration name: (identifier) @name) @definition.module
(method_declaration name: (identifier) @name) @definition.method
(constructor_declaration name: (identifier) @name) @definition.method
(invocation_expression function: (identifier) @name) @reference.call
(invocation_expression function: (member_access_expression name: (identifier) @name)) @reference.call
"""

_KOTLIN_TAGS = """
(class_declaration name: (identifier) @name) @definition.class
(object_declaration name: (identifier) @name) @definition.class
(function_declaration name: (identifier) @name) @definition.function
"""

_SCALA_TAGS = """
(class_definition name: (identifier) @name) @definition.class
(object_definition name: (identifier) @name) @definition.class
(trait_definition name: (identifier) @name) @definition.interface
(function_definition name: (identifier) @name) @definition.method
(call_expression function: (identifier) @name) @reference.call
"""

_SWIFT_TAGS = """
(class_declaration name: (type_identifier) @name) @definition.class
(protocol_declaration name: (type_identifier) @name) @definition.interface
(function_declaration name: (simple_identifier) @name) @definition.function
"""

# Bash ships no TAGS_QUERY; functions are definitions and `command` invocations are call references
# (only those matching an in-file function resolve to an edge — external commands are dropped).
_BASH_TAGS = """
(function_definition (word) @name) @definition.function
(command (command_name) @name) @reference.call
"""

# SQL: schema objects are the "symbols" (drift on a CREATE is a useful schema-change signal). No call
# model. Only verified node types — an unknown one would fail query compile and skip the language.
_SQL_TAGS = """
(create_table (object_reference (identifier) @name)) @definition.table
(create_view (object_reference (identifier) @name)) @definition.view
(create_function (object_reference (identifier) @name)) @definition.function
"""


def _vendored(name: str, exts: tuple[str, ...], module: str, lang_attrs: tuple[str, ...],
              query: str) -> TagExtractor:
    return TagExtractor(name, exts, name, _grammar(module, *lang_attrs), lambda: query, _SPEC_VENDORED_COMMENT)


def _member_callee(call: Node, id_types: frozenset[str]) -> str | None:
    """Callee name of a Kotlin/Swift ``call_expression``: a bare identifier, or the member of a
    ``navigation_expression`` (``this.m()`` / ``self.m()`` → ``m``)."""
    if not call.named_children:
        return None
    callee = call.named_children[0]  # the value_arguments node is a later child
    if callee.type in id_types:
        return callee.text.decode()
    last = None
    for node in _walk(callee):
        if node.type in id_types:
            last = node
    return last.text.decode() if last is not None else None


class _CallExprMixin(TagExtractor):
    """Adds intra-file call edges for languages whose tags query has no ``@reference.call`` and whose
    ``call_expression`` has no function field (Kotlin/Swift) — resolution reuses the generic machinery."""

    _ID_TYPES: frozenset[str] = frozenset()

    def _extra_call_refs(self, root, source):
        out = []
        for node in _walk(root):
            if node.type == "call_expression":
                name = _member_callee(node, self._ID_TYPES)
                if name:
                    out.append((node, name))
        return out


class KotlinExtractor(_CallExprMixin):
    _ID_TYPES = frozenset({"identifier", "simple_identifier"})

    def __init__(self) -> None:
        super().__init__("kotlin", (".kt", ".kts"), "kotlin", _grammar("kotlin", "language"),
                         lambda: _KOTLIN_TAGS, _SPEC_VENDORED_COMMENT)


class SwiftExtractor(_CallExprMixin):
    _ID_TYPES = frozenset({"simple_identifier"})

    def __init__(self) -> None:
        super().__init__("swift", (".swift",), "swift", _grammar("swift", "language"),
                         lambda: _SWIFT_TAGS, _SPEC_VENDORED_COMMENT)


#: Extractors using a yigraf-vendored tags query (the grammar ships none usable). Kotlin/Swift add
#: call edges via a hook (their call_expression has no function field for the query to key on).
VENDORED_EXTRACTORS: tuple[TagExtractor, ...] = (
    _vendored("c_sharp", (".cs",), "c_sharp", ("language",), _CSHARP_TAGS),
    KotlinExtractor(),
    _vendored("scala", (".scala", ".sc"), "scala", ("language",), _SCALA_TAGS),
    SwiftExtractor(),
    _vendored("bash", (".sh", ".bash"), "bash", ("language",), _BASH_TAGS),
    _vendored("sql", (".sql",), "sql", ("language",), _SQL_TAGS),
)
