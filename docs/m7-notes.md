# yigraf — M7 Notes (memory node family + capture verbs)

> The first slice of the post-v0 **memory milestone** (`docs/BUILD-PLAN.md` §Post-v0,
> `docs/memory-model.md`, `docs/capture-flow.md`). Adds the fourth node family — **memory** — and the
> verbs that capture it. Deliberately **deterministic and embedding-free**: the semantic seeder +
> write-time dedup (M8) and the maturity/GC/telemetry engine (M9) come next. Built 2026-06-24 after M6.

## 1. What shipped

- **`src/yigraf/memory.py`** — the authored `.md` truth for the memory family. One file per node under
  `yigraf/memory/<seq>-<slug>.md`, mirroring the intent/plan artifact pattern (`docs/graph-design.md`
  §4): body authored (`## <statement>`, `**Why:**`, `**Rejected:**`), frontmatter machine-written
  (`id`, `type`, `serves`, `concerns` + anchors, `supersedes`, `status`, `maturity`, `provenance`).
  Types: `decision | constraint | rationale | rejected-alternative | learned-fact | preference`.
- **Capture verbs** (`yigraf …`):
  - `remember "<statement>" --type … --why … [--serves <id>…] [--concerns <sym>…] [--rejected …]`
  - `note-constraint "<rule>" [--concerns <sym>…]` — a `constraint` node flagged `promotable`
  - `supersede <old-id> "<statement>" --why …` — a mind-change as a *new* node + `supersedes` edge,
    never an in-place edit (capture-flow §0a invariant).
- **Projection** (`memory.project_into`, wired into `build_graph` after intent/plan, before
  `resolve_renames`): memory nodes + `serves` (→ intent/plan), `concerns` (→ structure, **anchored**),
  `supersedes` (→ memory) edges. Unresolved targets stash `dangling_*` instead of conjuring phantoms.
- **`concerns` is the second drift-bearing relation.** `drift.py` was generalized from
  `implements`-only to a `{implements, concerns}` table, so a decision anchored to code inherits
  rename re-anchoring + soft/hard detection **for free** — one code path, both relations. Each
  `DriftItem` now carries its `relation` so the reconcile line is worded per kind ("re-verify this
  decision still holds" vs "re-verify or relink").
- **Counters.** `memory.recompute_counters` materializes the edge-derived `superseded_in` /
  `supersedes_out` on memory nodes each build (self-healing, graph-design §3). Retrieval's relevance
  prior already penalizes `superseded_in > 0`, so the active decision out-ranks its superseded
  predecessor while the predecessor stays available.
- **Retrieval render.** `_searchable` matches a memory on its `statement` + `why` + `alternatives`;
  the `Decisions (why):` group renders `mem:NNN [decision]: <statement> — why: … (serves …; concerns …)`,
  tagging a stale node `[decision·superseded]`. The action-driven hook surfaces a `concerns`-linked
  decision (and its drift) when the governed code is edited — verified on a scratch repo.
- **Skill + AGENTS block** (`hooks.py` templates) now teach the capture ritual: `remember` the
  non-obvious *why* at task completion, `note-constraint` a correction, `supersede` a mind-change.
- **14 tests** (`tests/test_memory.py`); suite is **107 green** (was 93). No-change rebuild stays
  byte-identical with memory nodes present.

## 2. Decisions (and why)

- **`concerns` reuses the `implements` drift machinery rather than a parallel path.** The two relations
  differ only in source family and the dangling-attr name; folding them into one table means rename
  re-anchoring, the SHA cache, and soft/hard detection are written once. (This decision is itself a
  candidate to `remember` when dogfooding — §4.)
- **Capture mechanism = agent-asserted only (memory-model §5, option A).** No pre-`/clear`
  distillation backstop yet. Cheapest, deterministic, `EXTRACTED` confidence; mirrors the v0
  `implements` pattern we already trust. Revisit (option B) once links prove valuable.
- **No embedding dedup in M7.** Without the index, write-time dedup is trivial; `remember` does not yet
  detect near-duplicates or contradictions (capture-flow §4) — that arrives with the M8 index.
- **`maturity` is authored, not earned, in M7.** Every node is `working`; the `working → settled`
  promotion needs the runtime `survival` counter, which is M9 (telemetry). Kept the field so the
  artifact format is stable across milestones.
- **`provenance` is minimal (`{source: cli}`), no timestamp.** Avoids coupling capture to a wall clock
  before the telemetry milestone; `anchor_commit`/`ts` land with M9.
- **Counters stamped only on memory nodes.** Only memory carries `supersedes` edges, so stamping
  `superseded_in: 0` on every structure node would just bloat `graph.json`; retrieval reads the counter
  with a `0` default.

## 3. Done-test (memory-model / capture-flow, on a scratch repo)

1. `remember "session refresh uses optimistic locking" --serves int:… --concerns sym:…#refresh
   --rejected "pessimistic row lock"` → `mem:001` with `serves`/`concerns` edges; the `concerns` edge's
   anchor equals the symbol's `content_hash` (no drift fresh). ✓
2. Edit `refresh()` body → **soft `concerns` drift** surfaces (alongside the `implements` drift), and
   the `PostToolUse` hook injects the governing decision + both drift lines. ✓
3. Rename `refresh`→`renew` (body identical) → the `concerns` edge **auto-re-anchors**, no drift. ✓
4. `supersede mem:001 "… pessimistic locking"` → `mem:002` with a `supersedes` edge; `context` ranks
   `mem:002` (active) above `mem:001` (`·superseded`), both available. ✓
5. `note-constraint "refresh() must not block over 50ms" --concerns sym:…#refresh` → a `promotable`
   `constraint` node. ✓

## 4. Next

- **M8 — embedding index + semantic seeder** (`docs/retrieval-design.md` §10): `bge-small` default as
  an optional extra, numpy brute-force cosine over **memory + intent only**, fused with graph
  proximity, graceful fallback to lexical when no backend. Then write-time dedup/contradiction
  (capture-flow §4).
- **M9 — counters/maturity/GC + runtime telemetry**: `survival`/`usage`/`last_seen`, `working → settled`
  promotion at `K`, the GC pass, recency/maturity in the relevance prior, merge-driver reconciliation.
- **Boundary nudges** (capture-flow §0a boundaries A/B): `UserPromptSubmit`/plan-mode-exit hooks that
  nudge `remember`/`intent`/`plan`. New host wiring — deferred; M7 ships the in-flow skill path + the
  existing `PostToolUse` boundary C.
- **Dogfood**: capture yigraf's own M7 design decisions as real memory nodes (e.g. the `concerns`-reuse
  decision above), so the memory family is self-hosted like the rest.
