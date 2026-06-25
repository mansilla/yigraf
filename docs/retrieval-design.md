# yigraf — Retrieval & Ranking

> How a request becomes a scoped subgraph rendered within a token budget (the "legible" payoff).
> Builds on `docs/graph-design.md` (data model, counters) and the scoped-hybrid decision in
> `docs/memory-model.md` §4. Borrows Graphify's IDF + hub-aware + token-budgeted retriever and
> extends it across the four node families.

## 0. Two triggers, one pipeline

| trigger | "query" is… | seeding |
| --- | --- | --- |
| **Query-driven** — agent runs `yigraf context "how does session expiry work, and why?"` | an NL string | hybrid seeders (§2) |
| **Action-driven** — fail-open hook fires as the agent is about to `Edit`/`Read` a file | the **locus** (file/symbol being touched), no NL | seed = the structure node(s) for that locus |

Both converge after seeding into the same **traverse → rank → render → surface-drift** pipeline.
Action-driven is the "can't-see-it-⇒-doesn't-exist" injection: no question asked, we proactively
surface what governs the code being touched.

## 1. Pipeline
```
seed  →  bounded traversal  →  fusion ranking  →  token-budgeted render  →  drift surfacing
```

## 2. Seeding (hybrid, scoped) — pick the few nodes the request is "about"

Bad seeds ruin everything downstream, so seeding is deliberately conservative.

