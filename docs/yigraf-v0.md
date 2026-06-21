# yigraf v0 — "The legible + enforceable intent↔code spine"

> v0 scope detail. **Authoritative decisions live in `docs/DESIGN.md`** (Decision Log R1–R8);
> where this doc conflicts, DESIGN.md wins. Build sequence in `docs/BUILD-PLAN.md`.
> Grounded in OpenAI's harness-engineering post (`docs/research/harness-engineering-notes.md`).
> Language: **Python**. Retrieval: **scoped hybrid, decided** (embeddings deferred past v0, not undecided).

---

## The one thing v0 proves

> An agent working in an **existing** repo is told — *without being asked, at the moment it acts* —
> what intent governs the code it's touching, and is given a **remediation instruction** when code
> and intent have drifted. End-to-end, inside a real host (Claude Code first).

This is the single capability **neither parent tool has**: OpenSpec tracks intent but can't see
code; Graphify maps code but tracks no intent. v0 builds the *spine* that connects them and makes
the connection **enforceable**, not decorative.

## Why this exact slice (straight from the post)

- **"What capability is missing, and how do we make it both legible AND enforceable?"** — v0 delivers
  exactly one capability along both axes: *legible* (the graph + scoped retrieval) and *enforceable*
  (the drift check).
- **"Anything it can't access in-context while running effectively doesn't exist."** → v0 must ship
  the **runtime injection** (a hook), not just a store. A graph nobody reads at the decision moment
  is worth zero. This is why v0 is not "build the database first."
- **"Because the lints are custom, we write the error messages to inject remediation instructions
  into agent context."** → the drift check's output is a *fix instruction injected via hook*, not a
  passive report.
- **"A map, not a 1,000-page manual."** → retrieval returns a scoped subgraph within a token budget.
- **Our wedge vs. OpenAI's setup:** they got legibility by building greenfield with total control.
  yigraf **retrofits** legibility onto brownfield repos with no restructuring required.

---

## In scope

**1. Structure index** *(reuse Graphify's approach)*
- tree-sitter → NetworkX graph of symbols / files / imports for the repo. Python implementation.
- Incremental refresh via **detached git post-commit hook** (Graphify pattern) — AST-only, free, fast.
- Confidence provenance on edges (`EXTRACTED` / `INFERRED`), reused as-is.
- *Cut for v0:* non-code modalities (docs/PDF/image/video) and the cross-project global graph.

**2. Plan / intent layer** *(OpenSpec model, simplified)*
- Repo-local, **versioned markdown** under `yigraf/` (or `docs/`-style), **filesystem-as-state**:
  a plan = a set of intent units (goal/requirement) + tasks; "done" is derived, no separate state DB.
- Each intent/task carries a **decision log** field (the post's "execution plans with decision
  logs") — this is also the seam the memory dimension will grow into later.

**3. The `implements` edge + drift check** *(the new core)*
- A typed edge `intent_node → code_node(s)` recording, at link time, a **content hash of the linked
  symbol's source range** (not just the file — robust to unrelated edits elsewhere in the file) and
  the commit it was anchored at.
- **Authoring is agent-asserted, not inferred** in v0: when the agent implements a task it calls
  `yigraf link <intent-id> <symbol>` → edge stored as `EXTRACTED` (cheap, reliable). Auto-inference
  (`INFERRED`) is deferred — it's the risky part.
- **Drift detection:** linked code's hash changed after the intent was anchored (or intent text
  changed after the link) ⇒ `drift`. Computed on the git hook and on query.
- **Output is a remediation instruction**, e.g.:
  > ⚠ `auth/session.py:refresh()` implements intent **R-12 "sessions expire after 30m idle"**, but
  > its source changed at `a1b2c3` after R-12 was anchored. Re-verify R-12 still holds, or update the
  > link with `yigraf link R-12 auth/session.py:refresh`.

**4. Retrieval / injection surface** *(synthesis of both parents)*
- One CLI + one MCP tool: `yigraf context "<query>"` → a **scoped subgraph** (structure + linked
  intent/plan + any drift warnings) under a token budget. Reuse Graphify's IDF + hub-aware,
  token-budgeted traversal for the structure side.
- **Fail-open PreToolUse hook** (Graphify pattern): when the agent is about to edit/read a file that
  has linked intent, inject the governing intent + drift warnings. Fails open, skips `yigraf/` paths.

**5. Integration** *(Graphify's multi-tier blueprint, minimal)*
- Ship for **Claude Code + Codex** in v0 (skill body + hook). Other hosts get the AGENTS.md
  always-on block only. Breadth comes later — v0 proves depth in two hosts.

---

## Out of scope for v0 (deferred, with reason)

| Deferred | Why |
| --- | --- |
| **Memory node family + capture (`concerns` drift)** | Hardest piece. v0 enforcement is **`implements`-only** (R7); `concerns`-edge drift + every "…and why?" example are memory-milestone. v0 lays only the schema seam. |
| **Semantic / vector retrieval (embeddings)** | Approach is **decided** (scoped hybrid, D4) but *built later*: v0 ships the **lexical/IDF seeder only**. Embeddings (bge-small) + write-time dedup/contradiction (R6) come with the memory milestone. |
| **Auto-inferred `implements` edges** | Risky (`INFERRED`). v0 = agent-asserted, **explicit-only** linking (D6). |
| **Non-code modalities (docs/PDF/image/video)** | Graphify's LLM pass 3; not needed to prove the spine. |
| **Runtime legibility (logs/metrics/UI driving)** | A *different* harness axis the post covers; not yigraf's lane (we are static legibility). |
| **Generator/evaluator orchestration, broad host fan-out** | Consumers of yigraf, not the spine. |

## Success criteria

1. In a real, pre-existing repo: an agent mid-edit receives — unprompted — the governing intent and
   a drift warning for the code it's about to change, and acts on it. Demonstrated in ≥1 host.
2. **Token win:** "what governs this code / what's left on this plan" answered by one scoped-subgraph
   query vs. grep + re-reading files + scrollback. Measure tokens both ways.
3. Edges survive: agent crash, `/clear`, and unrelated edits in the same file (anchor is
   symbol-scoped + AST-normalized, so cosmetic edits and renames don't break them — R4).

## v0 CLI surface

`yigraf init` · `yigraf intent` · `yigraf plan` · `yigraf link` · `yigraf context` · plus the
post-commit/post-checkout git hooks. Capture verbs `remember`/`supersede`/`note-constraint` are
**memory-milestone** (post-v0). Full sequence + done-tests: `docs/BUILD-PLAN.md`.

## Resolved (were open; now decided — see DESIGN.md)

- **Link granularity:** symbol-level, agent-asserted, **explicit-only** (D6).
- **Drift signal:** **AST-normalized** symbol content hash, measured at the **git commit** boundary;
  rename auto-re-anchors (R4, R5) — not raw source-range, not commit-touch.
- **Link authoring:** skill instruction + explicit `yigraf link` at task completion (no auto-link);
  conservative PostToolUse nudge; background "done-but-unlinked" sweep catches misses (D6).

---

## Next milestone (post-v0): the memory family + embeddings

Retrieval approach is already **decided** (scoped hybrid, D4); the *milestone* that builds it comes
after v0: memory node family, capture verbs, the local embedding index (bge-small), write-time
dedup/contradiction (R6), maturity/GC. This is what unlocks the "what did we decide, and why?" query.
