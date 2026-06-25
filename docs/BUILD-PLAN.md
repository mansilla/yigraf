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
- Spec lifecycle: intent carries **`scenarios` + optional `design`** (R9a); specs are **durable nodes**
  (git + `supersedes` are the change model — **no** propose/apply/archive, **no** delta folders, R9b);
  **finished = `verified`** = `satisfied` ∧ live `implements` edge ∧ no drift, surfaced not gated (R9c).

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
- Verbs: `yigraf intent` (`statement` + **`scenarios` (Given/When/Then) + optional `design`** — R9a),
  `yigraf plan` (+tasks, `tracks`/`requires` edges), `yigraf link` (declare `implements`/`tracks`).
  Artifact readers project these into the graph (edges from frontmatter; `scenarios`/`design` into the
  intent node).
- **post-commit git hook** (detached, AST-only) that rebuilds structure and **stamps the anchor** on
  (re)linked edges against committed content (R5).
- **Done-test:** create an intent (with a scenario + design) + a plan with a task, `yigraf link` the
  task to a symbol, commit → the intent node in `graph.json` carries its `scenarios`/`design`, the
  `implements` edge carries an `anchor` equal to the committed symbol's normalized hash, and the
  linking commit shows **no** drift.

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
- **Verified-done check (R9c):** compute `verified(intent) = status==satisfied ∧ ≥1 live `implements`
  edge ∧ no drift on it` — derived from the M3 drift signal, no new state. A `satisfied`-but-unverified
  intent (unlinked or drifted) emits a reconcile line, reserved in budget alongside drift.
- **Done-test:** `yigraf context "session expiry"` returns the requirement + the implementing
  symbol(s) as signatures + any drift, under the budget; output token count materially below
  grep-+-read of the same files (record the number — operationalizes v0 success-criterion #2); a spec
  marked `satisfied` whose linked symbol has drifted surfaces a **"satisfied but not verified"** line.

## M5 — Claude Code hooks + skill (R8)
- **PostToolUse** on `Edit|Write`: fail-open, silent-unless the touched symbol has an `implements`
  edge or drift → inject (`additionalContext`) the governing intent + reconcile message (incl. a
  `satisfied`-but-now-drifted spec re-opening, R9c); plus the conservative "link this?" nudge for an
  unlinked symbol under an active task.
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

---

## Memory milestone (post-v0) — in progress

The fourth node family + the *why*. Decomposed into three milestones on the M0–M6 cadence. Specs:
`docs/memory-model.md`, `docs/capture-flow.md`, `docs/retrieval-design.md` §10, `docs/graph-design.md` §3.

### M7 — Memory node family + capture verbs ✅ (commit 4c795aa, `docs/m7-notes.md`)
- `memory/<seq>-<slug>.md` artifacts (`decision`/`constraint`/`rationale`/`rejected-alternative`/
  `learned-fact`/`preference`); `yigraf remember` / `note-constraint` / `supersede`; projection of
  `serves`/`concerns`/`supersedes` edges. **`concerns` is the 2nd drift-bearing relation** — reuses the
  `implements` rename/soft/hard machinery via one `{implements, concerns}` code path. `superseded_in`/
  `supersedes_out` counters materialized; `Decisions (why)` render group; agent-asserted capture only
  (memory-model §5 option A). Embedding-free + deterministic.
- **Done-test (met):** `remember` → node + anchored `concerns` edge (no drift); edit the code → soft
  `concerns` drift; rename → auto-re-anchor; `supersede` → active out-ranks `·superseded`;
  `note-constraint` → promotable. 14 tests.

### M8 — Embedding index + semantic seeder + write-time dedup ✅ (commit e021b22, `docs/m8-notes.md`)
- Pluggable model backend (default local `bge-small-en-v1.5`) + a numpy brute-force cosine index over
  **memory+intent only** (gitignored `index/`, no vector DB). Semantic seeder **fused** with the
  lexical/IDF seeder (union-of-top-k seeds; per-source-normalized `match`). Write-time near-duplicate
  guard (`dup_cosine`, `--new` to force; `supersede` bypasses). Optional `[embeddings]` extra; **graceful
  lexical fallback** when absent. The hot action-driven hook never embeds (seeds from the locus).
- **Done-test (met):** a paraphrased, lexically-disjoint query ranks the right memory/intent node first;
  near-dup `remember` refused; **suite green with *and* without the extra** (112 / 114).

### M9 — Counters / maturity / GC + runtime telemetry (NEXT)
- The first **non-recomputable** state. `survival`/`usage`/`last_seen` become **authoritative in
  `graph.json`** and are **preserved** across rebuilds (edge-derived counters still recomputed; runtime
  counters kept, not overwritten — graph-design §3). `working → settled` promotion once `survival ≥ K`.
  The relevance prior gains **recency** (`w2`, exp-decay on `last_seen`) + **maturity** (`w3`). A **GC
  pass**: delete pure churn (`superseded_in>0 ∧ refs_in=0 ∧ usage=0`), retain a referenced predecessor
  as `rejected-alternative`/`archived`. Register the **`graph.json` union-merge driver** (max `survival`
  / latest `last_seen` / union of nodes+edges) via the git hooks so teammates/CI reconcile cleanly.
- **Done-test:** capture a decision; after `K` rebuild/commit boundaries un-superseded it promotes to
  `settled` and its relevance rises; a re-injection bumps `usage`/`last_seen` and those **survive a
  rebuild** (not recomputed away); a superseded, never-referenced churn node is GC'd while a referenced
  one is kept as `rejected-alternative`; two branches' counter divergence merges via the driver.
- **Open going in:** `K` and the `w*`/`α,β,γ` weights are intuition-set (graph-design §8) — tune
  empirically once telemetry exists; `usage` merge reconciliation is best-effort (graph-design §8).

## Still post-v0 (after the memory milestone)
- **Capture breadth:** pre-`/clear` distillation backstop (memory-model §2 option B); the boundary-A/B
  capture nudges — `UserPromptSubmit` / plan-mode-exit (capture-flow §0a); artifact mining for bootstrap.
- **Retrieval:** `dup_cosine` tuning + **contradiction** detection (vs near-dup; capture-flow §7);
  non-local embedding backends (`ollama`/`openai`/`voyage`); multilingual embeddings.
- **Reach:** multi-language extraction (reuse Graphify grammar breadth); non-code modalities;
  cross-project graph; team MCP.
- **Hardening:** hook portability — `install-claude-hooks` bakes an absolute interpreter path (caveats
  M5 🔴); the PostToolUse full-graph-rebuild-per-edit cost (caveats M5).
