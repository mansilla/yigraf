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

The module also owns the two *non-AST* anchor algorithms, because "compare like against like" is one
rule and it belongs in one place: :data:`FILE_ANCHOR_ALGO` (raw bytes, for a file or a line range) and
:data:`SECTION_ANCHOR_ALGO` (``mdsec-v1``: one markdown heading's normalized section — see
:func:`section_content_hash`, which restates astnorm's own rules for prose).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from tree_sitter import Node

#: Version tag stored alongside every anchor. Bumping it (``astnorm-v2``) re-anchors instead of
#: silently false-drifting against hashes produced by an older rule (docs/m1-notes.md §4).
ANCHOR_ALGO = "astnorm-v1"

#: Anchor algo for a ``file:`` target (friend-review #12): a raw SHA-256 of the file bytes (or a line
#: range), for infra/glue files (Dockerfile, buildspec, cdk.json, *.sh) that have no code symbols. A
#: distinct algo so drift compares a file anchor only against a file node's hash, never an astnorm one.
FILE_ANCHOR_ALGO = "file-sha256-v1"

#: Anchor algo for a ``file:<path>#<heading>`` **section** target (feedback-v4 #6): a SHA-256 over one
#: heading's *normalized* section, not its raw bytes — so it needs its own tag, distinct from
#: ``FILE_ANCHOR_ALGO``. It exists because a line range is a **positional** address and prose moves:
#: inserting a paragraph above a governed section false-drifts it, ``reaffirm`` then re-stamps the hash
#: of the WRONG lines while reporting success, and a later rewrite of the actual governed claim drifts
#: nothing at all — a false negative in the moat, not a nag (mem:a65f1ccad03b765e).
SECTION_ANCHOR_ALGO = "mdsec-v1"

#: Suffixes whose headings ``mdsec-v1`` can address. Markdown only: the algorithm reads ATX headings
#: and fenced code, which is a markdown grammar — accepting ``.rst``/``.adoc`` would mint addresses
#: that silently never resolve.
DOC_SUFFIXES = frozenset({".md", ".markdown", ".mdx"})

_FILE_RANGE = re.compile(r"^(.*):L(\d+)-L?(\d+)$")  # file:path:L10-L40 (or L10-40)


def _split_fragment(spec: str) -> tuple[str, str | None]:
    """Split a bare ``<path>[#<section>]`` spec, taking the **last** ``#`` and only when what precedes
    it looks like a filename with an extension.

    Both conditions earn their keep on real paths. A file genuinely named ``C#-notes.txt`` was made
    unanchorable by an unconditional split — refused as "``C`` is not markdown", advising a path that
    does not exist, and silently dropping any anchor already stored on it (D8). Splitting on the last
    ``#`` keeps ``C#-notes.md#intro`` working; requiring an extension keeps ``C#-notes.md`` a path. And
    ``cfg.txt#top`` still reads as an attempted section, so the "not markdown, use a line range"
    guidance still fires where it helps.
    """
    prefix, sep, frag = spec.rpartition("#")
    if sep and frag and prefix and PurePosixPath(prefix).suffix:
        return prefix, frag
    return spec, None


def parse_file_target(target: str) -> tuple[str, int | None, int | None]:
    """Split ``file:<path>[:L<a>-L<b>][#<section>]`` into ``(relpath, start, end)`` (1-based, inclusive).

    A ``#<section>`` fragment is stripped from ``relpath`` and yields ``(relpath, None, None)`` — it
    addresses a heading, not a line range. Every existing caller wants exactly that: the path on disk,
    for an existence check or a node's ``source_file``. Callers that need the fragment itself use
    :func:`parse_section_target`.
    """
    spec = target[len("file:"):] if target.startswith("file:") else target
    spec = _split_fragment(spec)[0]
    match = _FILE_RANGE.match(spec)
    if match is None:
        return spec, None, None
    return match.group(1), int(match.group(2)), int(match.group(3))


def parse_section_target(target: str) -> tuple[str, str | None]:
    """Split ``file:<path>#<slug>`` into ``(relpath, slug)``; ``slug`` is ``None`` for any other form.

    The ``file:`` prefix is **required** for the fragment to count, because ``#`` already separates a
    symbol from its path: without that guard ``sym:auth/session.py#refresh`` reads as a section of
    ``auth/session.py`` and every ``sym:`` guidance surface answers about headings.

    The slug is returned **as typed**, never case-folded: the locator string *is* the node id, so
    accepting ``#Drift`` and ``#drift`` as the same locus would split one section's identity across two
    nodes. One spelling is canonical and ``cli._anchor`` guides a near miss to it (design law #1).
    """
    if not target.startswith("file:"):
        return target, None
    return _split_fragment(target[len("file:"):])


def file_content_hash(root: Path, target: str) -> str | None:
    """SHA-256 anchor for a ``file:`` target (whole file, or a ``:L<a>-L<b>`` slice); ``None`` if absent.

    Unlike :func:`content_hash`, this is a raw byte hash — no AST normalization, because these targets
    are files with no parsed symbol structure. A line range hashes only those lines, so an unrelated
    edit elsewhere in the file doesn't drift a region-scoped decision (friend-review #12/#13).
    """
    relpath, start, end = parse_file_target(target)
    path = Path(root) / relpath
    if not path.is_file():
        return None
    data = path.read_bytes()
    if start is not None:
        data = b"\n".join(data.split(b"\n")[start - 1:end])
    return hashlib.sha256(data).hexdigest()

#: Field separators for the token stream, shared by ``astnorm-v1`` and ``mdsec-v1``. ``\x1f`` (unit)
#: joins a token's type to its text; ``\x1e`` (record) joins tokens. Both are control chars no source
#: file carries in practice, so a literal's — or a paragraph's — contents can't forge a boundary. For
#: code that is a guarantee (a parser would reject them); for prose it is a property of real documents,
#: and the failure it protects against is a hash collision between two texts, not a security boundary.
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


# ── mdsec-v1: a markdown heading's section as a drift anchor (feedback-v4 #6) ─────────────────────

#: A fenced code block's delimiter: 3+ backticks or tildes, indented at most 3 spaces (CommonMark).
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*(.*)$")

#: An ATX heading: 1-6 ``#`` indented at most 3 spaces, then whitespace and the title (CommonMark).
#: ``#!/bin/sh`` is correctly not a heading — the ``#`` must be followed by whitespace or end of line.
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")

#: A heading's optional closing sequence (``## Drift ##``) — only a run of ``#`` preceded by space.
_CLOSING_HASHES = re.compile(r"[ \t]+#+$")

_SLUG_NOISE = re.compile(r"[^a-z0-9]+")

#: The hash every *empty* section produces (no body at all → an empty token stream). Excluded from
#: rename matching, because it identifies nothing: a stub heading is common in real documents, so every
#: one of them collides with every other, and "exactly one survivor carries the stored anchor" then
#: resolves a DELETED section to whichever stub happens to remain (D1). Content-hash identity needs
#: content.
EMPTY_SECTION_HASH = hashlib.sha256(b"").hexdigest()

#: Block-start markers. A *continuation* line joins the block above it — that is what makes a rewrap
#: invisible — so the hash needs to know which lines genuinely start something new. Checked in this
#: order: ``- - -`` is a thematic break, not a list item, and both patterns accept it.
_BREAK = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_LIST = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)")
_QUOTE = re.compile(r"^ {0,3}>")
_TABLE = re.compile(r"^ {0,3}\|")

