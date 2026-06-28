# yigraf — Vision & Synthesis

> **yigraf = "Why I Graph?"** — a tool **for AI coding agents, not for human beings.** It answers, for
> the agent, the *why's* and *what-for's* of its current state — the questions an agent can't recover
> from source alone and loses on every `/clear`. A human is the *principal* whose intent it carries;
> the **agent is the operator and the audience.** Token efficiency is a *property* it delivers (a scoped
> graph slice instead of re-read files), **not** the meaning of the name.
> Built on lessons from **OpenSpec** (the plan/intent layer) and **Graphify** (the structure/retrieval layer).
> See `docs/research/openspec-analysis.md` and `docs/research/graphify-analysis.md`.

---

## 1. The thesis

Today's AI coding agents lose state in three independent places:

| Where state lives | What's lost | Who tries to fix it |
| --- | --- | --- |
| Chat history | intent, goals, rejected approaches | OpenSpec (partially) |
| The codebase | structure, who-calls-what, the *why* | Graphify (partially) |
| The session | "what am I doing right now," memory across `/clear` | **nobody** |

OpenSpec and Graphify each solve one slice and **deliberately ignore the others**. OpenSpec tracks
plans but has *zero* code awareness. Graphify maps code structure but tracks *no* plans, goals, or
conversation memory (its makers ship a separate product for that).

**yigraf's bet:** these are not three problems — they are one. They are all *graphs of meaning that
should be linked*. A requirement should point at the functions that implement it. A design decision
should point at the code it constrains and the conversation turn that birthed it. The active plan
should point at both. Represent all five dimensions as **one connected, queryable, token-cheap graph**
and the agent stops re-deriving context it already had.

---

## 2. The five dimensions → where each tool already helps

The five dimensions of state an agent must track across a task, mapped to prior art and the gap yigraf
must fill. (Each is a question the agent asks about its own work — yigraf exists to answer it.)

### ① Memory — concepts/ideas in the conversation and their relationships
- OpenSpec: ✗ (intent artifacts survive, but not the reasoning trail).
- Graphify: ✗ (explicitly out of scope; rationale nodes capture *code* comments, not conversation).
- **yigraf gap → the core novel contribution.** A **memory graph**: nodes capturing the *reasoning*
  produced during work (decisions, constraints, rejected alternatives), linked to each other and
  *down* into the structure/plan graphs. Modeled now in **`docs/memory-model.md`**, grounded in
  ReCAP (a memory node = a persisted, linked reasoning trace `T`) — see
  `docs/research/recap-paper-analysis.md`. Reframe: *memory is organized, re-injectable context, not
  a pile of stored facts.*

### ② Semantics — content, intention, necessities, goals
- OpenSpec: ✓✓ specs as behavioral contracts (SHALL/MUST), proposal = *why*, design = *how*.
- Graphify: ~ concept/entity nodes from docs + `semantically_similar_to` edges.
- **yigraf:** adopt OpenSpec's "spec = observable behavior, design = approach" split as the *intent*
  schema, and Graphify's concept extraction as the *content* index. Link intent nodes to the code
  nodes that satisfy them — the thing **neither tool does**.

### ③ Structure — how the project, tools, and source connect
- OpenSpec: ✗.
- Graphify: ✓✓ tree-sitter AST → symbol/file/import graph, call edges, communities, god nodes.
- **yigraf:** take Graphify's extraction pipeline almost wholesale (NetworkX, tree-sitter, no
  embeddings, confidence provenance). This is solved; don't reinvent it.

### ④ Active plan — goals codified/structured so work continues
- OpenSpec: ✓✓ artifact DAG, `tasks.md` checkboxes, propose→apply→archive, delta specs.
- Graphify: ✗.
- **yigraf:** adopt OpenSpec's **filesystem-as-state** DAG and **delta-patch** model. Then do what
  OpenSpec can't: link each task/requirement to the structure-graph nodes it touches, so "what's
  left" and "what code does it affect" are one query.

### ⑤ Token efficiency — stop re-reading what's already encoded
- OpenSpec: ~ CLI-as-context-API returns *exact paths* to read (context hygiene, not compression).
- Graphify: ✓✓ scoped subgraphs instead of file dumps; ~71× fewer tokens; IDF + hub-aware retrieval.
- **yigraf:** unify both. Graphify's token-budgeted graph retriever becomes the *single read surface*
  for ALL dimensions — ask once, get a scoped subgraph spanning plan + code + memory, never re-read.

---

## 3. The synthesis — what yigraf actually is

> **One graph, four node families, two proven delivery mechanisms.**

```
                         ┌─────────────────────────────────────────┐
                         │            yigraf knowledge graph         │
                         │                                           │
   conversation  ───►    │   MEMORY ◄──┐                             │
                         │     │       │  links                      │
   specs / goals ───►    │   INTENT ───┼──► STRUCTURE  ◄─── tree-sitter AST
                         │     │       │      (code)                 │
   tasks / DAG   ───►    │    PLAN ────┘                             │
                         │                                           │
                         └─────────────────────────────────────────┘
                                   ▲                       │
                  filesystem-as-state (OpenSpec)   token-budgeted retrieval (Graphify)
```

