# yigraf — M2 Implementation Notes (intent/plan artifacts + linking)

> Pins the artifact schema and the link→anchor→commit timing **before** code. Governed by
> `DESIGN.md` R5 (commit boundary), R7 (`implements`-only), R9a/b/c (spec lifecycle); realizes the
> file formats in `docs/graph-design.md` §4 and the M2 milestone in `docs/BUILD-PLAN.md`. Builds on
> M1's structure family + `astnorm` anchor (`docs/m1-notes.md`).

## 1. What M2 adds

The **intent** and **plan** node families, the cross-family edges that join them to M1's structure
nodes (`tracks`, `implements`, `requires`), and the three authoring verbs that write the artifacts
those families project from. `yigraf build` now reads `yigraf/intents/` and `yigraf/plans/` in
addition to source. v0 enforcement stays `implements`-only (R7); memory/`concerns` are post-v0.

## 2. Artifact schemas (the authored truth — D2)

**One file = one node** (a plan file also holds its task sub-nodes). Bodies are authored/readable;
`edges` frontmatter is machine-written. Mirrors `graph-design.md` §4 + `spec-lifecycle.md` §1 (R9a).

### `yigraf/intents/<slug>.md`
```markdown
---
id: int:<slug>
family: intent
type: requirement          # requirement | goal | capability
status: proposed           # proposed | active | satisfied | archived  (soft guide, R9b)
---
## Requirement
The system SHALL … (one-line behavioral contract, SHALL/MUST)

## Scenarios
- Given …, When …, Then …

## Design (how)
<optional approach; rationale lives in memory, not here>
```
Projects to one `intent` node: `statement` (## Requirement body), `scenarios` (## Scenarios bullets,
list), `design` (## Design body, optional), `type`, `status`.

### `yigraf/plans/{active,completed}/<slug>.md`
```markdown
---
id: plan:<slug>
family: plan
edges:
  task:<slug>/1:
    tracks: int:<intent-slug>
    requires: [task:<slug>/2]
    implements:
      - {sym: "sym:<path>#<name>", anchor: <hash>, anchor_algo: astnorm-v1}
---
# <Title>
## Tasks
- [ ] {#1} implement idle expiry
- [x] {#2} add session store
```
Projects to: a `plan` node (`kind: plan`, label = title) + one `task` node per checkbox
(`kind: task`, `id: task:<slug>/<n>`, `state: todo|done` from `[ ]`/`[x]`, `order: n`,
`description`). Edges: `contains` (plan→task), `tracks` (task→intent), `requires` (task→task),
`implements` (task→symbol, carrying `anchor` + `anchor_algo`).

**ID schemes** (`graph-design.md` §1): `int:<slug>`, `plan:<slug>`, `task:<slug>/<n>`. Slugs are
casefolded (path-style ids already are, M1); intents/plans are author-named so the slug is the key.

## 3. The verbs (write surface)

| verb | writes | result |
| --- | --- | --- |
| `yigraf intent <slug>` | `intents/<slug>.md` | statement (`--statement`) + scenarios (`--scenario`, repeatable) + optional `--design`; `--type`/`--status` |
| `yigraf plan <slug>` | `plans/active/<slug>.md` | `--title` + tasks (`--task`, repeatable → todo checkboxes) |
| `yigraf link <task> <target>` | the plan's `edges` frontmatter | `sym:…` target → `implements` (anchor stamped, §4); `int:…` target → `tracks` (no anchor) |

Create verbs refuse to clobber an existing file (idempotent-safe). After any write the graph is
rebuilt so `graph.json` reflects it.

## 4. Link → anchor → commit timing (the one load-bearing decision)

R5's *goal*: the linking session shows **no** false drift, but a later un-relinked change to the
symbol **does** drift. R5's named *mechanism* — a post-commit hook that stamps anchors — has a flaw
if taken literally: writing anchors into frontmatter *after* the commit leaves a dirty tree and a
commit whose state lacks the anchor. M2 realizes R5's goal with a cleaner split:

1. **`yigraf link` stamps the anchor immediately** from the *current working-tree* content: it
   parses the target symbol's file, takes its `astnorm` `content_hash`, and writes `anchor` +
   `anchor_algo` into the plan frontmatter. The edge is armed at once — the session shows **no
   drift** and the commit naturally carries the anchor. This anchor is **authoritative**.
2. **The `post-commit` hook (`yigraf install-hooks`) rebuilds `graph.json` to HEAD** — the
   "detached AST rebuild" of the BUILD-PLAN. In the normal flow (link, then commit the plan +
   rebuilt graph together) the rebuild is **byte-identical** → no-op; if code was committed without
   a rebuild, it refreshes the projection.

**Deliberately NOT done: automatic anchor re-stamping at commit.** If a symbol is edited *after* it
was linked, without a re-link, that **should** surface as drift ("re-verify / relink") — masking it
by silently re-anchoring to committed content would defeat R9c (drift re-opens a verified spec).
Re-linking (`yigraf link` again) is the explicit re-verify gesture that re-stamps. This is a
refinement of R5's *mechanism* in service of its *goal* + R9c — worth a Decision-Log note.

**Drift** stays derivable with no extra state: `edge.anchor ≠ target_node.content_hash` (compared
only when `anchor_algo` matches, R10). Full soft/hard-drift surfacing + rename re-anchor is **M3**.

## 5. Out of scope for M2 (don't fold in)

- **Soft/hard drift surfacing + rename auto-re-anchor** → M3. M2 only stores the anchor and keeps it
  matching at link/commit time.
- **The `verified` predicate + reconcile lines** (R9c) → computed in M4 (`context`) / surfaced in M5
  (PostToolUse). M2 stores `status` and the `implements` edge it builds on.
- **Unresolvable link targets.** If a symbol/intent id doesn't resolve, the edge is **not** added as
  a phantom node — the unresolved id is stashed on the task node (`dangling_*`) for M3 to surface as
  hard drift. M2's done-test path resolves cleanly.
- **`why`→memory capture, the guided authoring skill** → memory milestone / M5 (`authoring-skill.md`).
- **Completed-plan / archival semantics** beyond reading `plans/completed/` → later.