#: One level of blockquote marker, stripped from a quote block's *continuation* lines so a rewrapped
#: callout is not a change. The block's FIRST line keeps its marker, so un-quoting the text still
#: drifts; stripping only one level keeps a nested ``>>`` visible.
_QUOTE_MARK = re.compile(r"^ {0,3}> ?")

#: An indented code block needs 4 spaces — but only where a paragraph isn't already open, which is
#: CommonMark's own condition and the one :func:`_hash_section` applies.
_CODE_INDENT = 4

#: A **setext** underline: a run of ``=`` (depth 1) or ``-`` (depth 2) on its own line, which turns the
#: paragraph above it into a heading. Recognized because ignoring it corrupted *extents*, not merely
#: addresses: a section's end is the next heading at its depth or shallower, so a document mixing
#: setext top-level headings with ATX sub-headings let one section swallow a later one's prose (D7,
#: over-sensitive) and hid a setext sibling from its parent's subsection markers (D2, a false
#: negative against the documented "adding, renaming or removing a subsection drifts the parent").
#: Checked BEFORE :data:`_BREAK`, which also matches ``---`` — CommonMark gives setext precedence when
#: a paragraph is open, and a thematic break when one is not.
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")

#: An HTML block comment (CommonMark block type 2): the line must *begin* with ``<!--``, and the block
#: runs to the line containing ``-->``. Skipped like a fence, because a commented-out ``## Old wording``
#: was read as a real heading and **ended** the governed section there — after which the prose below it
#: could be reversed in silence (D6).
_HTML_COMMENT_OPEN = re.compile(r"^ {0,3}<!--")

