# yigraf — Graph Design

> The data model: node families, edges, counters, storage, and how the graph is built, captured
> into, and queried. Synthesizes every decision so far — see `docs/yigraf-vision.md`,
> `docs/yigraf-v0.md`, `docs/memory-model.md`, and the research notes.
> Language: Python. Store: NetworkX node-link JSON (Graphify pattern), repo-local.

## 0. Three principles

1. **Authored artifacts are the source of truth for content & edges; `graph.json` is a committed,
   shareable projection that also holds the runtime counters.** Plans, intents, and captured memory
   live as versioned `.md` artifacts (git-diffable, reviewable — OpenSpec/harness-post principle);
   the repo's own source code is the truth for structure. `graph.json` is built from all of them
   **and** is the authoritative store for runtime-accumulated counters (`survival`/`usage`/
   `last_seen`). It is **committed** (with a union-merge driver) so teammates and CI query without
   rebuilding; a rebuild re-projects content/edges while **preserving** those counters.
2. **Repo-local and inspectable.** No opaque service; the agent (and human) can read the graph and
   the artifacts directly ("boring, in-repo, agent-can-reason-about-it").
3. **One graph, four node families, connected by cross-family edges.** The cross-family edges are
   the whole differentiator — they're what neither parent tool has.

## 1. Node families

Every node: `id`, `family`, `label`, `confidence` (`EXTRACTED` | `INFERRED` | `AMBIGUOUS`), plus the
**counters** (§3) and family-specific fields.