- **Lexical/structural seeder** (Graphify's IDF): tokenize the query; score nodes by IDF-weighted
  term overlap on labels/identifiers with **exact > prefix > substring** precedence. Primary for code
  identifiers (`validateToken`, `session.py`) and plan/intent titles. Runs over all families.
- **Semantic seeder** (embeddings, **scoped**): embed the query; k-NN over the embedding index built
  **only over memory + intent** node statements. Primary for conceptual/"why" queries.
- **Action-driven:** skip both — resolve the touched path→`file`, line range→`symbol`; those are the
  seeds.

**Merge + cutoff:** take top-`k` from each seeder, union them. Within each seeder apply Graphify's
**score-gap cutoff** (stop adding seeds at the first big score drop, so noise terms don't each become
a seed). Union-of-top-k avoids comparing lexical and semantic scores on different scales at seed time.
Hard cap seeds at a small `S` (≈3–8).

## 3. Bounded traversal — gather the connected neighborhood across families

From seeds, expand to pull in the relevant subgraph (from a code symbol → its intent, task, decisions).

- **Bounds:** max hop depth `d` (≈2–3) and a max node budget `N` — whichever hits first.
- **Hub-aware (Graphify):** include a super-hub node (degree > p99, floored ≈50) but **do not traverse
  through it** — utility funcs / god-nodes would otherwise explode the subgraph.
- **Edge-type filter by intent:** bias which relations to follow from the request shape —
  - "why / decided" → `serves`, `concerns`, `supersedes` (memory edges)
  - "who calls / structure" → `calls`, `imports`, `implements`
  - "what's left / plan" → `requires`, `tracks`, task state
  - action-driven → `implements`, `concerns`, `tracks` (surface governing intent + drift first)
- **Always include** drift-bearing `implements`/`concerns` edges touching in-scope structure nodes,
  even if not "asked for" (so §6 can fire).

Output: a connected, hub-pruned subgraph (nodes + edges).

## 4. Fusion ranking — order candidates to fill the budget

Each gathered node gets:
```
final(n) = α·match(n) + β·proximity(n) + γ·relevance(n)
```
- **match** — query-match strength: semantic sim (memory/intent) or IDF lexical score (structure/plan)
  from whichever seeder hit it. Nodes pulled in *only* by traversal have `match=0` and rank on the
  other two (correct: a symbol reached via `implements` from a matched intent is relevant by proximity).
- **proximity** — closeness to seeds, `1/(1+hops)` (structural relevance to what was asked).
- **relevance** — the O(1) counter prior from `graph-design.md` §3:
  `w1·log(1+refs_in) + w2·recency − w4·[superseded_in>0]` + maturity weight. Query-independent
  importance/freshness.

Normalize each component within the candidate set (min-max → weighted sum; RRF as fallback if scales
prove unstable). `α,β,γ` tunable.

Special cases:
- **Superseded memory** is down-weighted (the `−w4`) but kept available — the *active* decision ranks
  high, its superseded predecessor surfaces only if budget allows or the query is explicitly historical.
- **Drift always survives trimming** (see §6) — it's a safety signal, not a search result.

## 5. Token-budgeted rendering — the map, not the territory

Greedy fill by `final(n)` until the budget is hit. Output is **compact and structured**, never raw
file dumps:
- per node: `id`, label/statement, and its key edges (so the agent sees connections);
- structure nodes render as **locator + signature**, *not* source — the agent opens the file only if
  it needs to. This is the token-efficiency core: pointers + relationships, not content.
- grouped by family for legibility: `Intent:` / `Plan & tasks:` / `Code:` / `Decisions (why):` /
  `⚠ Drift:`.
- **Budget tiers:** hook-injection is *tight* (~0.5–1k tokens — we're interrupting the agent: governing
  intent + active decisions + drift only). Explicit `yigraf context` gets a larger budget.
- **Narrowing hint** when truncated (Graphify): "N more elided — narrow with
  `yigraf context '…' --family memory` / `--symbol X`."

## 6. Drift surfacing (cross-cutting, always on)

Any in-scope `implements`/`concerns` edge with `current_hash(target) ≠ anchor`, or an **unresolvable
locator** (dangling edge), emits a remediation line with reserved budget — surfaced regardless of
ranking. This is the "enforceable" payoff riding along every retrieval.

## 7. Two worked traces

**Query — "why do we expire sessions?"** → semantic seeder hits `int:session-expiry` + `mem:002`;
traverse `serves`/`concerns` → the implementing symbol; rank; render: the requirement + the *active*
decision and its `why` + a pointer to `auth/session.py#refresh` (signature only). `mem:001` (rejected
optimistic locking) elided unless budget/historical.

**Hook — agent about to `Edit auth/session.py`** → seed = `sym:…#refresh`; traverse
`implements`/`concerns`/`tracks` → `int:session-expiry`, `task:auth/3`, `mem:002`; detect `mem:001`
superseded; detect `refresh()` hash ≠ anchor → **drift**. Tight injection:
> This implements **R session-expiry** (task auth/3). Active decision: **pessimistic locking** (mem:002).
> ⚠ `refresh()` changed since the task was anchored — re-verify it still satisfies R, or relink.

## 8. v0 vs later

- **v0:** action-driven hook + query-driven with the **lexical/IDF seeder only** (no embeddings yet);
  traversal + drift surfacing; ranking with `match` + `proximity` + a basic `relevance` (`refs_in`,
  `superseded_in`). Proves the legible+enforceable loop on structure+plan.
- **Memory milestone — M8 (done):** the **semantic seeder** + embedding index (scoped hybrid, §10) is
  shipped — unioned with the lexical seeder, fused into `match`, graceful lexical fallback;
  superseded/rejected-alternative handling lands with the memory family (M7). **Still M9:** the full
  counter `relevance` (recency `w2` + maturity `w3`) once the runtime telemetry counters exist.

## 9. Default parameters (set by intuition + Graphify; all tunable in `config.yaml`)

| param | default | note |
| --- | --- | --- |
| seed top-k / seeder | 5 | union of lexical + semantic |
| seed cap `S` | 6 | after score-gap cutoff |
| score-gap cutoff | relative drop > 50% | stop adding seeds |
| hop depth `d` | 2 | |
| node budget `N` | 60 | gathered candidates |
| hub threshold | p99 degree, floor 50 | Graphify — include but don't traverse through |
| `α` match | 0.5 | query-match dominates |
| `β` proximity | 0.3 | |
| `γ` relevance | 0.2 | the counter prior |
| `w1` refs_in (log) | 1.0 | |
| `w2` recency | 0.5 | exp decay on `last_seen` age |
| `w3` maturity | settled +0.3 / working 0 | |
| `w4` superseded penalty | 1.5 | strong — superseded sinks but stays available |
| maturity promote `K` | `survival ≥ 3` | working → settled |
| normalization | min-max → weighted sum | RRF fallback if scales misbehave |
| char : token | ≈ 3 : 1 | Graphify, for the budget cut |
| budget — hook inject | ~800 tok | tight; we're interrupting |
| budget — `yigraf context` | ~4k tok | configurable |

Action-driven retrieval (no NL) effectively ranks on `β + γ` (match ≈ 0) — proximity to the locus +
counter importance. The hook is **silent unless** the locus has a governing intent/memory edge or a
drift to report (no nagging on routine edits).

Still genuinely open: how much budget to reserve for drift; multilingual embeddings (§10).

## 10. Embedding engine

**Two separate layers — don't conflate them:**
- **Embedding model** (text → vector): bge-small, MiniLM, OpenAI text-embedding-3, …
- **Vector index/store** (holds vectors, does nearest-neighbor search): FAISS, hnswlib, Chroma, …

FAISS is *only* the index layer — it does **not** generate embeddings; you feed it vectors you
already computed. (Tools like Chroma/txtai/LanceDB *bundle* a model + index, which is where the
"FAISS embeds" confusion comes from.) So we need a model regardless of index choice.

Embeddings (the model layer) are **yigraf's own responsibility** — unlike Graphify's LLM extraction
(which borrows the host session), no host exposes an embedding endpoint to a hook/skill. So the only
zero-config option is a **local model**, and that's the default.

**Index layer: no vector DB at our scale — plain numpy brute-force.** Because we embed only
memory+intent (not code), N is small. Worst case ~10k nodes × 384-dim × 4 B ≈ 15 MB; a query is one
matmul (~sub-ms, exact). An ANN index (FAISS/hnswlib) buys nothing here and adds a heavy native dep,
so we skip it until N is very large (≈100k+), then add `hnswlib` (lighter than FAISS) as an optional
extra. The "index" is just a numpy matrix + id map in the gitignored `index/`.

- **Default:** a small **local sentence-transformers** model — `bge-small-en-v1.5` (384-dim, ~130 MB,
  strong quality-for-size, permissive license), CPU, **no API key**, downloaded and version-pinned on
  first use (reproducible). Ultra-light fallback: `all-MiniLM-L6-v2`.
- **Scope keeps it cheap:** we embed **only memory + intent** text (`statement`+`why`+`type`) — a small
  set (decisions/requirements: tens–thousands, *not* the codebase). One vector per node, **no chunking**
  (statements are short). Re-embed only changed nodes (SHA cache).
- **Index = plain files + brute-force cosine.** For small N, a numpy matrix + id map under the
  gitignored `index/`, cosine via matmul — no FAISS/vector-DB until N is large (then `hnswlib` as an
  optional extra). Repo-local, derived, rebuildable.
- **Pluggable backends** (optional extras, à la Graphify's `[mcp]`/`[neo4j]`): `ollama`
  (nomic-embed-text), `openai` (text-embedding-3-small), `voyage`/`cohere`. Model name+revision pinned
  in `config.yaml`; changing it forces a full reindex.
- **Graceful degradation:** no embedding backend ⇒ seeding falls back to **lexical/IDF only** (= v0).
  Semantic recall is an enhancement, never a hard dependency.
- Multilingual: English default; `bge-m3` / `multilingual-e5-small` as a config option later.