#: A YAML front-matter fence: ``---`` on the very first line, closed by ``---`` or ``...``. Skipped
#: entirely so a ``#`` comment in it is not a phantom heading (D9) and so the closing fence is not read
#: as a setext underline for the metadata line above it. Nothing addressable can precede it, so
#: skipping cannot change any section's hash.
_FRONT_MATTER = re.compile(r"^(---|\.\.\.)[ \t]*$")


def section_slug(title: str) -> str:
    """The addressable slug for a heading title: case-folded, every run of other characters → one ``-``.

    Deliberately *not* GitHub's rule, which preserves a ``-`` per punctuation character (so ``The
    --governs flag`` becomes ``the---governs-flag``). The audience is an agent typing a locator, not a
    browser following an anchor link, so the collapsing rule is the one a caller can actually guess —
    and when a guess still misses, ``cli._anchor`` prints the file's real slugs (design law #1).
    """
    return _SLUG_NOISE.sub("-", title.casefold()).strip("-")


@dataclass(frozen=True)
class _Heading:
    index: int  # 0-based line index where the heading STARTS (a setext heading's text, not its rule)
    depth: int  # 1..6
    slug: str
    body_start: int  # first line after the heading — ``index + 1`` for ATX, past the rule for setext


@dataclass(frozen=True)
class _Section:
    slug: str
    start: int  # the line the heading starts on
    body_start: int  # first line of the body — the heading's own text is never hashed
    end: int  # exclusive — the next heading at depth <= this one, or EOF
    depth: int


def _line_kind(line: str) -> str:
    """Classify one non-fenced, non-heading line by the block it starts, or ``"text"`` if it continues.

    Only ``"text"`` (and, per its own kind, a ``quote`` or ``table`` line) joins the block above it.
    ``list`` deliberately does not: two items are two things, so splitting one must drift.
    """
    if not line.strip():
        return "blank"
    if _BREAK.match(line):
        return "break"
    if _LIST.match(line):
        return "list"
    if _QUOTE.match(line):
        return "quote"
    if _TABLE.match(line):
        return "table"
    return "text"


