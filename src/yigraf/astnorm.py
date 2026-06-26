"""AST-normalized ``content_hash`` — the drift anchor (``astnorm-v1``).

A symbol's ``content_hash`` is a SHA-256 over its *significant token stream*: the tokens that remain
after dropping comments and docstrings, normalizing string quote style, and replacing each nested
*extracted* symbol with a stable ``<def:NAME>`` marker. The rule is pinned in ``docs/m1-notes.md`` §4
and is **load-bearing**: once anchors are stamped (M2), changing the rule silently mismatches every
stored anchor — so the algorithm carries a version tag (:data:`ANCHOR_ALGO`). A future rule change
bumps the tag and re-anchors on next commit instead of false-drifting.

What is deliberately ignored (no drift): comments, docstrings, string quote style (``'x'`` ≡ ``"x"``),
and all whitespace/reformatting that doesn't change the parsed token stream — so a ``black``/``isort``
reflow is safe. What trips drift (intended): any change to identifiers, operators, literal *values*,
keywords, control flow, signatures, or decorators within a symbol's own body.
"""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from tree_sitter import Node

#: Version tag stored alongside every anchor. Bumping it (``astnorm-v2``) re-anchors instead of
#: silently false-drifting against hashes produced by an older rule (docs/m1-notes.md §4).
ANCHOR_ALGO = "astnorm-v1"

#: Field separators for the token stream. ``\x1f`` (unit) joins a token's type to its text; ``\x1e``
#: (record) joins tokens. Both are control chars that cannot occur in Python source, so they can't be
#: forged by a literal's contents.
_FIELD = "\x1f"
_TOKEN = "\x1e"

#: Python defaults for the per-language astnorm knobs. They are the function defaults below, so a
#: caller that passes nothing reproduces the original Python rule byte-for-byte (no ``astnorm-v2``
#: bump, existing anchors stay valid). Other languages pass their own sets (e.g. Go: all empty — no
#: docstrings, no quote-style ambiguity), keeping the *algorithm* astnorm-v1 while varying the
#: language-specific token vocabulary it normalizes.

#: Token types whose text is a quote delimiter (prefix + quotes) we canonicalize.
_PY_QUOTE_TOKENS = frozenset({"string_start", "string_end"})

#: Block-like containers whose *leading* string statement is a docstring to drop.
_PY_BODY_CONTAINERS = frozenset({"block", "module"})

#: Node types that count as a lone string statement (a docstring) inside a body container.
_PY_DOCSTRING_TYPES = frozenset({"string", "concatenated_string"})

#: Node types dropped as comments. Default fits Python/Go/JS/C; languages whose grammar names them
#: differently (Rust/Java: ``line_comment``/``block_comment``) pass their own set.
_PY_COMMENT_TYPES = frozenset({"comment"})


def content_hash(node: Node, source: bytes, boundaries: Mapping[int, str],
                 exclude: frozenset[int] = frozenset(), *,
                 quote_tokens: frozenset[str] = _PY_QUOTE_TOKENS,
                 body_containers: frozenset[str] = _PY_BODY_CONTAINERS,
                 docstring_types: frozenset[str] = _PY_DOCSTRING_TYPES,
                 comment_types: frozenset[str] = _PY_COMMENT_TYPES) -> str:
    """Hash ``node``'s significant token stream (``astnorm-v1``); see module docstring.

    ``boundaries`` maps the tree-sitter node id of each *directly nested extracted symbol* (a
    top-level def for a module; a method for a class) to its local name. Those subtrees are replaced
    by a ``<def:NAME>`` marker and not descended into — so a class hash captures its member *names*
    but not method bodies, and editing a method body flips only that method's hash.

    ``exclude`` is a set of node ids dropped outright — used for the symbol's **own declared name**,
    so a pure rename leaves the body-hash unchanged and M3 can re-anchor by exact match
    (docs/m3-notes.md §2). A *container's* member names (the ``<def:NAME>`` markers) are unaffected.

    ``quote_tokens`` / ``body_containers`` / ``docstring_types`` are the per-language knobs (default:
    Python). Empty sets disable quote canonicalization / docstring dropping for languages that have
    neither (e.g. Go), while the rest of the algorithm — and ``ANCHOR_ALGO`` — is unchanged.
    """
    tokens: list[str] = []
    _emit(node, source, boundaries, exclude, tokens, quote_tokens, body_containers, docstring_types,
          comment_types)
    blob = _TOKEN.join(tokens).encode("utf-8", "surrogatepass")
    return hashlib.sha256(blob).hexdigest()


