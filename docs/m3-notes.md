# yigraf — M3 Implementation Notes (drift detection + rename handling)

> Pins the drift model and the **name-exclusion refinement to the anchor** (R10) that rename
> detection requires. Governed by `DESIGN.md` R4/R5 (drift), R7 (`implements`-only), R10/R11 (anchor);
> realizes the M3 milestone in `docs/BUILD-PLAN.md`. Builds on M2's `implements` edge + `dangling_*`
> stashes.

## 1. The drift model (glossary §4)

Computed over the built graph — no new persisted state:

- **soft drift** — the locator resolves (the structure node exists) but its current `content_hash`
  ≠ the edge's stored `anchor` (compared **only** when `anchor_algo` matches, R10). → "re-verify / relink."
- **hard drift** — the locator does **not** resolve (no such structure node, and no rename match). →
  "relink or remove." Sourced from the task node's `dangling_implements` stash (M2).
- **rename/move is NOT drift** — auto-re-anchored (§3). Emitted as an informational `renamed` line.

v0 is **`implements`-only** (R7): `tracks`/`requires` dangles are not drift. `verified`/reconcile
(R9c) is M4/M5, not here.

## 2. R10 refinement — the anchor excludes the symbol's own declared name

Rename detection needs the stored anchor to be a **rename-invariant fingerprint**: a pure rename
must yield the *same* hash so the moved locator can be matched by content. So `astnorm` now **drops
the symbol's own `name` identifier** from its `content_hash` (the `def NAME` / `class NAME` token).
Everything else stays — params, decorators, bases, body, and the `<def:NAME>` markers a *container*
emits for its members (so renaming a member still flips the enclosing class/module hash, a real
structural change).

Consequences:
- A pure rename (`foo`→`bar`, body identical) leaves `foo`'s body-hash **unchanged** → the edge
  re-anchors to `sym:…#bar` by exact hash match, no drift.
- Normal soft drift is unaffected (the name is unchanged when only the body is edited).
- **Safe to change now:** no anchors are persisted anywhere yet (only ephemeral test fixtures), so
  `astnorm-v1` is refined in place rather than bumped. Documented in `m1-notes.md` §4 + `DESIGN.md` R10.

## 3. Rename resolution (auto-re-anchor)

On build, after artifacts project, `drift.resolve_renames(graph)` walks each task's
`dangling_implements` (each carries `{sym, anchor, anchor_algo}`):

1. Index structure nodes by `content_hash`.
2. For a dangling entry, look its `anchor` up in the index (algo must match):
   - **exactly one** structure node matches → it's a **rename/move**. Add the `implements` edge to
     the new locator (carrying the anchor + `renamed_from: <old>`), drop the dangling entry. No drift.
   - **zero** matches → **hard drift** (genuinely deleted/changed-beyond-recognition). Left dangling.
   - **multiple** matches → ambiguous → **not** auto-re-anchored (hard drift, surfaced). Don't guess.

**In-memory only** — resolution mutates the graph (so `graph.json` shows the resolved edge and no
drift) but does **not** rewrite the authored plan frontmatter. Builds stay side-effect-free on
tracked artifacts (the post-commit hook never dirties a `.md`); because the anchor is the
rename-invariant body-hash, every rebuild re-resolves deterministically. Persisting the new locator
back to frontmatter is deferred (a future `yigraf drift --fix`); until then a rename-**then**-edit
shows as hard drift (relink is the honest remedy).

## 4. Surface — `yigraf drift`

`yigraf drift [path]` rebuilds, then prints soft/hard/renamed lines and exits non-zero iff any
**soft or hard** drift exists (renames don't count). This is an explicit *check*, not a workflow
gate (R8/R9c fail-open still governs the hook/editing path).

## 5. Out of scope for M3 (don't fold in)

- **Persisting rename re-anchors to frontmatter** (`--fix`) → later.
- **Rename + simultaneous body edit** → not auto-resolved (hard drift; relink). v0 matches on exact
  body-hash only; fuzzy similarity is post-v0.
- **`verified` predicate + reconcile messaging** (R9c) → M4 (`context`) / M5 (PostToolUse).
- **`concerns`/memory drift** → memory milestone (R7).