def _scan(text: str) -> tuple[list[str], list[str], list[_Heading]]:
    """Split ``text`` into lines, a per-line block kind, and the headings found in real content.

    Three states are tracked over the **whole file**, not per section, because each one can otherwise
    put a heading where the document has none — and a phantom heading *ends* the section it lands in,
    which silences every edit below it:

    * **fences** — a ``#`` inside a fenced block is code, so a shell comment in an example would read
      as a heading;
    * **HTML comments** — a commented-out ``## Old wording`` is not a heading (D6);
    * **front matter** — a ``#`` comment in it is not a heading, and its closing ``---`` is not a
      setext rule for the metadata line above (D9).

    Setext headings (``Title`` over ``===`` / ``---``) are recognized as headings, which is what keeps
    section *extents* right in a document that mixes them with ATX (D2/D7). A setext heading spans its
    paragraph *and* its rule, so it records a ``body_start`` past both; for ATX the two are adjacent.
    """
    lines = text.splitlines()
    kinds = ["text"] * len(lines)
    headings: list[_Heading] = []
    fence: str | None = None
    skip_to: str | None = None  # closing token of an open HTML comment / front-matter block
    para: list[int] = []  # line indices of the open paragraph — a setext heading's text
    i = 0
    while i < len(lines):
        line = lines[i]

        if skip_to is not None:  # inside an HTML comment or front matter: content, never structure
            kinds[i] = "skip"
            if (_FRONT_MATTER.match(line) if skip_to == "---" else skip_to in line):
                skip_to = None
            i += 1
            continue

        delim = _FENCE.match(line)
        if fence is not None:
            kinds[i] = "fence"  # delimiters included: open-to-close is one verbatim run
            if (delim is not None and delim.group(1)[0] == fence[0]
                    and len(delim.group(1)) >= len(fence) and not delim.group(2)):
                fence = None
            i += 1
            continue
        if delim is not None:
            fence, kinds[i], para = delim.group(1), "fence", []
            i += 1
            continue

        if i == 0 and _FRONT_MATTER.match(line) and line.strip() == "---":
            # Only at the very top, and only if it actually closes — otherwise a lone `---` on line 1
            # is a thematic break and swallowing the file would hide every heading in it.
            if any(_FRONT_MATTER.match(later) for later in lines[1:]):
                kinds[i], skip_to = "skip", "---"
                i += 1
                continue
        if _HTML_COMMENT_OPEN.match(line):
            kinds[i], para = "skip", []
            skip_to = None if "-->" in line else "-->"
            i += 1
            continue

        atx = _ATX.match(line)
        title = _CLOSING_HASHES.sub("", atx.group(2) or "").strip() if atx is not None else ""
        if title:  # a bare ``##`` has no title, so it has no address
            headings.append(_Heading(i, len(atx.group(1)), section_slug(title), i + 1))
            kinds[i], para = "heading", []
            i += 1
            continue

        rule = _SETEXT.match(line)
        if rule is not None and para:
            # The paragraph above becomes the heading text; its lines and this rule stop being body.
            depth = 1 if rule.group(1)[0] == "=" else 2
            text_of = " ".join(" ".join(lines[j] for j in para).split())
            headings.append(_Heading(para[0], depth, section_slug(text_of), i + 1))
            for j in (*para, i):
                kinds[j] = "heading"
            para = []
            i += 1
            continue

        kinds[i] = _line_kind(line)
        para = [*para, i] if kinds[i] == "text" else []
        i += 1
    return lines, kinds, headings


def _sections(lines: list[str], headings: list[_Heading]) -> list[_Section]:
    """Each heading's extent: to the next heading at the same or a shallower depth, else end of file.

    The boundary is the next heading's ``index`` — where it *starts* — so a setext heading's own text
    lines fall outside the section above it rather than being hashed as that section's last paragraph.
    """
    out: list[_Section] = []
    for k, head in enumerate(headings):
        end = next((h.index for h in headings[k + 1:] if h.depth <= head.depth), len(lines))
        out.append(_Section(head.slug, head.index, head.body_start, end, head.depth))
    return out


