# yigraf — M1 Implementation Notes (structure index)

> Pins the load-bearing M1 decisions **before** code, because the drift anchor is **irreversible by
> default**: change the normalization rule later and every stored anchor silently mismatches. Governed
> by `DESIGN.md` (R4/R5 drift, R10 normalization); builds the structure family in `docs/graph-design.md`
> §1–§2 and the M1 milestone in `docs/BUILD-PLAN.md`. Reuses Graphify's extractor approach.

## 1. Dependencies & parser API (validated)

- **Core + grammar:** `tree-sitter>=0.23,<0.25` + `tree-sitter-python>=0.23,<0.25` — **core
  dependencies**, not an extra (the structure graph is foundational). Resolved to `tree-sitter 0.24.0`
  + `tree-sitter-python 0.23.6` (ABI-compatible).
- **Python only for v0**; multi-language grammars come post-v0 (`BUILD-PLAN` sequencing). Keep the
  grammar pluggable so a language pack drops in later.
- **API shape (modern, ≥0.22):** `lang = Language(tree_sitter_python.language()); parser = Parser(lang)`.
  *Not* the legacy `Language(path, name)` / `parser.set_language(...)` forms.

## 2. What gets extracted (nodes & ids)

Per `graph-design.md` §1. **Python-only v0 symbol kinds**, mapped to tree-sitter node types:

| node | tree-sitter source | id (casefold-normalized) |
| --- | --- | --- |
| `file` | the source file | `file:<path>` |
| `module` | `module` (file top level) | `module:<path>` |
| `symbol` (`function`) | top-level `function_definition` (+ wrapping `decorated_definition`) | `sym:<path>#<name>` |
| `symbol` (`class`) | `class_definition` | `sym:<path>#<Class>` |
| `symbol` (`method`) | `function_definition` directly inside a class `block` | `sym:<path>#<Class>.<name>` |

**Not separate nodes in v0:** nested/local functions, comprehensions, lambdas — their tokens stay in
the enclosing symbol's content (so they ride that symbol's hash). Structural edges
(`contains`/`calls`/`imports`) per `graph-design.md` §2; all structure nodes/edges are `EXTRACTED`.

## 3. The two hashes — keep them distinct

| hash | over what | purpose | where |
| --- | --- | --- | --- |
| **file cache SHA** | raw file **bytes**, SHA-256 | skip re-extracting unchanged files (cache hit ⇒ byte-identical graph) | `yigraf/cache/` (gitignored) |
| **`content_hash` (the anchor)** | the symbol's **AST-normalized token stream** (§4) | drift detection on `implements`/`concerns` edges | on the structure node + copied to the edge as `anchor` |

The cache SHA is about *files changed*; the `content_hash` is about *a symbol's body meaningfully
changed*. A comment-only edit changes the file bytes (cache miss → re-extract) but **must not** change
any `content_hash` (no drift). This is the M1 done-test.

## 4. The normalization rule (R10 — pinned, versioned)

`content_hash(symbol)` = `SHA-256` over a deterministic serialization of the symbol's **significant
token stream**, computed as:

1. **Walk the symbol's AST subtree** in pre-order.
2. **Drop `comment` nodes entirely.** (The explicit done-test: comment-only edits don't trip drift.)
3. **Drop docstrings** — the leading `string` expression-statement of a module / class / function
   body. (Treated like comments: doc-only edits are maintenance, and a real contract change also
   changes code, which trips drift anyway. String literals used as *values* stay significant.)
4. **Exclude nested *extracted-symbol* subtrees**, replacing each with a stable marker
   `<def:NAME>` (the nested symbol's local name). So:
   - a **class** hash captures its decorators, bases, class-var assignments, and the *set of member
     names* — **not** method bodies. Editing a method body flips **only that method's** hash, never
     the class's (satisfies "a body change flips *exactly that* symbol's hash"). Add/remove/rename a
     member → the marker set changes → the class hash flips (a real structural change).
   - a **module** hash captures imports + top-level statements + the *set of top-level def/class
     names*, not their bodies.
   - a **function/method** hash includes everything in its body *except* comments and a leading
     docstring (local helper functions are **not** extracted nodes, so their tokens are included —
     they're part of the body).
4b. **Exclude the symbol's *own* declared name** (the `def NAME` / `class NAME` identifier; added
   2026-06-24 for M3). A pure rename then leaves the body-hash **unchanged**, so a moved/renamed
   locator re-anchors by exact content match instead of false-drifting (`docs/m3-notes.md` §2/§3).
   This is the symbol's *own* name only — a **container** still emits its members' names in the
   `<def:NAME>` markers above, so renaming a member is still a (real) structural change to the
   enclosing class/module hash. Safe to refine in `astnorm-v1` (no anchors persisted yet).
5. **Normalize string quote style** — when emitting a `string`'s `string_start`/`string_end`,
   canonicalize the quote *character* (single↔double) to double, **preserving the prefix** (`r`/`b`/
   `f`) and the **quote count** (do *not* collapse `'''`↔`'`, which can change semantics).
   `string_content` is emitted verbatim. (Kills the dominant `black` quote-flip false-drift source.)
6. **For each remaining leaf token**, emit `<node_type>\x1f<token_text>`; **join tokens with `\x1e`**;
   encode UTF-8; `SHA-256`; store hex. (Emitting `node_type` too keeps structurally-different code
   with identical text — rare — distinguishable.)

**Consequences of the rule (deliberate):**
- **Ignored (no drift):** comments; **docstrings**; **string quote-style** (`'x'` ≡ `"x"`); all
  whitespace, indentation, blank lines, line breaks, and reformatting that doesn't change the parsed
  token stream. A `black`/`isort` reflow — including its quote normalization — is **safe**. This is
  the deliberate defense against mass-reformat alert fatigue (R10).
- **Trips drift (intended):** any change to identifiers, operators, literal *values*, keywords,
  control flow, signatures/params, or decorators within the symbol's own body.
- **Deferred to a possible `astnorm-v2` (rare; the version tag lets us add without false mismatches):**
  - **Escape-level / decoded-value canonicalization** — e.g. `'it\'s'` → `"it's"` (black avoids the
    escape by switching quotes) still changes `string_content`, so it trips drift in v1. Handling it
    means decoding string values, which v1 deliberately skips.

**Versioning (this is what makes it *not* irreversible):** store
`anchor_algo: "astnorm-v1"` alongside each anchor. The drift check compares hashes **only when the
algo matches**; a future rule change bumps the tag (`astnorm-v2`) and edges re-anchor on next commit
instead of silently false-drifting. Cheap insurance against the one decision we most feared locking.

## 5. Out of scope for M1 (handled elsewhere — don't fold in)

- **Rename / move** of a symbol → **not** a hash concern. The locator (`path#name`) changes; M3
  resolves it via tree-sitter identity + similarity and **auto-re-anchors** (R4). M1 only produces a
  correct hash for a *resolved* locator.
- **Semantic equivalence** (e.g., `x+1` vs `1+x`, refactors that preserve behavior) — we are
  **token-level only**, by design. Such edits *do* trip soft drift; "re-verify" is the cheap, honest
  response.
- **Cross-file moves, multi-language, the git post-commit hook** — M3 / M2 / later.

## 6. Determinism requirement (M1 done-test)

Re-running extraction with no source change must yield a **byte-identical `graph.json`** (cache hit).
So the writer **sorts nodes and edges by id** (and edge tuples by `(src, relation, dst)`) before
serializing, and uses stable key ordering. No timestamps or run-dependent fields in the
content/edge projection (runtime counters live separately per R1).
