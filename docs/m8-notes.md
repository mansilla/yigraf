# yigraf — M8 Notes (embedding index + semantic seeder + write-time dedup)

> The second slice of the post-v0 **memory milestone** (`docs/retrieval-design.md` §10,
> `docs/memory-model.md` §4 scoped-hybrid, `docs/capture-flow.md` §4 dedup). Adds **scoped semantic
> recall** — an embedding index over memory+intent text, fused with the lexical/IDF seeder — and the
> write-time near-duplicate guard. Built 2026-06-24 after M7. Optional by design: with the
> `[embeddings]` extra uninstalled, everything degrades to the v0 lexical seeder.

## 1. What shipped

- **`src/yigraf/embeddings.py`** — two layers kept separate (retrieval-design §10):
  - **model**: a pluggable backend, default **local `bge-small-en-v1.5`** via `sentence-transformers`
    (CPU, no API key, downloaded on first use). `get_embedder` never raises — a missing extra, an
    unknown backend, or a load failure all return `None` ⇒ lexical fallback.
  - **index**: a plain numpy matrix + id map under the gitignored `yigraf/index/` (`vectors.npy` +
    `meta.json`), brute-force cosine via one matmul. **No FAISS/vector-DB** — we embed only
    memory+intent (tens–thousands of short statements), so N is tiny.
- **Scope + cache**: `node_text` embeds only the memory + intent families (`statement` + `why` +
  alternatives / scenarios + design). `refresh_index` re-embeds **only nodes whose text-hash changed**
  and **loads the model only when there's work** — so a steady-state build with no spec/memory edits
  costs nothing (safe to call from `yigraf build` and the capture verbs).
- **Semantic seeder fusion** (`retrieval.context`): a new `semantic_match` param (`{id: cosine}`)
  is **unioned** into the seed set (union-of-top-k, each scorer cut independently — they're on
  different scales) and fused into the ranking `match` component (per-source min-max normalize, then
  max). `None`/empty ⇒ pure lexical (= v0). The CLI computes it via `embeddings.semantic_scores`.
- **Write-time dedup guard** (`capture-flow §4`): before `remember`/`note-constraint` creates a node,
  `most_similar_memory` finds the most similar *active* memory node sharing a serves/concerns target;
  over `embeddings.dup_cosine` (default 0.9) ⇒ refuse, point at it, suggest `supersede` or `--new`.
  Advisory and backend-optional (no backend ⇒ skipped). `supersede` skips the guard (a mind-change
  *should* resemble its predecessor).
- **Config + packaging**: `embeddings: {backend, model, dup_cosine}` in `config.yaml`/defaults; a new
  **optional `[embeddings]` extra** (`numpy`, `sentence-transformers`) in `pyproject.toml`.
- **Tests**: `tests/conftest.py` disables the embedder by default (autouse) so the whole suite stays
  deterministic + backend-independent; tests opt in with `@pytest.mark.embeddings`. `test_embeddings.py`
  adds 5 model-free tests (node-text scope, index round-trip, model-mismatch reindex, fusion seeds a
  node lexical misses, no-backend ⇒ lexical) + 2 model-gated (real recall ranks a paraphrase; the
  dedup guard blocks a near-dup and `--new` forces). Suite: **114 green** (112 without the extra).

## 2. The win (measured on yigraf's own repo)

The query **"how do we avoid paying for a vector database"** — near-zero lexical overlap with the
target — ranks `mem:004` ("embed only memory+intent … no vector DB at this scale") **first**. The
lexical seeder alone produces a degenerate stopword tie (every intent at the same score) and can't
discriminate. Semantic scoring ranks `int:memory-family` (0.65) and `mem:001` (0.64) at the top for a
paraphrased "keep the rationale around after the chat history is wiped". This is the memory-milestone
payoff: the *why* is findable by concept, not just by shared identifiers (the M4 caveat about
"lexical-only misses pure-concept queries").

## 3. Decisions (and why) — captured as memory in this repo

- **Embed only memory+intent, numpy brute-force, no vector DB** (`mem:004`). N is tiny; a query is one
  matmul (exact). FAISS/hnswlib add a heavy native dep that buys nothing below ~100k nodes.
- **The backend is an optional extra with graceful lexical fallback, never a hard dependency**
  (`mem:005`). No host exposes an embedding endpoint to a hook, so embeddings are yigraf's own
  responsibility; requiring `torch` for everyone would break the zero-config promise.
- **The suite disables embeddings by default** (conftest autouse + `embeddings` marker). The memory/
  retrieval logic is tested in isolation; the model is exercised by a small, opt-in, skippable set —
  keeps CI fast and honors "semantic recall is never required."
- **Hooks don't pay embedding cost.** The action-driven `PostToolUse` hook seeds from the touched
  locus (no NL query), so it never loads the model — only `yigraf context "<NL>"` and the capture
  verbs do.

## 4. Done-test

1. `yigraf build .` → downloads `bge-small`, writes `yigraf/index/{vectors.npy,meta.json}` with one
   vector per memory+intent node; a no-change rebuild re-embeds nothing. ✓
2. A paraphrased, lexically-disjoint `yigraf context` query ranks the conceptually-right memory/intent
   node at the top (semantic > lexical's flat tie). ✓
3. `remember` a near-paraphrase of an existing decision → refused with a pointer to the original;
   `--new` forces it; `supersede` is never guarded. ✓
4. Uninstall the extra (or `backend: none`) → `get_embedder` is `None`, `semantic_scores == {}`,
   retrieval == v0 lexical. The 112 non-embeddings tests pass with no numpy/torch. ✓

## 5. Next / open

- **M9 — counters/maturity/GC + runtime telemetry**: `survival`/`usage`/`last_seen`, `working→settled`
  promotion at `K`, the GC pass (churn deletion / rejected-alternative retention), recency + maturity
  in the relevance prior, merge-driver reconciliation.
- **`dup_cosine` tuning** (caveat): 0.9 catches tight paraphrases but lets looser restatements through
  (`bge-small` cosines for paraphrases sit ~0.8–0.9). Contradiction detection (same target, *opposed*
  statement) is still heuristic-only — capture-flow §7's open question (heuristic vs a cheap LLM check).
- **Other backends** (`ollama`/`openai`/`voyage`) are stubbed to "degrade" in `get_embedder`; wiring
  them is a later extra.