def _hash_section(lines: list[str], kinds: list[str], headings: list[_Heading],
                  sec: _Section) -> str:
    """SHA-256 over one section's normalized token stream; see :func:`section_content_hash`.

    One token per *block*, not per line. Joining a block's continuation lines is what makes a rewrap
    invisible — and a rewrap (Prettier's markdown printer, ``fmt``, an editor's hard wrap) is to prose
    what a ``black`` reflow is to code: the dominant false-drift source, changing nothing. Per-line
    tokens looked equivalent and were not: re-wrapping one sentence across two lines drifted it.
    """
    by_line = {h.index: h for h in headings}
    tokens: list[str] = []
    block: list[str] = []
    block_kind: str | None = None

    def flush() -> None:
        nonlocal block, block_kind
        if block:
            tokens.append(f"text{_FIELD}{' '.join(' '.join(block).split())}")
        block, block_kind = [], None

    i = sec.body_start  # the section's OWN heading is excluded — that is what survives a rename
    while i < sec.end:
        child = by_line.get(i)
        if child is not None:
            flush()
            tokens.append(f"<sec:{child.slug}>")  # a directly nested subsection: its body is its own
            i = child.body_start
            while i < sec.end and not (i in by_line and by_line[i].depth <= child.depth):
                i += 1
            continue
        line, kind = lines[i], kinds[i]
        if kind == "skip":
            flush()  # an HTML comment or front matter: not content, and never a heading
        elif kind == "fence":
            flush()
            tokens.append(f"code{_FIELD}{line}")  # verbatim: indentation is semantic in a sample
        elif kind == "blank":
            flush()
        elif kind == "break":
            flush()
            tokens.append(f"break{_FIELD}{line.strip()}")
        elif kind == "list":
            flush()  # two items are two things: splitting one must drift, so it never continues
            block, block_kind = [line], "list"
        elif kind in ("quote", "table"):
            continuing = block_kind == kind
            if not continuing:
                flush()
                block_kind = kind
            # Consecutive ``>``/``|`` lines are ONE block, so a rewrap is safe. A quote's continuation
            # lines shed their marker as well, or the interior ``>`` would itself be the change when a
            # two-line callout is re-wrapped onto one. The first line keeps it, so un-quoting drifts.
            block.append(_QUOTE_MARK.sub("", line) if continuing and kind == "quote" else line)
        elif not block and len(line) - len(line.lstrip(" ")) >= _CODE_INDENT:
            # An indented code block — only reachable with no paragraph open, CommonMark's own rule.
            # Where the guess is wrong (deep list content after a blank line) it errs verbatim, i.e.
            # over-sensitive: the wrong direction to err is collapsing a code sample's indentation.
            flush()
            tokens.append(f"code{_FIELD}{line}")
        else:
            block_kind = block_kind or "text"
            block.append(line)
        i += 1
    flush()
    return hashlib.sha256(_TOKEN.join(tokens).encode("utf-8", "surrogatepass")).hexdigest()


def _read_sections(root: Path, relpath: str):
    """``(lines, kinds, headings, sections)`` for a markdown file, or ``None`` if it isn't there."""
    path = Path(root) / relpath
    if not path.is_file():
        return None
    lines, kinds, headings = _scan(path.read_text(encoding="utf-8", errors="replace"))
    return lines, kinds, headings, _sections(lines, headings)


def section_slugs(root: Path, relpath: str) -> list[str]:
    """Every addressable heading slug in a markdown file, in document order (duplicates kept).

    Duplicates are kept because they are the signal: two headings with one slug make that slug
    unaddressable, and ``cli._anchor`` refuses it rather than picking one (which would silently anchor
    a belief to whichever section happened to come first).
    """
    read = _read_sections(root, relpath)
    return [s.slug for s in read[3]] if read is not None else []