**Node families**
1. **Structure nodes** — code symbols, files, imports (Graphify's extractor, verbatim approach).
2. **Intent nodes** — requirements, design decisions, goals (OpenSpec's spec/design schema).
3. **Plan nodes** — tasks/milestones in a DAG with filesystem-derived state (OpenSpec's engine).
4. **Memory nodes** — concepts, constraints, rejected approaches from the session (**new**).

**The differentiator is the cross-family edges** — `implements`, `constrains`, `decided-because`,
`blocks`, `supersedes` — that neither parent tool has, because neither has both graphs to connect.

**Delivery (steal both, layered):**
- **Integration breadth** = Graphify's multi-tier strategy: portable skill body → idempotent
  always-on instruction injection → **fail-open PreToolUse hooks** that intercept grep/read at the
  decision moment → MCP server for repeated/team access. This is *the* way to be "available to as
  many agents as possible."
- **State & plan mechanics** = OpenSpec's: **filesystem-as-state** (no drift, survives crashes),
  **CLI-as-context-API** (agent queries for exactly what it needs), **delta patches** for evolving
  intent without conflicts, **externalized schemas/templates** so prompts are editable, not compiled.

---

## 4. Gaps in the parents that yigraf is positioned to close

1. **Plan ↔ code linkage** — OpenSpec can't verify a requirement is implemented; Graphify can't say
   which code a goal belongs to. yigraf's `implements` edge makes "is this spec done?" a graph query,
   not a vibe check.
2. **Durable conversation memory** — the unaddressed third state-loss site. yigraf is the only one of
   the three carrying memory nodes across `/clear`.
3. **One retrieval surface** — instead of "OpenSpec for plans, Graphify for code, scrollback for
   memory," a single scoped-subgraph query spans all three under a token budget.
4. **Honest staleness handling** — Graphify auto-refreshes only AST on commit (semantics drift);
   OpenSpec lets spec/code silently diverge. yigraf can mark cross-family edges with
   Graphify's `EXTRACTED/INFERRED/AMBIGUOUS` provenance *plus* a freshness timestamp, and flag
   intent nodes whose linked code changed since the spec was written.

---

## 5. What to reuse vs. build

| Capability | Source | Action |
| --- | --- | --- |
| Tree-sitter AST → structure graph | Graphify | **Reuse** (architecture/approach) |
| NetworkX JSON store, no embeddings | Graphify | **Reuse** |
| Token-budgeted IDF + hub-aware retriever | Graphify | **Reuse**, extend across node families |
| Multi-tier agent integration (skill/always-on/hooks/MCP) | Graphify | **Reuse** the blueprint |
| Confidence provenance (`EXTRACTED/INFERRED/AMBIGUOUS`) | Graphify | **Reuse** for cross-family edges |
| Detached git-hook incremental refresh | Graphify | **Reuse** |
| Artifact DAG + filesystem-as-state | OpenSpec | **Reuse** the model |
| Spec/design/tasks schema (intent vocabulary) | OpenSpec | **Adapt** into intent nodes |
| Delta-patch evolution (ADDED/MODIFIED/REMOVED) | OpenSpec | **Adapt** for intent + memory updates |
| CLI-as-context-API, externalized templates | OpenSpec | **Reuse** the pattern |
| **Memory node family + cross-family edges** | — | **Build** (the novel core) |
| **Plan↔code↔memory linkage & staleness flags** | — | **Build** |

---

## 6. Open questions to resolve before building

1. **Language:** Graphify is Python (great tree-sitter/graph ecosystem); OpenSpec is TS. yigraf leans
   toward Python to inherit Graphify's extraction stack — confirm.
2. **Memory extraction trigger:** how/when are memory nodes captured — agent-driven (skill tells it
   to record decisions), hook-driven, or end-of-session distillation? Cheapest reliable signal wins.
3. **One graph vs. linked stores:** single `graph.json` with four node families, or separate
   plan/structure/memory stores joined at query time? Affects merge/refresh complexity.
4. **Cross-family edge authoring:** inferred automatically (risky, `INFERRED`) vs. asserted by the
   agent when it implements a task (cheap, `EXTRACTED`). Likely both.
5. **Scope of v0:** now specified concretely in **`docs/yigraf-v0.md`** — structure + plan + the
   `implements` edge **+ a context-injecting drift check** (ship enforcement/injection, not just a
   store). Memory and semantic retrieval come after.

---

*See `docs/research/harness-engineering-notes.md` for how OpenAI's harness-engineering post reframes
this work (legible + enforceable; "can't see it ⇒ doesn't exist"), and `docs/yigraf-v0.md` for the
concrete first build. Retrieval decided: **scoped hybrid** (IDF/structural for code+plan; embeddings
only over memory+intent) — see `docs/memory-model.md` §4. Memory node + capture: `docs/memory-model.md`.*
