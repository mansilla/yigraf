# yigraf — Build Plan (v0)

> Sequenced milestones to ship the **legible + enforceable spine** (`docs/yigraf-v0.md`), governed by
> the decisions in `docs/DESIGN.md`. Python, Claude Code first. Each milestone has a concrete
> done-test. v0 deliberately excludes the memory family, embeddings, and multi-host breadth.

## Guiding constraints (from DESIGN.md)
- v0 enforcement is **`implements`-only**; no `concerns`/memory (R7).
- v0 retrieval = **lexical/IDF seeder, no embeddings** (R7, D4-deferred).
- Drift = **AST-normalized hash**, measured at the **git commit** boundary; rename auto-re-anchors (R4, R5).
- `graph.json` committed (recomputable state only); telemetry in gitignored sidecar (R1).
- v0 hooks = **PostToolUse** (inject drift + link-nudge) + **SessionStart** (re-inject) (R8).

## Dogfood target
Build yigraf **on itself** — a Python repo with intents/plans. Earliest possible self-hosting is the
forcing function for quality and the first real demo.

---

## M0 — Scaffold
- `pyproject.toml` (uv), package `yigraf/`, CLI entry `yigraf` (typer/click), `config.yaml` loader,
  pytest. `yigraf init` writes the `yigraf/` skeleton (`intents/ plans/{active,completed} memory/`),
  a committed `graph.json` stub, `.local/` + `index/` + `cache/` gitignored, and a `.gitattributes`
  union-merge entry for `graph.json`.
- **Done-test:** `yigraf --help` and `yigraf init` run; a fresh `yigraf/` tree + correct `.gitignore`/
  `.gitattributes` appear; `pytest` green.

## M1 — Structure index
- tree-sitter extraction (**Python only** to start — enough to dogfood), → NetworkX nodes
  (`file`/`symbol`/`module`) + structural edges (`contains`/`calls`/`imports`); **AST-normalized
  `content_hash`** per symbol; SHA content cache; `graph.json` writer (node-link).
- **Done-test:** run on a sample repo → `graph.json` with expected symbols and stable ids; re-run with
  no changes = byte-identical graph (cache hit); a comment-only edit leaves every `content_hash`
  unchanged (normalization works); a body change flips exactly that symbol's hash.

## M2 — Intent/plan artifacts + linking
- Verbs: `yigraf intent`, `yigraf plan` (+tasks, `tracks`/`requires` edges), `yigraf link` (declare
  `implements`/`tracks`). Artifact readers project these into the graph (edges from frontmatter).
- **post-commit git hook** (detached, AST-only) that rebuilds structure and **stamps the anchor** on
  (re)linked edges against committed content (R5).
- **Done-test:** create an intent + a plan with a task, `yigraf link` the task to a symbol, commit →
  the `implements` edge in `graph.json` carries an `anchor` equal to the committed symbol's normalized
  hash; the linking commit shows **no** drift.

## M3 — Drift detection + rename handling
- On build/query: compute soft drift (hash≠anchor, symbol exists) and hard drift (locator unresolvable).
  **Rename/move detection** (symbol identity + similarity) → auto-re-anchor, emit no drift.
- **Done-test:** edit a linked symbol's body + commit → **soft** drift surfaces; rename the symbol +
  commit → **no** drift (auto-re-anchored); delete the symbol + commit → **hard** drift.

## M4 — Retrieval (`yigraf context`)
- Lexical/IDF seeder (exact>prefix>substring, score-gap cutoff); hub-aware bounded traversal
  (d=2, N=60, p99 hub floor 50) across structure+intent+plan; fusion rank
  `α·match + β·proximity + γ·relevance` with `relevance` = `refs_in`/`superseded_in` only (no memory
  yet); token-budgeted render (**locators + signatures, not source**); drift lines reserved in budget.
- **Done-test:** `yigraf context "session expiry"` returns the requirement + the implementing
  symbol(s) as signatures + any drift, under the budget; output token count materially below
  grep-+-read of the same files (record the number — operationalizes v0 success-criterion #2).

## M5 — Claude Code hooks + skill (R8)
- **PostToolUse** on `Edit|Write`: fail-open, silent-unless the touched symbol has an `implements`
  edge or drift → inject (`additionalContext`) the governing intent + reconcile message; plus the
  conservative "link this?" nudge for an unlinked symbol under an active task.
- **SessionStart** (`clear|compact`): re-inject active plan + governing intents.
- `SKILL.md` (skill body: the link-on-task-done ritual, `yigraf context` first) + the always-on
  `AGENTS.md` block.
- **Done-test (in a real Claude Code session):** editing a linked+drifted symbol surfaces the reconcile
  message unprompted; editing unrelated code stays silent; after `/clear`, the active plan reappears.

## M6 — Dogfood + measure + harden
- Run yigraf on yigraf; install the git hooks; track its own intents/plans/links; measure the token
  win on a real "what governs this / what's left" query; write `config.yaml` defaults + docs.
- **Done-test:** `docs/yigraf-v0.md` success criteria #1–#3 demonstrably met on yigraf's own repo:
  (1) agent gets unprompted governing-intent + drift while editing; (2) measured token win; (3) edges
  survive crash, `/clear`, and unrelated same-file edits.

---

## Sequencing notes
- **Critical path:** M1 → M2 → M3 (the enforceable core) before M4/M5 (the surfacing). M0 first.
- **Earliest demo:** end of M3 = drift works at the CLI; end of M5 = the in-agent experience.
- **Languages beyond Python:** after v0 (reuse Graphify's extractor breadth).
- **Verify before M5:** re-confirm the PostToolUse `additionalContext` shape + SessionStart matchers
  against current Claude Code docs (versions move).

## Post-v0 (not in this plan)
Memory family + capture verbs (`remember`/`supersede`/`note-constraint`) + embeddings (bge-small) +
write-time dedup/contradiction (R6) + maturity/GC + the full three-boundary capture taxonomy +
multi-host breadth + non-code modalities.