def section_content_hash(root: Path, target: str) -> str | None:
    """``mdsec-v1`` anchor for ``file:<path>#<slug>``; ``None`` if the file, or a *unique* section with
    that slug, isn't there.

    Every normalization rule is one astnorm already applies to code, restated for prose:

    * the section's **own heading text is excluded**, exactly as :func:`content_hash`'s ``exclude``
      drops a symbol's declared name — so renaming the heading leaves the hash intact, which is what
      lets :func:`section_locator_for_anchor` resolve the move instead of reporting hard drift
      (int:drift-detection: SHALL NOT flag a pure rename);
    * each **directly nested subsection** collapses to a ``<sec:slug>`` marker and is not descended
      into, exactly as a nested symbol becomes ``<def:NAME>`` — so editing prose under ``### Soft
      drift`` never drifts ``## Drift``, while adding, removing or renaming a subsection does (a
      container's hash captures its members' names, not their bodies);
    * **each block becomes one whitespace-collapsed token**, the prose analogue of quote
      canonicalization: a rewrap is to text what a ``black`` reflow is to code — the dominant
      false-drift source, changing nothing — so a paragraph's or a list item's continuation lines are
      joined before hashing. Inside a fence (or an indented code block) every byte is kept:
      indentation is semantic in a sample, and equating two different samples would be a false
      negative in the one part of a doc that is precise. A new list item, table row or thematic break
      is its own token, so adding one still drifts.

    Heading *depth* is deliberately not hashed: promoting a whole document one level is a reflow-class
    edit, and where a depth change really alters what a section contains, its body tokens move anyway.
    """
    relpath, slug = parse_section_target(target)
    if slug is None:
        return None
    read = _read_sections(root, relpath)
    if read is None:
        return None
    lines, kinds, headings, sections = read
    matches = [s for s in sections if s.slug == slug]
    if len(matches) != 1:
        return None  # absent, or ambiguous — cli._anchor tells those apart and guides each
    return _hash_section(lines, kinds, headings, matches[0])


def section_locator_for_anchor(root: Path, relpath: str, anchor: str) -> str | None:
    """The ``file:<relpath>#<slug>`` whose section hashes to ``anchor``, when exactly one does.

    The section counterpart of astnorm's rename re-anchoring, and the reason a heading's own text sits
    outside the hash. Symbols get this for free: the extractor indexes every symbol, so a renamed one
    is already a node ``drift._hash_index`` can find. Docs are deliberately **not** indexed
    (mem:a65f1ccad03b765e keeps that — a repo whose docs nobody governs pays nothing), so nothing mints
    a node under the heading's new name. Resolving the move from the stored anchor at projection time
    is what lets a rename land as ``renamed`` rather than hard drift, with no doc-wide index.

    Two sections that hash alike (two empty ones, say) return ``None`` — ambiguous, so not guessed,
    the same rule ``drift.resolve_renames`` applies to an ambiguous symbol hash.
    """
    read = _read_sections(root, relpath)
    if read is None:
        return None
    lines, kinds, headings, sections = read
    if anchor == EMPTY_SECTION_HASH:
        return None  # an empty section identifies nothing — see :data:`EMPTY_SECTION_HASH`
    hits = [s.slug for s in sections if _hash_section(lines, kinds, headings, s) == anchor]
    return f"file:{relpath}#{hits[0]}" if len(hits) == 1 else None


def locus_hash(root: Path, target: str) -> tuple[str | None, str | None]:
    """``(hash, algo)`` for any ``file:`` form — section, line range, or whole file; ``(None, None)``
    if it doesn't resolve.

    One dispatcher, so every site that stamps or re-derives a file anchor (``cli._anchor``, the
    ``reaffirm`` re-stamp, and the two projectors) routes the section form to ``mdsec-v1`` and the
    other two to the raw byte hash. The algo travels with the hash so ``drift`` keeps comparing like
    against like.
    """
    if parse_section_target(target)[1] is not None:
        anchor, algo = section_content_hash(root, target), SECTION_ANCHOR_ALGO
    else:
        anchor, algo = file_content_hash(root, target), FILE_ANCHOR_ALGO
    return (anchor, algo) if anchor is not None else (None, None)
