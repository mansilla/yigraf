# yigraf — Caveats & Known Issues (running log)

> A running log of sharp edges, deliberate simplifications, and issues found *while implementing*
> the v0 milestones — distinct from the forward-looking "out of scope" sections in the `mN-notes`
> docs (which are planned deferrals). Each entry: what, why it's OK for now / when it bites, and the
> milestone that should address it. Newest findings appended per milestone.

## Severity key
- 🔴 **bug / correctness risk** — could give a wrong answer; fix before relying on it.
- 🟡 **sharp edge** — correct under stated assumptions, surprising outside them.
- 🟢 **deliberate v0 simplification** — known gap, planned.

---

## M1 — structure index

- 🟡 **Path-only casefolding of ids.** Locator ids casefold the *path* (`file:src/yigraf/config.py`)
  but preserve the *symbol name* (`#Foo`). On a **case-sensitive** filesystem, two files differing
  only by case (`Config.py` vs `config.py`) would collide to one id; on macOS (case-insensitive, the
  dev target) they're already the same file. Deviates from m1-notes' "casefold-normalized" wording;
  chosen to avoid collapsing `class Foo` / `def foo` in one module. Revisit if Linux/CI case-folding
  matters. *(M4+ — case-insensitive matching belongs in retrieval, not ids.)*
- 🟢 **`imports` edges are intra-repo only.** External imports (stdlib/third-party) are recorded as a
  sorted file-node attribute but produce no edge (no phantom nodes). Relative imports (`from . import`)
  are skipped entirely. Resolution strips a leading `src/` for src-layout; other layouts won't resolve.
- 🟢 **`calls` resolution is shallow.** Only bare-name calls to top-level functions and `self.method`
  calls to sibling methods resolve. `obj.method()`, aliased imports, cross-file, and dynamic calls are
  dropped. Fine for a structure sketch; not a call graph.