| family | node types | key fields | source |
| --- | --- | --- | --- |
| **structure** | `file`, `symbol` (class/fn/method — `kind`), `module` | `source_file`, `source_range`, **`content_hash`** (of the range — drift anchor), `language` | tree-sitter (Graphify) — `EXTRACTED` |
| **intent** | `requirement`, `goal`, `capability` | `statement` (behavioral, SHALL/MUST), `scenarios` (Given/When/Then), `design` (optional, the *how*), `status` (proposed/active/satisfied/archived) | intent markdown (OpenSpec-style) — body is authored spec content (R9a / `spec-lifecycle.md`) |
| **plan** | `plan`, `task` | `state` (todo/in_progress/done — *derived from filesystem*), `order`, `decision_log` | plan markdown, filesystem-as-state (OpenSpec) |
| **memory** | `decision`, `constraint`, `rationale`, `rejected-alternative`, `learned-fact`, `preference` | `statement`, `why` (ReCAP's `T`), `alternatives`, `maturity` (working/settled), `status` (active/superseded/archived), `provenance{source, anchor_commit, ts}` | agent-asserted at commit boundary (memory-model §2) |

ID scheme (stable, casefold-normalized like Graphify): `file:<path>`, `sym:<path>#<qualified.name>`,
`int:<slug>`, `plan:<slug>`, `task:<plan>/<n>`, `mem:<content-or-seq-id>`.

## 2. Edges

Edge data: `relation`, `confidence`, `context` (optional tag), `anchor_hash` (on drift-bearing
edges), `created_at` (commit/seq).

**Structural** (within structure family — Graphify): `contains` (file→symbol), `calls`, `imports`,
`inherits`, `references`.

**Cross-family** (the differentiator):
| relation | from → to | meaning | drift anchor? |
| --- | --- | --- | --- |
| `implements` | intent/plan → structure | this code satisfies this requirement/task | **yes** (`anchor_hash`) |
| `tracks` | plan(task) → intent | this task works toward this requirement | — |
| `serves` | memory → intent/plan | this decision serves this goal | — |
| `concerns` / `constrains` | memory → structure | this decision/constraint governs this code | **yes** (`anchor_hash`) |
| `relates_to` / `semantically_similar_to` | memory/intent ↔ memory/intent | semantic link (embeddings + LLM) | — |

**Plan DAG** (OpenSpec): `requires` (plan/task → plan/task) — topological order, filesystem-derived state.

**Memory evolution**: `supersedes` (mem → mem, newer replaces older), `refines` (mem → mem),
`contradicts` (mem ↔ mem → flagged `AMBIGUOUS` for review).

**Drift** = on any `implements`/`concerns` edge, the target structure node's current `content_hash`
≠ the edge's `anchor_hash`. Detected on rebuild and on query; surfaced as a remediation injection.

## 3. Counters & lifecycle (the relevance/GC engine)

Maintained **on each node**, bumped atomically inside the single edge-mutation code path:

| counter | meaning | recomputable on rebuild? |
| --- | --- | --- |
| `refs_in` | # incoming semantic edges (`implements`/`serves`/`concerns`/`tracks`/`references`) → importance | yes (edge-derived) |
| `supersedes_out` | # nodes this one supersedes | yes |
| `superseded_in` | # nodes that supersede this one (`>0` ⇒ stale) | yes |
| `usage` | runtime # of times surfaced/injected → soft popularity | **no — authoritative in committed `graph.json`** |
| `last_seen` | most recent usage or edge-touch → recency | **no — in `graph.json`** |
| `survival` | # of commit/task boundaries survived un-superseded → drives `maturity` | **no — in `graph.json`** |

**Consistency rule:** edge-derived counters (`refs_in`/`supersedes_out`/`superseded_in`) and
`maturity` (= `working → settled` once `survival ≥ K`) are **recomputed** on every rebuild
(self-healing). The runtime counters (`survival`/`usage`/`last_seen`) are **not** recomputable from
files — they live in the committed `graph.json`, are **preserved** on rebuild, and are
**reconciled by the merge driver**: `survival` = max, `last_seen` = latest, `usage` = best-effort.

**Relevance** (O(1) from counters — no traversal):
```
relevance(n) = w1·log(1+refs_in) + w2·recency(last_seen) + w3·maturity_weight − w4·[superseded_in>0]
```
Used three ways:
- **Retrieval ranking** — a cheap prior fused with semantic + structural scores (§5).
- **Garbage collection** — `superseded_in>0 ∧ refs_in=0 ∧ usage=0` ⇒ delete (pure churn);
  `superseded_in>0 ∧ (refs_in>0 ∨ usage>0)` ⇒ keep as `rejected-alternative`/`archived` (it was
  acted on / referenced — historical value); stale ∧ never-referenced ∧ old ⇒ archive.
- **Maturity promotion** — `working → settled` once `survival ≥ K` with `superseded_in=0`
  (behavioral certainty, per memory-model §0; no self-reported confidence needed).

## 4. Storage layout & file↔graph mapping

```
yigraf/
├── config.yaml                        # committed — languages, ignore globs, K, weights
│
├── intents/<slug>.md                  # ┐ COMMITTED — source of truth for node content + edges
├── plans/{active,completed}/<slug>.md # │  one file per node (a plan file holds its task sub-nodes)
├── memory/<id>-<slug>.md              # ┘  edges + drift anchors in frontmatter (machine-written)
│
├── graph.json                         # COMMITTED — projection + AUTHORITATIVE runtime counters;
│                                      #   union-merge driver (max survival, latest last_seen)
├── index/                             # gitignored — embeddings over memory+intent (rebuildable)
└── cache/                             # gitignored — SHA256 content cache (rebuildable)
```

Structure nodes are **not** stored here — they're projected from the repo's own source via
tree-sitter; artifacts point into code by locator (`sym:<path>#<name>`).

**One file = one node** for intents and memory. A plan file holds the `plan` node *plus* its `task`
sub-nodes (checkbox state in the body, edges in frontmatter keyed by task id).

**File formats** (frontmatter carries ids, edges, and drift anchors — all machine-written by
`yigraf`; human-readability is not a goal for the *frontmatter*, so anchors etc. live there. Intent
and plan **bodies** are the exception: they hold authored spec content meant to be read — R9a):

`intents/session-expiry.md` *(body authored; frontmatter machine-written — R9a / `spec-lifecycle.md`)*
```markdown
---
id: int:session-expiry
type: requirement
status: active
---
## Requirement
The system SHALL expire a session after 30m of inactivity.
## Scenarios
- Given a session idle 30m, When a request arrives, Then respond 401 and clear the session.
## Design (how)
Optimistic-locked refresh; TTL in the session store. (Rationale lives in memory, not here.)
```

`memory/001-optimistic-locking.md`
```markdown
---
id: mem:001
type: decision
serves:   [int:session-expiry]
concerns: [{sym: sym:auth/session.py#refresh, anchor: H1a2b}]   # anchor = target hash at link time
supersedes: []
---
## session refresh uses optimistic locking
**Why:** refresh path is hot; a DB lock serializes it. A version-conflict retry is cheaper.
**Rejected:** pessimistic row lock — too much contention.
```

`plans/active/auth-hardening.md`
```markdown
---
id: plan:auth-hardening
edges:
  task:auth-hardening/1: {tracks: int:session-expiry, implements: [{sym: sym:auth/session.py#refresh, anchor: H1a2b}]}
---
# Auth hardening
## Tasks
- [ ] {#1} Implement idle expiry
- [x] {#2} Add session store
```

**Mapping rule (file → graph):**
1. one `.md` → one node (id from frontmatter); one code symbol → one structure node (id = locator).
2. frontmatter edge fields → edges, resolved by id; **unresolvable target ⇒ dangling edge (drift)**.
3. drift anchors live in the **declaring frontmatter** (`anchor:`), so they survive a rebuild;
   drift = `current_hash(target) ≠ stored anchor`.
4. authored in `.md`: node *content* + *edges* + *anchors*. Authoritative in `graph.json`: runtime
   *counters*. Everything else (structural nodes/edges, `refs_in`, `maturity`, effective status) is
   derived on build.

## 5. How the graph is used (three operations)

1. **Build / refresh** *(detached git hook, AST-only is free)*: tree-sitter → structure
   nodes/edges + `content_hash`es; parse `intents/`, `plans/`, `memory/` → those nodes + declared
   edges; recompute edge-counters + `maturity`; **preserve the runtime counters already in
   `graph.json`** (don't overwrite `survival`/`usage`/`last_seen`); (re)embed changed memory/intent
   statements. SHA cache → only changed files re-extract.
2. **Capture** *(runtime, at a commit boundary — memory-model §2)*: agent calls
   `yigraf remember/link`; appends a `memory/*.md` node + edge(s); bumps counters; embeds the new
   node. Mind-changes append a new node with a `supersedes` edge (counters handle the rest).
3. **Query / inject** *(runtime)*: `yigraf context "<q>"` or the fail-open hook → seed match
   (IDF/exact on structure+plan, embedding/semantic on memory+intent) → **bounded, hub-aware graph
   traversal** (Graphify) gathering the connected subgraph across families → rank by
   `α·semantic + β·graph_proximity + γ·relevance` → render within a token budget → **also emit any
   drift warnings** for `implements`/`concerns` edges in scope.

## 6. Worked example (all four families + counters + drift)

- Intent `int:session-expiry` (requirement: "sessions expire after 30m idle").
- Task `task:auth/3` `tracks → int:session-expiry`.
- Agent implements it → `implements` edge `task:auth/3 → sym:auth/session.py#refresh`, `anchor_hash=H1`.
  (`sym:…#refresh.refs_in` += 1)
- Agent chooses optimistic locking → `mem:001` (decision) `serves → int:session-expiry`,
  `concerns → sym:…#refresh`. (counters bump on all three)
- Agent later switches to pessimistic → `mem:002` `supersedes → mem:001`.
  `mem:001.superseded_in=1`; it *was* referenced, so it's kept as a `rejected-alternative`, not GC'd.
- Someone edits `refresh()` → its `content_hash` becomes `H2 ≠ H1` → **drift** on the `implements`
  edge → next time the agent touches that file the hook injects: *"task auth/3 (R session-expiry) is
  linked to refresh(), which changed since it was anchored — re-verify or relink."*
- Query *"how does session expiry work, and why?"* → seeds hit `int:session-expiry` + `mem:002`
  (semantic) and `sym:…#refresh` (structural) → returns the requirement, the implementing symbol, the
  **active** decision (`mem:002`, pessimistic) with `mem:001` available as the rejected alternative —
  ranked using the counters, all within budget.

## 7. v0 vs later

- **v0** (`docs/yigraf-v0.md`): structure family + plan/intent (lightweight) + `implements`/`tracks`
  edges + drift + the hook + `yigraf context`. Counters present but only `refs_in`/`superseded_in`
  needed. No embeddings yet (structural/IDF retrieval only).
- **Memory milestone**: memory family + `serves`/`concerns`/`supersedes` + capture-at-boundary +
  maturity + the embedding index (scoped hybrid) + full relevance/GC.
- **Later**: non-code modalities, auto-inferred edges, cross-project graph, team MCP.

## 8. Open questions

- `K` for maturity promotion, and the retrieval weights (`w*`, `α,β,γ`) — tune empirically.
- Merge-driver reconciliation for `usage` (max vs. sum-of-deltas); `survival`/`last_seen` merge
  cleanly (max/latest), `usage` is best-effort.
- Locator stability under refactors (rename/move): how aggressively to auto-relink vs. surface as
  drift.

*Resolved (2026-06-17): `graph.json` committed + shareable (union-merge driver); cross-family edges
in artifact frontmatter; runtime counters in `graph.json`; one file per node.*