def _emit(node: Node, source: bytes, boundaries: Mapping[int, str], exclude: frozenset[int],
          out: list[str], quote_tokens: frozenset[str], body_containers: frozenset[str],
          docstring_types: frozenset[str], comment_types: frozenset[str]) -> None:
    """Append ``node``'s significant tokens to ``out`` in pre-order."""
    if node.id in exclude:
        return  # the symbol's own name — dropped so a rename doesn't change the body-hash

    name = boundaries.get(node.id)
    if name is not None:
        out.append(f"<def:{name}>")  # nested extracted symbol — its body is its own concern
        return

    kind = node.type
    if kind in comment_types:
        return

    if node.child_count == 0:
        text = source[node.start_byte : node.end_byte].decode("utf-8", "surrogatepass")
        if kind in quote_tokens:
            # Canonicalize the *kind* too: in some grammars (JS/TS) the delimiter's node type IS the
            # quote char (``"`` vs ``'``), so normalizing only the text would still differ by type.
            # On Python's ``string_start``/``string_end`` this is a no-op (no quote char in the name),
            # so existing anchors stay byte-identical.
            kind = _canon_quote(kind)
            text = _canon_quote(text)
        out.append(f"{kind}{_FIELD}{text}")
        return

    children = node.children
    if kind in body_containers:
        children = _without_leading_docstring(children, docstring_types)
    for child in children:
        _emit(child, source, boundaries, exclude, out, quote_tokens, body_containers, docstring_types,
              comment_types)


def _without_leading_docstring(children: list[Node], docstring_types: frozenset[str]) -> list[Node]:
    """Return ``children`` with a leading docstring statement removed, if present.

    A docstring is the first *statement* (comments don't count) of a body that is a bare string
    expression. Doc-only edits are maintenance; a real contract change also edits code, which trips
    drift anyway (docs/m1-notes.md §4).
    """
    for i, child in enumerate(children):
        if child.type == "comment":
            continue  # comments precede the docstring but aren't the first statement
        if child.type == "expression_statement" and _is_string_only(child, docstring_types):
            return children[:i] + children[i + 1 :]
        return children  # first real statement isn't a docstring
    return children


def _is_string_only(stmt: Node, docstring_types: frozenset[str]) -> bool:
    """True when an ``expression_statement`` is a lone string literal (a docstring)."""
    kids = stmt.children
    return len(kids) == 1 and kids[0].type in docstring_types


def _canon_quote(token: str) -> str:
    """Canonicalize a string delimiter: lowercase the prefix, force double quotes, keep quote count.

    ``r'''`` → ``r\"\"\"``, ``F"`` → ``f"``. Preserves the prefix letters (``r``/``b``/``f``) and the
    quote *count* (never collapses ``'''`` ↔ ``'``, which would change semantics). Kills the dominant
    ``black`` quote-flip false-drift source; ``string_content`` is emitted verbatim, so escape-level
    rewrites (``'it\\'s'`` → ``"it's"``) still trip drift and are deferred to a possible v2.
    """
    i = 0
    while i < len(token) and token[i] not in ("'", '"'):
        i += 1
    prefix, quotes = token[:i], token[i:]
    return prefix.lower() + quotes.replace("'", '"')
