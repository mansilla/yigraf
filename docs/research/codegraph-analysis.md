# CodeGraph — analysis & what yigraf imports

> Study of [`colbymchenry/codegraph`](https://github.com/colbymchenry/codegraph) (cloned in
> `origins/codegraph`, gitignored), done 2026-06-28, and the plan for what yigraf learns from it.
> Sibling to `graphify-analysis.md` / `openspec-analysis.md`: an external tool we mine for ideas, not
> a dependency.

## 1. What CodeGraph is

A mature, shipping (1.0) **pure code-intelligence engine** — ~61k LOC of TypeScript, 24 languages via
tree-sitter, stored in SQLite+FTS5, served to 8 agents over MCP, kept fresh by a native file-watcher
daemon. One `codegraph_explore` call returns the **verbatim source** of the relevant symbols plus the
call paths (including dynamic-dispatch hops) and a blast-radius summary, so the agent stops grepping.

It is, essentially, the "structure + retrieval" layer yigraf's vision said to take from Graphify —
but a far more mature, multi-language, MIT-licensed realization of it. It **deliberately omits** intent,
plan, and memory (its maker is building those as a separate hosted product). So **CodeGraph and yigraf
are mostly complementary, not competitors**: yigraf's moat — the four-family governance graph, drift,
memory capture/maturity, the *enforceable* axis — is exactly what CodeGraph defers. CodeGraph even
states "no live correctness validation — that's the compiler/test/linter's job." That gap is yigraf.

## 2. Decision: import ideas, never build *on* it

We considered consuming CodeGraph as yigraf's structure engine (it's MIT, multi-language, battle-tested).
**Rejected — yigraf stays fully independent and imports ideas/heuristics with attribution.** The
principled reason, not just a preference: yigraf's drift anchor is a **per-symbol, AST-normalized,
name-excluded, reformatting-stable hash** (`astnorm-v1`, DESIGN R10). CodeGraph has no such thing — its
only hash is file-level `(size, mtime)` reconciliation for *sync*, not a per-symbol drift hash (verified
in its `schema.sql`: the `nodes` table stores ranges/signatures/docstrings but **no body hash**). So
even "consume it" would still force yigraf to re-parse every symbol to normalize it — the one dependency
you'd most want to offload (parsing) is welded to the differentiator (drift). "Build on" therefore adds
coupling (a Node binary + daemon + foreign DB, cross-language, on a soon-to-be-commercial competitor)
**without removing the work it was supposed to remove.** Owning the parse outright is barely more work
and far cleaner. Mining heuristics from its open source (MIT, with a `# adapted from CodeGraph` note) is
the opposite of a runtime dependency — that's what we do.

## 3. Lessons, ranked by leverage *for yigraf*

yigraf's value is governance, not code-intelligence depth — so the agent-adoption lessons (which serve
the moat's *adoption*) outrank the structure-depth ones (which serve a product yigraf isn't).

| # | lesson | status |
|---|---|---|
| 1 | **Adapt the tool to the agent** — can't steer tool *choice* via low-salience channels; one strong tool beats a menu; **errors teach abandonment** (one `isError`/non-zero exit and the agent stops calling it) | A1, A2 done |
| 2 | **Sufficiency over token-thrift** — the agent falls back to Read the instant output is insufficient; a token-cheap answer that triggers a Read costs more end-to-end | A3 shipped, default-off (§4) |
| 3 | **Eval discipline** — measure tool-calls/Read/Grep/time (not just tokens), n≥4, **floor model = Sonnet** | A4 done (`scripts/eval/`) |
| 4 | **Provenance-by-channel** (`synthesizedBy:<rule>`) + "partial coverage is worse than none" | Phase 3 (as derived edges land) |
| 5 | Structure depth — inheritance edges, Python relative imports, cross-file calls | Phase 3 pending |
| — | **Not importing:** dynamic-dispatch synthesizers, framework-route nodes, SQLite/FTS5, the daemon, multi-agent installer breadth — CodeGraph's *product*, not yigraf's moat | deferred |

Freshness banners (CodeGraph's staleness story) are a **non-issue** for yigraf: it rebuilds the graph
synchronously in every hook and `context` call, so there's no stale window to warn about.

## 4. The source-vs-signature decision (A3) — documented

CodeGraph's strongest claim is that returning **verbatim source** ("treat as already Read") is what makes
the agent stop reading, and that yigraf's **locator+signature** render (token-thrift) risks forcing a
Read that costs more overall. We took this seriously enough to build the experiment rather than argue it.

**What shipped:** a `retrieval.render` config knob (`signature_only` | `source_for_seeds`). `source_for_seeds`
renders the top `source_max_symbols` ranked symbols as verbatim, line-numbered source (`_source_block` in
`retrieval.py`), periphery as signatures. `root` is threaded through `context`/`context_for_locus`/
`session_context` so files can be read; absent root ⇒ graceful fallback to signatures.

**Default: `signature_only`** — and here's why we did *not* flip it on:

- **A/B (n=1, directional only — variance is huge: the without-arm swung 24→8 tool calls between
  identical runs):** with-yigraf crushed the baseline (3 tools / 1 Read / 19.5s vs 24 / 8 / 74s) — the
  legibility win is real. But isolating source-vs-signature (both arms *with* hooks, only the knob
  differing): source bought **zero** Read reduction (both hit 1 Read) while costing **~50% more tokens**
  (150k vs 98k).
- **Render-level data** (same query, both modes, on yigraf's own graph): source renders **far fewer
  nodes per budget** (30 vs 57) and **amplifies ranking-quality bugs** — a mis-ranked symbol
  (`cli.py#intent` surfacing for a *drift* query) grabs the expensive source slot, whereas in signature
  mode a wrong pick costs one line.

**So the bottleneck upstream of A3 is ranking, not render.** Flip `source_for_seeds` on only after
(a) an n≥4, multi-question A/B run in a real terminal (not nested), **and** (b) a ranking fix — the
semantic seeder on by default + the file/module-clutter suppression noted in `caveats.md` (M4/M6). The
knob is shipped and measurable; the evidence just says "not yet." See `scripts/eval/README.md` for how
to re-run the comparison.

## 5. Where the imported work lives

- `src/yigraf/cli.py` — A1 exit-0 guidance contract (`_guidance`/`_symbol_suggestion`/`_anchor_or_guide`).
  **Convention for any new agent-facing verb: use `_guidance`, never `typer.Exit(1)`** for recoverable
  conditions; reserve non-zero exit for genuine stop / CI gates (`drift`).
- `src/yigraf/retrieval.py` + `src/yigraf/config.py` — A3 render knob.
- `src/yigraf/hooks.py` — A2: SKILL.md/AGENTS.md present `yigraf context` as the one read verb.
- `scripts/eval/` — A4 A/B harness (`run_ab.py`, offline-testable `parse_run.py`, `cases.yaml`, README).
