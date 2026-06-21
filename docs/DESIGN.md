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

## 6. Document index

| doc | holds |
| --- | --- |
| `docs/DESIGN.md` (this) | authoritative decisions, glossary, mapping, tie-breaker |
| `docs/BUILD-PLAN.md` | sequenced v0 milestones + done-tests |
| `docs/yigraf-vision.md` | thesis, five dimensions, long-form synthesis |
| `docs/yigraf-v0.md` | v0 scope detail |
| `docs/graph-design.md` | data model, edges, counters, storage |
| `docs/memory-model.md` | memory node + capture (memory milestone) |
| `docs/retrieval-design.md` | seeding→traversal→rank→render, embeddings |
| `docs/capture-flow.md` | write path, boundaries, dedup |
| `docs/research/*` | OpenSpec, Graphify, harness-engineering, ReCAP analyses |

> Follow-up (low priority): propagate R1–R8 into the detail docs' bodies. Until then, this Decision
> Log governs.
