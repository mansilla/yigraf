"""JavaScript / TypeScript structure extractor (tree-sitter-javascript + tree-sitter-typescript).

One extractor spans the whole family — ``.js .jsx .mjs .cjs .ts .tsx`` — because they share ~all of
their symbol shapes and routinely import across suffixes (a ``.ts`` importing a ``.tsx``). The
grammar is picked per file: ``.ts`` → typescript, ``.tsx`` → tsx, everything else → javascript.

Symbols (top-level, unwrapping ``export``; plus class methods):
- ``function_declaration`` / ``generator_function_declaration`` → function.
- ``class_declaration`` / ``abstract_class_declaration`` → class; ``method_definition`` → method.
- ``const`` / ``let`` / ``var`` bound to an arrow or function expression → function (the modern idiom).
- TS ``interface_declaration`` / ``type_alias_declaration`` / ``enum_declaration`` → type.

Calls resolve intra-file like the other extractors (bare identifier → top-level function; ``this.m()``
→ a sibling method), dropping everything else rather than guessing. Imports are recorded on the file
node and resolved into edges best-effort: relative specifiers (``./x``, ``../y``) against the repo's
files, trying the usual extensions and ``/index`` — across all JS/TS suffixes. astnorm normalizes
``'``/``"`` quote style (Prettier flips these) and has no docstrings.
"""
from __future__ import annotations

import posixpath
from pathlib import PurePosixPath

from tree_sitter import Language, Parser

from yigraf.languages.base import AstnormSpec, Discovery, LanguageExtractor, Symbol, edge

_FUNC_DECLS = frozenset({"function_declaration", "generator_function_declaration"})
_CLASS_DECLS = frozenset({"class_declaration", "abstract_class_declaration"})
_TYPE_DECLS = frozenset({"interface_declaration", "type_alias_declaration", "enum_declaration"})
_FUNC_VALUES = frozenset({"arrow_function", "function", "function_expression"})
_RESOLVE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

#: JS/TS strings allow interchangeable ``'``/``"`` (Prettier rewrites them) and have no docstrings.
JSTS_ASTNORM = AstnormSpec(quote_tokens=frozenset({"'", '"'}), body_containers=frozenset(),
                           docstring_types=frozenset())


class JsTsExtractor(LanguageExtractor):
    name = "javascript"
    aliases = ("typescript",)
    extensions = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")
    astnorm_spec = JSTS_ASTNORM

    def __init__(self) -> None:
        super().__init__()
        self._langs: dict[str, Language] = {}
        self._parsers: dict[str, Parser] = {}

    def ts_language(self) -> Language:
        # Availability probe: require *both* grammars (the family is one extractor), return one.
        return self._grammar("javascript")

    def _grammar(self, key: str) -> Language:
        if key not in self._langs:
            if key == "typescript":
                import tree_sitter_typescript as tsts

                self._langs[key] = Language(tsts.language_typescript())
            elif key == "tsx":
                import tree_sitter_typescript as tsts

                self._langs[key] = Language(tsts.language_tsx())
            else:
                import tree_sitter_javascript as tsjs

                self._langs[key] = Language(tsjs.language())
        return self._langs[key]

    @staticmethod
    def _grammar_key(relpath: str) -> str:
        suffix = PurePosixPath(relpath).suffix
        return {".ts": "typescript", ".tsx": "tsx"}.get(suffix, "javascript")

    def parser_for(self, relpath: str) -> Parser:
        key = self._grammar_key(relpath)
        if key not in self._parsers:
            self._parsers[key] = Parser(self._grammar(key))
        return self._parsers[key]

    def language_label_for(self, relpath: str) -> str:
        return "typescript" if PurePosixPath(relpath).suffix in (".ts", ".tsx") else "javascript"

    def discover(self, root, pid: str, module_id: str, source: bytes) -> Discovery:
        symbols: list[Symbol] = []
        for stmt in root.children:
            decl = stmt
            if stmt.type == "export_statement":
                decl = stmt.child_by_field_name("declaration")
                if decl is None:
                    continue  # `export { … }` / `export default <expr>` — no named local declaration
            _emit_decl(stmt, decl, pid, module_id, source, symbols)
        module_boundaries = {s.stmt.id: s.name for s in symbols if s.container == module_id}
        bindings = _es_bindings(root)  # named-import bindings → import-aware base resolution
        inherits = [
            [s.id, *bindings.get(base, ("", base))]
            for s in symbols if s.kind in ("class", "type")
            for base in _heritage_bases(s.defn)
        ]
        return Discovery(symbols=symbols, module_boundaries=module_boundaries, imports=_imports(root),
                         inherits=inherits or None)

    def call_edges(self, symbols, pid: str, symbol_ids: set[str]) -> list[tuple[str, str]]:
        found: set[tuple[str, str]] = set()
        for s in symbols:
            for call in _collect_calls(s.stmt, s.boundaries, []):
                target = _resolve_call(call, pid, s.enclosing_class, symbol_ids)
                if target is not None and target != s.id:
                    found.add((s.id, target))
        return sorted(found)

    def add_import_edges(self, graph, file_imports, file_sources, root) -> None:
        by_relpath = {src: fid for fid, src in file_sources.items()}
        relset = set(file_sources.values())
        for file_id in sorted(file_imports):
            base_dir = PurePosixPath(file_sources[file_id]).parent
            for spec in file_imports[file_id]:
                if not spec.startswith("."):
                    continue  # bare specifier (node_modules / stdlib) → external, no edge
                target = _resolve_relative_import(base_dir, spec, relset)
                tgt_id = by_relpath.get(target) if target else None
                if tgt_id is not None and tgt_id != file_id:
                    graph.add_edge(file_id, tgt_id, **edge("imports"))

    def add_inheritance_edges(self, graph, file_inherits, file_sources, root) -> None:
        """Resolve ``extends``/``implements`` (``inherits``) **import-aware**: a base bound by a named ES
        import resolves through its relative specifier (``./base``) to the defining file; an unbound base
        is looked up in the same file. Bare specifiers (node_modules) and default/namespace/qualified
        bases were already dropped. Edge only when the base symbol exists (no phantom, no false edge)."""
        by_relpath = {src: fid for fid, src in file_sources.items()}
        relset = set(file_sources.values())
        for file_id in sorted(file_inherits):
            base_dir = PurePosixPath(file_sources.get(file_id, "")).parent
            for subclass_id, spec, base_name in file_inherits[file_id]:
                if spec == "":
                    target_file = file_id  # unbound → same-file base
                elif spec.startswith("."):
                    tgt_rel = _resolve_relative_import(base_dir, spec, relset)
                    target_file = by_relpath.get(tgt_rel) if tgt_rel else None
                else:
                    target_file = None  # bare specifier → external
                if target_file is None:
                    continue
                base_id = f"sym:{target_file[len('file:'):]}#{base_name}"
                if base_id in graph and base_id != subclass_id:
                    graph.add_edge(subclass_id, base_id, **edge("inherits"))


