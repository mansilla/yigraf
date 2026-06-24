# yigraf — Design (authoritative)

> **This is the single source of truth.** Where any detail doc conflicts with the Decision Log below,
> this doc wins. The detail docs (graph-design, retrieval-design, capture-flow, memory-model) hold the
> long-form rationale; this one pins the decisions, the vocabulary, and the build plan pointer.
> Last consolidated 2026-06-20 after a coherence review + Claude Code hook verification.

## 1. What yigraf is (one paragraph)

A **harness primitive** for AI coding agents: the *system of record* + the *retrieval/injection
surface* for an agent's work. It maintains one connected graph over four node families and makes the
right slice **legible** (scoped, token-cheap retrieval) and **enforceable** (a drift check that injects
a remediation instruction when code and intent diverge). It retrofits onto existing repos. Python;
Claude Code first. Built on OpenSpec (plan/intent), Graphify (structure/retrieval), the OpenAI
harness-engineering post (legible+enforceable), and ReCAP (memory = organized, re-injectable context).

## 2. The five dimensions → four node families (mapping)

The vision names five *dimensions*; the graph has four *node families* + one cross-cutting property.

| dimension | realized as |
| --- | --- |
| **memory** | `memory` node family |
| **semantics** (content/intent/goals) | `intent` node family |
| **structure** | `structure` node family |
| **active plan** | `plan` node family |
| **token efficiency** | not a family — a *property* delivered by scoped retrieval + the graph itself |

## 3. Architecture at a glance

```
authored artifacts (TRUTH)          repo source (TRUTH)
  yigraf/intents,plans,memory  ┐        code  ┐
        (.md, edges in            │             │ tree-sitter
         frontmatter)             ▼             ▼
                          ┌─────────────────────────────┐
                          │   graph.json  (derived)      │  ← rebuildable projection
                          │  structure│intent│plan│memory│
                          │  + cross-family edges        │
                          └─────────────────────────────┘
                       counters: recomputable in graph.json;
                       volatile telemetry in gitignored sidecar
        retrieval (legible) ──┘                └── drift check (enforceable)
              │                                          │
              └──────── injected via Claude Code hooks ──┘
                 PostToolUse · UserPromptSubmit · SessionStart
```

## 4. Glossary (pins overloaded terms)

