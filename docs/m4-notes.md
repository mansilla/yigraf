# yigraf — M4 Implementation Notes (retrieval / `yigraf context`)

> What v0's `yigraf context` actually implements against the full design in
> `docs/retrieval-design.md`. Governed by R7 (lexical-only v0, no embeddings) and R9c (the reconcile
> signal). Most of M4 is a faithful build of retrieval-design §1–§6; this notes only the v0-specific
> choices and the one schema addition.

## 1. Pipeline (v0 subset)

`seed → bounded traversal → fusion rank → token-budgeted render → drift surfacing`, exactly
retrieval-design §1, **lexical/IDF seeder only** (R7 / §8) — no embedding/semantic seeder yet, so
purely conceptual "why" queries that share no identifiers with the intent text seed weakly. Over
structure + intent + plan (no memory family yet).

- **Seed:** IDF-weighted term overlap, **exact > prefix > substring** precedence (§2); top-`k` with a
  >50% score-gap cutoff, capped at `seed_cap`.
- **Traverse:** bounded BFS over the **undirected** edge set (relationships matter regardless of
  direction), depth `max_hops`, node cap `node_budget`; **hub-aware** — a node with degree ≥
  `max(hub_floor, p99)` is included but not expanded through. On small graphs the floor (50) means no
  hubs, so nothing is pruned.
- **Rank:** `α·match + β·proximity + γ·relevance`, each min-max normalized within the candidate set.
  `match` = the seeder score; `proximity` = `1/(1+hops)`; `relevance` = `w1·log(1+refs_in) − w4·[superseded]`
  computed **on the fly** (counters aren't materialized on nodes yet — recency/maturity are memory-era).
- **Render:** greedy fill by score until a `char ≈ 3·token` budget; grouped by family
  (`Intent` / `Plan & tasks` / `Code` / …); structure nodes render as **locator + signature, not
  source**; elision note when truncated.

## 2. Schema addition — `signature` on structure symbol nodes

Rendering "locator + signature, not source" needs the declaration line, which M1 didn't store. M4
adds a `signature` field (`def f(a) -> b:` / `class C(Base):`, whitespace-collapsed, decorators
excluded) to function/class/method nodes during extraction. Cache format bumped to **2** so any
pre-signature cache re-extracts. File/module nodes carry no signature.

## 3. Reconcile (R9c) — derived, no new state

For each intent with `status: satisfied`, `verified` = it has ≥1 task that `tracks` it whose
`implements` edge is **not** in the drift set (from `compute_drift`). `satisfied ∧ ¬verified` →
a reconcile line. Drift lines are shown for in-scope (traversed) `implements` edges; both are
reserved against the budget before node fill (§6). v0 only inspects the task→intent→implements path
(all v0 links are task-based); a direct intent→symbol `implements` isn't checked for `verified`.

## 4. Out of scope for M4 (don't fold in)

- **Semantic/embedding seeder** + the `index/` — memory milestone (R7 / retrieval-design §10).
- **Action-driven seeding** (locus → seed, no NL) lands with the **PostToolUse hook in M5**; M4 is
  the query-driven path only.
- **Real tokenizer** — v0 uses Graphify's char≈3:1 estimate; fine for budgeting, not exact.
- **Materialized counters / recency / maturity** in `relevance` — memory milestone.