# --------------------------------------------------------------------------------------------------
# Declaration → symbol(s)
# --------------------------------------------------------------------------------------------------


def _emit_decl(stmt, decl, pid: str, module_id: str, source: bytes, out: list[Symbol]) -> None:
    """Append the symbol(s) a top-level declaration produces (``stmt`` is the hashed/masked node)."""
    t = decl.type
    if t in _FUNC_DECLS:
        name = _field_text(decl, "name")
        if name:
            out.append(Symbol(id=f"sym:{pid}#{name}", kind="function", name=name, qualname=name,
                              stmt=stmt, defn=decl, container=module_id))
    elif t in _CLASS_DECLS:
        name = _field_text(decl, "name")
        if name:
            methods = _methods(decl, pid, name)
            boundaries = {m.stmt.id: m.name for m in methods}
            out.append(Symbol(id=f"sym:{pid}#{name}", kind="class", name=name, qualname=name,
                              stmt=stmt, defn=decl, container=module_id, boundaries=boundaries))
            out.extend(methods)
    elif t in _TYPE_DECLS:
        name = _field_text(decl, "name")
        if name:
            out.append(Symbol(id=f"sym:{pid}#{name}", kind="type", name=name, qualname=name,
                              stmt=stmt, defn=decl, container=module_id))
    elif t in ("lexical_declaration", "variable_declaration"):
        _emit_assigned_function(stmt, decl, pid, module_id, source, out)


def _emit_assigned_function(stmt, decl, pid: str, module_id: str, source: bytes, out: list[Symbol]) -> None:
    """`const foo = () => {…}` / `const foo = function () {…}` → a function symbol named ``foo``."""
    declarators = [c for c in decl.children if c.type == "variable_declarator"]
    if len(declarators) != 1:
        return  # only single-binding declarations become symbols (avoid cross-contaminated hashes)
    vd = declarators[0]
    value = vd.child_by_field_name("value")
    name_node = vd.child_by_field_name("name")
    if value is None or value.type not in _FUNC_VALUES:
        return
    if name_node is None or name_node.type != "identifier":
        return  # destructuring binding → no single symbol name
    name = name_node.text.decode()
    body = value.child_by_field_name("body")
    sig = None
    if body is not None:
        sig = " ".join(source[stmt.start_byte : body.start_byte].decode("utf-8", "surrogatepass").split())
    out.append(Symbol(id=f"sym:{pid}#{name}", kind="function", name=name, qualname=name,
                      stmt=stmt, defn=vd, container=module_id, signature_text=sig))


def _methods(class_decl, pid: str, class_name: str) -> list[Symbol]:
    body = class_decl.child_by_field_name("body")
    out: list[Symbol] = []
    for stmt in body.children if body is not None else []:
        if stmt.type != "method_definition":
            continue
        name = _field_text(stmt, "name")
        if not name:
            continue
        out.append(Symbol(id=f"sym:{pid}#{class_name}.{name}", kind="method", name=name,
                          qualname=f"{class_name}.{name}", stmt=stmt, defn=stmt,
                          container=f"sym:{pid}#{class_name}", enclosing_class=class_name))
    return out


