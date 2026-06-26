"""Language-agnostic core of structure extraction.

Holds the pieces every language extractor shares — the :class:`Symbol` record, the node/edge
builders, the :class:`AstnormSpec`, and the :class:`LanguageExtractor` base that turns a language's
*discovery* (symbols + module boundaries + imports) into a :class:`FileProjection` (nodes + edges
carrying content hashes, signatures, and ``contains``/``calls`` edges). Per-language modules
(``python.py``, ``go.py``) subclass it and supply only the language-specific node-type knowledge.

The split mirrors Graphify's hybrid extractor (a declarative core + per-language specifics) but is
scoped to exactly what yigraf needs — file/module/symbol nodes, ``contains``/``calls``/``imports``
edges, and the astnorm drift anchor — with none of Graphify's community/type-ref machinery.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from tree_sitter import Language, Node, Parser

from yigraf import astnorm

FAMILY = "structure"
CONF_EXTRACTED = "EXTRACTED"


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


@dataclass(frozen=True)
class AstnormSpec:
    """Per-language knobs for the astnorm drift anchor (see :mod:`yigraf.astnorm`).

    Defaults are Python's, so an extractor that omits them gets the original rule. Go passes empty
    sets — it has no docstrings and no quote-style ambiguity, so neither normalization applies.
    """

    quote_tokens: frozenset[str] = astnorm._PY_QUOTE_TOKENS
    body_containers: frozenset[str] = astnorm._PY_BODY_CONTAINERS
    docstring_types: frozenset[str] = astnorm._PY_DOCSTRING_TYPES
    comment_types: frozenset[str] = astnorm._PY_COMMENT_TYPES

    def kwargs(self) -> dict[str, frozenset[str]]:
        return {"quote_tokens": self.quote_tokens, "body_containers": self.body_containers,
                "docstring_types": self.docstring_types, "comment_types": self.comment_types}


@dataclass
class Symbol:
    """An extracted symbol and the facts needed to node-ify, hash, and link it."""

    id: str
    kind: str  # function | class | method | type | ...
    name: str  # local name (the marker name in a parent's hash)
    qualname: str  # graph label, e.g. "C.m"
    stmt: Node  # the node hashed for this symbol (decorated stmt where the language decorates)
    defn: Node  # the unwrapped definition (for signature + own-name exclusion)
    container: str  # id of the node that ``contains`` this one
    boundaries: dict[int, str] = field(default_factory=dict)  # nested extracted symbols → markers
    exclude_own_name: bool = True  # drop the symbol's own name id from its hash (rename re-anchor)
    enclosing_class: str | None = None  # language-specific resolver context (Python ``self.m()``)
    signature_node: Node | None = None  # node to derive the signature from (defaults to ``defn``)
    signature_text: str | None = None  # verbatim signature override (shapes with no body field, e.g. arrows)
    name_node: Node | None = None  # explicit own-name node to exclude from the hash (else via ``name_field``)


@dataclass
class Discovery:
    """What a language's discovery pass yields for one file."""

    symbols: list[Symbol]
    #: top-level declaration node ids → markers, masking their bodies in the *module* hash
    module_boundaries: dict[int, str]
    imports: list[str]  # sorted dotted/path import targets, recorded on the file node
    #: pre-resolved ``calls`` edges; when ``None`` the base falls back to :meth:`call_edges`
    calls: list[tuple[str, str]] | None = None


# --------------------------------------------------------------------------------------------------
# Shared node / edge builders
# --------------------------------------------------------------------------------------------------


def file_module_ids(pid: str) -> tuple[str, str]:
    return f"file:{pid}", f"module:{pid}"


def struct_node(kind: str, label: str, source_file: str, content_hash_: str,
                source_range: list[int], language: str) -> dict:
    return {
        "family": FAMILY,
        "kind": kind,
        "label": label,
        "language": language,
        "confidence": CONF_EXTRACTED,
        "content_hash": content_hash_,
        "source_file": source_file,
        "source_range": source_range,
    }


def edge(relation: str) -> dict:
    return {"relation": relation, "confidence": CONF_EXTRACTED}


def node_range(node: Node) -> list[int]:
    start, end = node.start_point, node.end_point
    return [start.row, start.column, end.row, end.column]


def own_name_ids(defn: Node, name_field: str) -> frozenset[int]:
    """The node id of a def's own name identifier — excluded from its hash so renames re-anchor."""
    name = defn.child_by_field_name(name_field)
    return frozenset({name.id}) if name is not None else frozenset()


def signature(defn: Node, source: bytes, body_field: str) -> str | None:
    """The one-line declaration up to the body, whitespace-collapsed (``None`` if it has no body)."""
    body = defn.child_by_field_name(body_field)
    if body is None:
        return None
    raw = source[defn.start_byte : body.start_byte].decode("utf-8", "surrogatepass")
    return " ".join(raw.split())