- 🟢 **Python only.** Multi-language extraction is post-v0 (reuse Graphify's grammar breadth).

## M2 — intent/plan + linking

- 🟡 **post-commit hook leaves `graph.json` dirty unless you rebuild before committing.** The hook
  rebuilds `graph.json` *after* the commit, so a commit that changed code (and thus hashes) without a
  prior `yigraf build` leaves an uncommitted `graph.json`. Workflow: rebuild before commit (or accept
  the follow-up). Inherent to committing a derived artifact; revisit if it annoys in dogfood (M6).
- 🟡 **Anchor authoritative at `link` time, not commit (R11).** A symbol edited *after* `yigraf link`
  but before commit surfaces as drift (re-verify), rather than silently re-anchoring to the committed
  state. Deliberate (R9c-consistent) but differs from R5's literal "stamp at commit" — see
  m2-notes §4 / DESIGN R11.
- 🟢 **`tracks`/`requires` dangles aren't drift.** v0 is `implements`-only (R7); an unresolved
  `tracks`/`requires` target is silently a `dangling_*` stash with no surfacing yet.

## M3 — drift + rename

- 🟡 **Rename re-anchor is in-memory only; the plan `.md` keeps the stale locator.** Builds re-resolve
  deterministically (anchor = rename-invariant body-hash), so this is invisible *until* a renamed
  symbol is **then edited**: because the frontmatter still names the old locator, that shows as **hard**
  drift, not soft. Honest (relink fixes it) but coarser than ideal. A future `yigraf drift --fix`
  should persist the new locator. *(post-v0)*
- 🟡 **Identical-body collision (R10.1).** Because `content_hash` excludes the symbol's own name, two
  functions with byte-identical bodies hash the same. If one is deleted and exactly one other matches,
  the rename re-anchor will attach to that other symbol — a plausible false rename. Mitigated by the
  "unique match only" rule (≥2 matches → no guess, hard drift), but a 1-of-1 textual twin can mislead.
- 🟢 **Rename + body edit in one commit = hard drift.** No fuzzy similarity in v0 — only exact
  body-hash match re-anchors. The honest remedy is relink. Fuzzy identity is post-v0.
- 🟢 **drift is `implements`-only.** `concerns`/memory drift arrives with the memory milestone (R7).

## M4 — retrieval / `yigraf context`

- 🟡 **Token counts are estimated (char ≈ 3:1), not tokenized.** Good enough for budget cuts; the
  reported `~N tokens` can be off, especially for symbol-dense output. A real tokenizer is post-v0.
- 🟡 **`file:`/`module:` nodes clutter the `Code:` group.** Traversal pulls a symbol's containing
  file/module in via `contains`; they rank low but still render, adding noise next to the symbol that
  actually matched. Candidate fix: suppress a file/module node when a symbol from the same file is
  already shown. *(polish; M5/M6)*
- 🟡 **Lexical-only seeding misses pure-concept queries (R7).** A "why do we …" query that shares no
  identifier/term with the intent's `statement`/slug won't seed it. The semantic seeder (embeddings)
  is the memory-milestone fix; until then, phrase queries with words that appear in the spec text.
- 🟡 **Loose prefix matching.** Seed precedence treats `token.startswith(q) or q.startswith(token)`
  as a prefix hit, so a very short query term can over-match (e.g. `re` → `refresh`, `return`). IDF
  damps common terms but short queries are noisy. Acceptable for v0; revisit with the semantic seeder.
- 🟢 **`relevance` is `refs_in`/`superseded` only, recomputed per query.** Counters aren't materialized
  on nodes and recency/maturity aren't in the prior yet — both arrive with the memory milestone, when
  the telemetry sidecar exists.
- 🟢 **`verified` only inspects task→intent→symbol.** A hypothetical direct `intent → symbol`
  `implements` edge isn't considered for the R9c check; all v0 links are task-based, so moot for now.

## M5 — Claude Code hooks + skill

- 🔴 **`install-claude-hooks` bakes an absolute interpreter path into the *committed*
  `.claude/settings.json`.** `"/abs/path/.venv/bin/python" -m yigraf …` works on the author's machine
  but **breaks for teammates / CI** with a different venv path, and the command silently no-ops
  (fail-open) so the breakage is invisible. Fine for the single-dev dogfood. For shared repos this
  should instead go in the gitignored `.claude/settings.local.json`, or use a PATH-portable command
  (`yigraf hook …` or `uv run yigraf hook …`). **Fix before recommending to teams (M6/post-v0).**
- 🟡 **SessionStart fires on `startup|resume` too, not just `clear|compact`.** Every new session gets
  the active-plan injection, not only post-reset. Defensible as orientation, but it's more than R8's
  literal "survives /clear" scope and could feel noisy on a big plan. Narrow the matcher to
  `clear|compact` if so.
- 🟡 **PostToolUse rebuilds the graph on every Edit/Write.** The SHA cache means only the touched file
  re-parses, but the whole graph is still re-assembled + drift recomputed each edit — latency grows
  with repo size. Could instead load the committed `graph.json` and re-extract only the touched file.
  Measure in M6.
- 🟡 **`additionalContext`-on-PostToolUse injection is verified from docs, not yet from a live run.**
  The fetched contract says it reaches the model's next turn; confirm empirically in the M6 dogfood
  session (the manual done-test).
- 🟡 **Edited-file key is `tool_input.file_path`, but docs showed `.path`.** The hook reads both; if a
  future tool uses yet another key the locus won't resolve and the hook stays (correctly) silent.

## M6 — dogfood

- 🟡 **Plan-node fan-out in `context`.** Every task hangs off one `plan` node, so a query about a
  single task pulls in *all* sibling tasks at 1 hop — `context` then lists the whole plan. Fine as
  orientation, noisy for a narrow query. Candidate fix: treat `plan` as a soft hub (include but don't
  traverse through) or down-weight non-matched siblings in ranking. *(M4 polish / post-v0)*
- 🟡 **Token-win is real but modest on small files (2.5× on `drift.py`).** The measured win grows with
  file size and with how many files an agent would otherwise grep+read, and undercounts the value of
  also returning intent/plan/drift. A fuller benchmark across several realistic queries is worth doing
  before quoting a headline number.
- 🟢 **Live-session done-test still manual.** The hook entry points produce correct payloads on this
  repo, but "Claude Code consumes `additionalContext` on PostToolUse in a live session" is confirmed
  only from docs — verify interactively (open a session in this repo, edit `src/yigraf/drift.py`).