# --------------------------------------------------------------------------------------------------
# Calls / imports
# --------------------------------------------------------------------------------------------------


def _collect_calls(node, boundaries: dict[int, str], out: list) -> list:
    if node.id in boundaries:
        return out  # a nested extracted symbol (a method) owns its own calls
    if node.type == "call_expression":
        out.append(node)
    for child in node.children:
        _collect_calls(child, boundaries, out)
    return out


def _resolve_call(call, pid: str, enclosing_class: str | None, symbol_ids: set[str]) -> str | None:
    fn = call.child_by_field_name("function")
    if fn is None:
        return None
    if fn.type == "identifier":
        candidate = f"sym:{pid}#{fn.text.decode()}"
        return candidate if candidate in symbol_ids else None
    if fn.type == "member_expression" and enclosing_class is not None:
        obj = fn.child_by_field_name("object")
        prop = fn.child_by_field_name("property")
        if obj is not None and prop is not None and obj.type == "this" and prop.type == "property_identifier":
            candidate = f"sym:{pid}#{enclosing_class}.{prop.text.decode()}"
            return candidate if candidate in symbol_ids else None
    return None


def _heritage_bases(decl) -> list[str]:
    """Simple-name bases of a class (``extends`` + ``implements``) or interface (``extends``).

    Skips qualified bases (``ns.Base`` → a ``member_expression``, not an identifier) and any non-name
    heritage entry — precision over recall, like the other extractors. In an ``extends_clause`` the base
    sits in value position (``identifier``); ``implements_clause`` / interface ``extends_type_clause`` use
    type position (``type_identifier``)."""
    names: list[str] = []
    heritage = next((c for c in decl.children if c.type == "class_heritage"), None)
    if heritage is not None:  # class
        for clause in heritage.children:
            if clause.type in ("extends_clause", "implements_clause"):
                names += [c.text.decode() for c in clause.children
                          if c.type in ("identifier", "type_identifier")]
    else:  # interface
        clause = next((c for c in decl.children if c.type == "extends_type_clause"), None)
        if clause is not None:
            names += [c.text.decode() for c in clause.children if c.type == "type_identifier"]
    return names


def _es_bindings(root) -> dict[str, tuple[str, str]]:
    """``import { Base [as Local] } from "spec"`` → ``{local_name: (spec, original_name)}`` for base
    resolution. Default (``import X from``) and namespace (``import * as ns``) imports are skipped —
    they don't bind a name that maps to an exported *symbol* of that name."""
    bindings: dict[str, tuple[str, str]] = {}
    for child in root.children:
        if child.type != "import_statement":
            continue
        source = child.child_by_field_name("source")
        clause = next((c for c in child.children if c.type == "import_clause"), None)
        if source is None or source.type != "string" or clause is None:
            continue
        spec = source.text.decode().strip("\"'`")
        named = next((c for c in clause.children if c.type == "named_imports"), None)
        if named is None:
            continue  # default / namespace import — no name→symbol binding
        for sp in named.children:
            if sp.type != "import_specifier":
                continue
            ids = [c for c in sp.children if c.type == "identifier"]
            if len(ids) == 1:  # `import { Base }`
                bindings[ids[0].text.decode()] = (spec, ids[0].text.decode())
            elif len(ids) >= 2:  # `import { Orig as Local }`
                bindings[ids[1].text.decode()] = (spec, ids[0].text.decode())
    return bindings


def _imports(root) -> list[str]:
    """Module specifiers from ``import … from "x"`` and re-exports ``export … from "x"`` (sorted)."""
    out: set[str] = set()
    for child in root.children:
        if child.type in ("import_statement", "export_statement"):
            source = child.child_by_field_name("source")
            if source is not None and source.type == "string":
                raw = source.text.decode().strip("\"'`")
                if raw:
                    out.add(raw)
    return sorted(out)


def _resolve_relative_import(base_dir: PurePosixPath, spec: str, relset: set[str]) -> str | None:
    """Resolve a relative specifier to a repo relpath, trying extensions and ``/index`` (best-effort)."""
    raw = posixpath.normpath(f"{base_dir}/{spec}")
    candidates = [raw]
    candidates += [raw + ext for ext in _RESOLVE_EXTS]
    candidates += [f"{raw}/index{ext}" for ext in _RESOLVE_EXTS]
    if raw.endswith(".js"):  # ESM/TS often import "./x.js" to mean the compiled "./x.ts"
        stem = raw[:-3]
        candidates += [stem + ext for ext in _RESOLVE_EXTS]
    for candidate in candidates:
        if candidate in relset:
            return candidate
    return None


def _field_text(node, field: str) -> str | None:
    child = node.child_by_field_name(field)
    return child.text.decode() if child is not None else None
