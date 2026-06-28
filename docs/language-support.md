# Language support — the tested capability matrix

What "16 languages" actually means, per capability, **asserted by tests** (not a marketing count). Every
✓ below is exercised by a test; every `—` is a deliberate non-capability (the language's
module/type system doesn't have that concept, so claiming it would invent false edges).

yigraf indexes at two tiers: **bespoke** extractors (Python/Go/JS-TS — hand-written, the deepest) and
the **tags-query** tier (everything else — one generic extractor + per-language enrichment). Governance
(link a task/intent to a symbol, detect drift on edit) works on *symbols* + *drift*, which every tier has.

| Language | symbols | calls | imports | inheritance | drift |
|---|:---:|:---:|:---:|:---:|:---:|
| Python | ✓ | ✓ | ✓ | ✓ | ✓ |
| Go | ✓ | ✓ | ✓ | ✓ (embedding) | ✓ |
| JavaScript | ✓ | ✓ | ✓ | ✓ | ✓ |
| TypeScript | ✓ | ✓ | ✓ | ✓ | ✓ |
| Rust | ✓ | ✓ | ✓ (`mod`) | ✓ (`impl`/trait) | ✓ |
| Java | ✓ | ✓ | ✓ (package) | ✓ | ✓ |
| C | ✓ | ✓ | ✓ (`#include`) | — | ✓ |
| C++ | ✓ | ✓ | ✓ (`#include`) | ✓ | ✓ |
| Ruby | ✓ | ✓ | ✓ (`require_relative`) | ✓ | ✓ |
| PHP | ✓ | —¹ | ✓ (`require`) | ✓ | ✓ |
| C# | ✓ | ✓ | —² | ✓ | ✓ |
| Kotlin | ✓ | ✓ | ✓ (package) | ✓ | ✓ |
| Scala | ✓ | ✓ | ✓ (package) | ✓ | ✓ |
| Swift | ✓ | ✓ | —² | ✓ | ✓ |
| Bash | ✓ | ✓ | — | — | ✓ |
| SQL | ✓ | — | — | — | ✓ (schema-change) |

**Legend:** ✓ = tested capability · — = not supported (by design).

- **drift** is the moat — a body edit must drift the symbol, a comment/reformat must not, and a rename must
  re-anchor. The full round-trip is asserted per language in `tests/test_language_drift.py`
  (`test_drift_round_trip_per_language`), with Go/TS in `test_languages.py`, Python in `test_extract.py`,
  and SQL schema-drift in `test_tags.py`.
- **imports / inheritance** breadth is asserted in `tests/test_language_drift.py::test_capability_matrix`
  (both directions — a `—` cell is verified *absent*).
- **calls** are intra-file, exact-or-drop (no cross-file call graph — that's CodeGraph's domain, not
  yigraf's; see `docs/research/codegraph-analysis.md`).

**Notes:**
1. PHP — the bundled tags query doesn't emit `@reference.call`, so intra-file calls aren't resolved yet
   (symbols/imports/inheritance/drift all work). A per-language `_extra_call_refs` hook would add it.
2. C# `using` names a *namespace* (spans many files; a file declares any namespace) and Swift `import`
   names a whole *module/framework* — neither maps to a file, so import **edges** can't be resolved without
   inventing false ones. (Bash/SQL have no import-to-file model either.)

**Quote handling (astnorm):** JS/TS/Python normalize `'`↔`"` (Prettier/Black flip them cosmetically, so a
flip must NOT drift). Ruby/PHP do **not** — there `'…'` (literal) and `"…"` (interpolating) differ
semantically, so a quote flip **is** real drift. Both directions are pinned in `test_language_drift.py`.