- **commit boundary** — a **git commit** (the only deterministic, content-stable point). Anchors are
  computed and drift is measured here. *Not* a PostToolUse edit and *not* a task-checkbox flip (those
  are *nudge* points, not the moment state is recorded). [resolves review #1]
- **anchor** — the **AST-normalized content hash** of a linked symbol, stored on an `implements`/
  `concerns` edge, captured at the commit boundary when the agent (re)links. Distinct from
  `anchor_commit` (the SHA it was taken at, provenance only). The hash, not the SHA, is what drift
  compares. [resolves #12]
- **drift** — `current_anchor_hash(symbol) ≠ stored anchor`. **Soft drift**: symbol exists, body
  changed → "re-verify / relink." **Hard drift**: symbol gone (unresolvable locator) → "relink or
  remove." Rename/move is *not* drift — it auto-re-anchors (§Decision R4). [resolves #5]
- **relevance** — the canonical O(1) ranking prior:
  `w1·log(1+refs_in) + w2·recency(last_seen) + w3·maturity_weight − w4·[superseded_in>0]`.
  This exact formula; all other phrasings defer to it. [resolves #12]
- **maturity** (`working`→`settled`) vs **confidence** (`EXTRACTED`/`INFERRED`/`AMBIGUOUS`) vs
  **status** (`active`/`superseded`/`archived`) — three **orthogonal** axes. A node is `superseded`
  iff `superseded_in>0` (derived, never written back). Maturity promotes only while `superseded_in=0`,
  so a node settles *before* it could be superseded, never after. [resolves #12]
- **node families** — exactly four: structure, intent, plan, memory. (intent and plan are *separate*
  families — `tracks` and `requires` depend on the distinction.) [resolves #8]

## 5. Decision Log

### Prior decisions (locked earlier)
- **D1** Python. **D2** Files = truth, graph = derived projection. **D3** Four node families + cross-
  family edges (`implements`/`tracks`/`serves`/`concerns` + `supersedes`/`refines`). **D4** Retrieval =
  **scoped hybrid** (IDF/structural for structure+plan; embeddings over memory+intent), fused with
  graph-proximity + relevance. **D5** Embedding engine = local `bge-small-en-v1.5`, plain numpy
  brute-force cosine (no vector DB at our scale). **D6** Capture = agent-asserted at boundaries; nudge
  conservative; linking explicit-only; cadence ≈ once per task completion. **D7** Counters
  (`refs_in`/`superseded_in`/`usage`/`survival`) drive O(1) relevance/GC/maturity. **D8** Capture
  spans events at three boundary kinds (conversational / plan-approval / code-task).

### New resolutions from the 2026-06-20 review (these override conflicting detail-doc text)

- **R1 — `graph.json` is committed for team-sharing, but holds ONLY recomputable state.** Nodes,
  edges, and edge-derived counters (`refs_in`, `superseded_in`) live in it and merge cleanly. **Volatile
  telemetry (`usage`, `last_seen`) moves to a gitignored sidecar** `yigraf/.local/telemetry.json` —
  local, best-effort, soft ranking hint only. Reconciles D2 (files-are-truth) with D7 + team-sharing.
  [review #4]
- **R2 — `survival`/`maturity` are git-derived, not session counters.** A memory node is `settled`
  when it has lived on the **default branch for ≥K commits** (K=3) with no superseding node — computed
  from git history + supersede edges at build time. Recomputable, branch-cadence-independent, merge-
  safe. Removes the ambiguous per-session `survival` counter. [review #4.3]
- **R3 — GC never deletes files and never gates on `usage`.** Churn (`superseded_in>0 ∧ refs_in=0`) is
  **archived** (moved to `yigraf/**/archive/`, append-only-friendly), never deleted; gated only on
  recomputable `refs_in`/`superseded_in`. [review #11]
- **R4 — Drift uses an AST-normalized hash and handles rename/move in v0.** Hash strips comments +
  whitespace (cosmetic edits don't trip drift). Rename/move is detected via tree-sitter symbol identity
  + similarity and **auto-re-anchored** (no false drift); only a genuinely vanished symbol = hard drift.
  [review #5.1, #5.2]
- **R5 — "commit boundary" = git commit (glossary §4).** `yigraf link` *declares* the edge during the
  session; the **post-commit hook stamps/updates the anchor** for (re)linked edges against committed,
  normalized content — so the linking session itself never shows false drift, and a later un-relinked
  change does. [review #1]
- **R6 — Write-time dedup (near-dup + contradiction) is a MEMORY-MILESTONE feature, gated on
  embeddings.** v0 dedup = "edge exists or not." Contradiction detection (needed for supersede) must be
  designed before the memory milestone. [review #2]
- **R7 — v0 enforcement is `implements`-only.** `concerns`-edge drift arrives with the memory family.
  Every "…and why?" / `mem:00x` worked example is **memory-milestone**, not v0. v0's hero query is
  "what governs this code / what's left on this plan" (structure+plan+`implements`+drift, lexical
  seeder, no embeddings). [review #3, #7]
- **R8 — Hook reality (verified) reshapes injection:**
  - **`PreToolUse` cannot inject context** — only `PostToolUse`, `UserPromptSubmit`, `Stop`,
    `SessionStart` can (via `hookSpecificOutput.additionalContext`). So **action-driven drift/intent
    surfacing = `PostToolUse` on Edit/Write** (fires after the edit, sees `file_path`, can inject).
  - **`SessionStart(source=clear|compact)` injection = the "memory survives `/clear`" mechanism** —
    re-inject active plan + governing intents after a reset (the ReCAP re-injection idea, realized).
  - **`PreCompact(auto|manual)`** = trigger for the deferred distillation backstop.
  - **Plan-approval boundary exists**: `PreToolUse`/`PermissionRequest` matching `ExitPlanMode`
    (carries the plan markdown) — detection only; the *nudge* to run `yigraf plan` is skill-driven.
  - **v0 hooks = `PostToolUse` (drift+link nudge) + `SessionStart` (re-inject) only**; the full
    three-boundary taxonomy (D8) is post-v0 and primarily skill-driven, hooks as Claude-Code
    enhancement. [review #1, #10]

### Spec lifecycle (2026-06-23 — folds OpenSpec's planning strength in, graph-natively)

- **R9 — Adopt OpenSpec's spec *substance* and *guided flow*, not its *ceremony*.** OpenSpec's
  four-artifact change folder (`proposal`/`specs`/`design`/`tasks`) and `propose→apply→archive` +
  delta-spec (ADDED/MODIFIED/REMOVED) workflow exist to compensate for having **no graph**. yigraf
  has one, so it takes the value and drops the packaging. Three sub-decisions; long-form +
  schema/examples in **`docs/spec-lifecycle.md`**.
  - **R9a — Enriched intent node, still one-file-per-node.** The `intent` node gains `scenarios`
    (Given/When/Then behavioral examples) and an optional `design` (approach) field, alongside the
    existing `statement` (SHALL/MUST) + `status`. **Extends/overrides `graph-design.md` §1 intent
    row.** We **do not** adopt the four-artifact change folder: its concerns already decompose across
    families — proposal-*why* → **memory**, tasks → **plan** nodes, the spec → the **intent** node,
    joined by edges. Re-bundling them duplicates the graph and breaks one-file-per-node (D2 store
    principle).
  - **R9b — Specs are durable nodes; git + `supersedes` are the change model.** Specs are edited in
    place; **git history is the change log** and **`supersedes`/`refines` edges are spec evolution**.
    **No `propose→apply→archive` workflow and no delta-spec folders.** This *pins* `yigraf-vision.md`
    §5's "Adapt delta-patch evolution" → realized via `supersedes` + git, **not** OpenSpec change
    folders. (The existing `status` field — `proposed/active/satisfied/archived`, `graph-design.md`
    §1 — stays as a *soft* guide, not an enforced gate.)
  - **R9c — "Finished" is enforceable, not self-reported.** `status: satisfied` is agent/human-
    *asserted*; a **derived predicate `verified` = `satisfied` ∧ ≥1 live `implements` edge ∧ no drift
    on those edges** is *computed*. `satisfied`-without-`verified` (no link, or drifted) is **surfaced**
    (PostToolUse / `yigraf context`), **never hard-gated** — fail-open, consistent with R8 and
    OpenSpec's "no rigid phase gates." Drift on a `verified` spec **re-opens** it (surfaces the
    reconcile message). Builds on the `implements` edge only, consistent with **R7**.
- **Delivery vs. structure (R9 corollary):** OpenSpec's guided *flow* (`why → scenarios → design →
  tasks`) is the part users value, and it is **separable from the artifacts** — it ships as the
  **authoring skill** (M5 / skill body), producing R9a artifacts + graph edges, not as filesystem
  ceremony. The proposal-*why* lands as **memory** nodes that `serve` the intent and re-inject at
  `/clear` (R8) — **memory-milestone**, not a `proposal.md`. So R9a's fields + R9c's `verified`
  predicate are small additions to v0 (M2–M4); the *why*→memory capture and the skill's full guided
  flow are memory-milestone / delivery, not v0 spine.

### M1 normalization (2026-06-24 — pinned before code; the one near-irreversible v0 decision)

- **R10 — The drift anchor `content_hash` is an AST-normalized, *versioned* token-stream hash.**
  `SHA-256` over the symbol's significant token stream: **comments dropped**; **all whitespace/
  formatting ignored** (reformatting is not drift); **nested extracted-symbol subtrees excluded** via a
  `<def:NAME>` marker (so a method-body edit flips *only* that method's hash, not the enclosing class's
  — satisfies the M1 "exactly that symbol" done-test). **Docstrings are stripped** (like comments) and
  **string quote-style is normalized** (single↔double delimiter; prefix/quote-count preserved), so a
  doc edit or a `black`-style quote reflow is **not** drift — protecting the signal against
  mass-reformat alert fatigue. Escape-level value canonicalization (e.g. `'it\'s'`→`"it's"`) is
  deferred to a possible `astnorm-v2`. Each anchor stores **`anchor_algo: "astnorm-v1"`**; the drift
  check compares only when the tag matches, so a future rule change re-anchors gracefully instead of
  silently false-drifting — this is what de-risks "change the rule ⇒ all anchors invalidate." Full
  rule + parser API + extraction scope: **`docs/m1-notes.md`**. Refines R4/R5 (which named
  "AST-normalized" but didn't define it). Deps pinned: `tree-sitter` + `tree-sitter-python` (Python-only
  v0), core not extra.
  - **R10.1 (2026-06-24, M3):** the hash also **excludes the symbol's own declared name**, so a pure
    rename leaves the body-hash unchanged and M3 re-anchors the moved locator by exact match (R4's
    "auto-re-anchor") instead of false-drifting. A *container* still hashes its members' names (the
    `<def:NAME>` markers), so a member rename remains a real structural change. Refined in place in
    `astnorm-v1` (no anchors persisted yet). Detail: `docs/m3-notes.md` §2.

### M2 linking (2026-06-24 — realizing R5's goal at implementation)

- **R11 — The anchor is stamped at `yigraf link` time (working-tree content), authoritative; the
  `post-commit` hook only rebuilds `graph.json` to HEAD.** This realizes R5's *goal* — the linking
  session shows no false drift, a later un-relinked change does — without R5's literal post-commit
  frontmatter rewrite, which would leave a dirty tree and an anchor-less commit. **Re-stamping at
  commit is deliberately NOT automatic:** a symbol edited after linking, without a re-link, must
  surface as drift (re-verify / relink), consistent with R9c (drift re-opens a `verified` spec);
  re-linking is the explicit re-verify gesture that re-stamps. Unresolvable link targets are stashed
  on the task node (`dangling_*`) rather than added as phantom edges — M3 surfaces them as hard
  drift. Refines R5's *mechanism* in service of its *goal*. Full rule: **`docs/m2-notes.md`** §4.

## 6. Document index

| doc | holds |
| --- | --- |
| `docs/DESIGN.md` (this) | authoritative decisions, glossary, mapping, tie-breaker |
| `docs/BUILD-PLAN.md` | sequenced v0 milestones + done-tests |
| `docs/yigraf-vision.md` | thesis, five dimensions, long-form synthesis |
| `docs/yigraf-v0.md` | v0 scope detail |
| `docs/spec-lifecycle.md` | spec authoring richness + lifecycle + enforceable-done (R9) |
| `docs/authoring-skill.md` | the guided spec-authoring flow (R9 delivery; ships M5) |
| `docs/m1-notes.md` | M1 structure-index decisions; the normalization rule (R10) |
| `docs/m2-notes.md` | M2 intent/plan artifact schema + link/anchor/commit timing (R11) |
| `docs/m3-notes.md` | M3 drift model + rename re-anchor + the R10.1 name-exclusion refinement |
| `docs/m4-notes.md` | M4 retrieval — v0 lexical pipeline, the `signature` field, reconcile (R9c) |
| `docs/m5-notes.md` | M5 — verified Claude Code hook contract + the hook/skill wiring |
| `docs/m6-notes.md` | M6 — dogfood on itself; the measured token win + success-criteria evidence |
| `docs/caveats.md` | running log of sharp edges / known issues found while implementing v0 |
| `docs/graph-design.md` | data model, edges, counters, storage |
| `docs/memory-model.md` | memory node + capture (memory milestone) |
| `docs/retrieval-design.md` | seeding→traversal→rank→render, embeddings |
| `docs/capture-flow.md` | write path, boundaries, dedup |
| `docs/research/*` | OpenSpec, Graphify, harness-engineering, ReCAP analyses |

> Follow-up (low priority): propagate R1–R11 into the detail docs' bodies (esp. R9a into
> `graph-design.md` §1's intent row). Until then, this Decision Log governs.