# --------------------------------------------------------------------------------------------------
# Extractor base
# --------------------------------------------------------------------------------------------------


class LanguageExtractor:
    """Base class: shared per-file orchestration. Subclasses supply the language-specific knowledge.

    A subclass sets the class attributes (``name``, ``extensions``, ``language_label``,
    ``astnorm_spec``, ``name_field``, ``body_field``) and implements :meth:`ts_language` and
    :meth:`discover`; optionally :meth:`call_edges` and :meth:`add_import_edges`. Everything that is
    truly common — parsing, the module/file nodes, per-symbol hashing + signatures, ``contains``
    edges, and the cache-facing :class:`FileProjection` — lives here.
    """

    name: str = ""
    aliases: tuple[str, ...] = ()  # extra config-``languages`` names that enable this extractor
    extensions: tuple[str, ...] = ()
    language_label: str = ""
    astnorm_spec: AstnormSpec = AstnormSpec()
    name_field: str = "name"
    body_field: str = "body"

    def __init__(self) -> None:
        self._parser: Parser | None = None

    # --- subclass hooks -------------------------------------------------------

    def ts_language(self) -> Language:
        raise NotImplementedError

    def discover(self, root: Node, pid: str, module_id: str, source: bytes) -> Discovery:
        raise NotImplementedError

    def call_edges(self, symbols: list[Symbol], pid: str, symbol_ids: set[str]) -> list[tuple[str, str]]:
        return []

    def add_import_edges(self, graph, file_imports: dict[str, list[str]],
                         file_sources: dict[str, str], root) -> None:
        """Resolve intra-repo import edges for this language (no-op by default)."""

    # --- shared machinery -----------------------------------------------------

    def parser(self) -> Parser:
        if self._parser is None:
            self._parser = Parser(self.ts_language())
        return self._parser

    def parser_for(self, relpath: str) -> Parser:
        """The parser for ``relpath`` (override for families whose grammar varies by suffix, e.g. TS/TSX)."""
        return self.parser()

    def language_label_for(self, relpath: str) -> str:
        """The ``language`` node attribute for ``relpath`` (override for multi-dialect families)."""
        return self.language_label

    def extract_file(self, relpath: str, source: bytes) -> FileProjection:
        """Project a single source file into structure nodes + intra-file edges."""
        rel = PurePosixPath(relpath).as_posix()
        pid = rel.casefold()  # path casefolded for id stability; symbol names stay exact
        file_id, module_id = file_module_ids(pid)
        language = self.language_label_for(relpath)

        root = self.parser_for(relpath).parse(source).root_node
        disc = self.discover(root, pid, module_id, source)
        ak = self.astnorm_spec.kwargs()

        nodes: dict[str, dict] = {}
        edges: list[list] = []

        module_hash = astnorm.content_hash(root, source, disc.module_boundaries, **ak)
        nodes[module_id] = struct_node("module", rel, rel, module_hash, node_range(root), language)
        nodes[file_id] = struct_node("file", rel, rel, module_hash, node_range(root), language)
        nodes[file_id]["imports"] = disc.imports
        edges.append([file_id, module_id, edge("contains")])

        symbol_ids = {s.id for s in disc.symbols}
        for s in disc.symbols:
            excl = self._exclude_ids(s)
            h = astnorm.content_hash(s.stmt, source, s.boundaries, exclude=excl, **ak)
            nodes[s.id] = struct_node(s.kind, s.qualname, rel, h, node_range(s.stmt), language)
            sig = s.signature_text if s.signature_text is not None else signature(
                s.signature_node or s.defn, source, self.body_field)
            if sig is not None:
                nodes[s.id]["signature"] = sig  # for "locator + signature, not source" render (M4)
            edges.append([s.container, s.id, edge("contains")])

        calls = disc.calls if disc.calls is not None else self.call_edges(disc.symbols, pid, symbol_ids)
        for src, dst in calls:
            edges.append([src, dst, edge("calls")])

        return FileProjection(nodes=nodes, edges=edges)

    def _exclude_ids(self, s: "Symbol") -> frozenset[int]:
        """Node ids dropped from a symbol's hash so a rename re-anchors: the explicit ``name_node`` if
        the extractor captured one (generic/tags path), else the ``name_field`` child of ``defn``."""
        if s.name_node is not None:
            return frozenset({s.name_node.id})
        return own_name_ids(s.defn, self.name_field) if s.exclude_own_name else frozenset()

    def content_hash_of(self, symbol_id: str, relpath: str, source: bytes) -> str | None:
        """The current astnorm ``content_hash`` of ``symbol_id`` in ``source`` (``None`` if absent)."""
        node = self.extract_file(relpath, source).nodes.get(symbol_id)
        return node.get("content_hash") if node else None
