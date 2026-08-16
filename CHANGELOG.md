# Changelog

All notable changes to yigraf are recorded here. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/); yigraf uses
[semantic versioning](https://semver.org/).

## [Unreleased]

A workspace yigraf cannot write to is now a condition it survives and explains, rather than one it
crashes on. Both caches under `yigraf/` — the SQLite materialized view and the tree-sitter parse cache
— are *derived* (design law #6), so neither losing a write can cost an answer; until now either one
ended the command in a raw storage traceback. No behaviour changes on a writable workspace.

### Fixed
- **An unwritable `yigraf/.local/` no longer takes down `build` — or, worse, `context`.** A read-only
  `.local/` (a restrictive umask, a full disk, a `graph.db` left root-owned by a `sudo yigraf` run)
  raised `sqlite3.OperationalError` straight through Typer: `yigraf build` **and** `yigraf context`
  both exited 1 on a ~40-line traceback. The read path was the sharper break — a `context` query whose
  answer was already computed failed because its *cache* could not be refreshed, which is exactly the
  fail-open guarantee design law #5 makes to hooks. `graphdb.materialize` now raises a typed
  `ViewUnwritable` carrying the fix, and both seams degrade to an uncached rebuild: reads answer
  normally and silently, `build` prints its real index counts and then the guidance at exit 0, and a
  capture (`remember`, `link`, …) warns but still reports the artifact it already wrote to disk. The
  guidance leads with *nothing was lost* — `graph.db` is a projection of the markdown, and an agent
  that doesn't know that reads any write failure as data loss. The catch stays narrow (`OSError` +
  `sqlite3.OperationalError`), so a genuine bug still surfaces as itself.
- **An unwritable `yigraf/cache/structure.json` no longer takes down the same two commands.**
  `StructureCache.load` had always started empty on an `OSError`; `save` had no such guard, so one
  read-only parse cache raised `PermissionError` from `cache.py` during `build_graph` — before the
  materialized view was ever reached. It now fails open to a re-parse, silently: any condition that
  refuses this write refuses the view in the same workspace, and that surface already names the path
  and the fix, so the operator hears about it once (design law #4). A fully read-only `yigraf/` now
  builds and queries cleanly, emitting exactly one line of guidance.

## [1.3.1] — 2026-08-13

Six fixes from the first field report on the 1.3.0 shared-log line (one developer, one repo, a day of
heavy use) — every one a case where a surface reached the agent unbidden and made its next action
worse. No new capability; local, unlinked workspaces are unaffected.

### Fixed
- **`status`'s `⚠ n diverged` count no longer ratchets upward on ordinary solo work.** Divergence's
  test was "declined, and its id is not in the current files" — but for a revisioned family
  (`int:`/`task:`) the id *is* the revision, so every edit to an already-pushed plan or intent left
  its previous revision in the log matching that test exactly: a disagreement with nobody. Re-linking
  8 stale completions on yigraf's own single-actor log produced 8 phantom, unclearable divergences.
  `OnlineLog.superseded_revisions` now triages the declined set: an id the same actor has since
  replaced with the live revision is that actor's own history, not a second principal's copy — keyed
  on `(locator, actor)` and strictly-earlier arrival, so a genuine disagreement from another principal
  is never filtered.
- **The ✔ proof-obligation block was emitted in full, outside the render budget.** `_render` counted
  it into `used` but never bounded it, so on a heavily-governed locus `used` began past `char_budget`
  and every node's fit-test failed before a single symbol was placed — measured before: `cli.py`
  injected 3833 tokens against an 800 budget, 0 of 86 nodes rendered. Obligations now take a share of
  what the ⚠ warnings leave, admitting whole governing intents in governance-density order; the drift
  block caps the same way (hard drift first, tailing to the uncapped `yigraf drift`); the render frame
  itself is now charged. Repo-wide after: every packet ≤ 796/800, nodes rendering everywhere.
- **`reaffirm --evidence` could upsert a `grounded_by` ref but never retire one.** A ref whose target
  was deleted had no verb that could clear it, so an `·empirical` belief went on citing evidence that
  no longer existed. `unlink mem:<id> <ref>` retires it — refusing to strand the belief by declining
  to retire its last remaining ref.
- **A `file:` anchor was write-only at the moment of action.** `remember --concerns file:docs/x.md`
  was accepted, stored, and answered by `yigraf context` — but the PostToolUse hook discarded the
  answer before asking, because `.md` isn't an extracted language. The gate now admits a file with a
  hand-placed `file:` anchor node even when its suffix isn't indexed; an un-anchored `.md` still stays
  silent.
- **`status`'s context percent traveled without its denominator**, so `ctx 94%` on a 1M-token host
  read as "nearly out of room" while the host's own readout said 24%, 764k free. Both renders now
  trail the percent with the physical pair (`ctx 94% 236k/1M`); the TTY status line adds a
  self-silencing note spelling out what the percent is of.
- **A moved symbol's stale `implements` entry had no verb that could clear it.** `link` keys by exact
  locator, so re-linking after a move appended a new entry and left the old one as hard drift
  `reaffirm`/`supersede` couldn't touch. `unlink` now retires it — exposed over MCP too, so a
  pull-only host can clear a stale link.

### Changed
- Drift/reconcile lines now carry the resolving verb with ids pre-filled and are kind-aware
  (`reaffirm` is never offered for hard drift, which it cannot re-anchor) — the one surface that
  reaches the agent unbidden had been suggesting "re-`remember` or `supersede`", which `SKILL.md`
  forbids and the write-time dedup guard refuses.
- `.gitignore` now covers the root-level twins of yigraf's own runtime caches (`/.local/`, `/cache/`),
  which appear when a command resolves its workspace root one level off.

### Upgrading
- Nothing to do. No wire change, no node-id change — a rebuild produces an identical graph. A
  workspace already showing phantom `diverged` entries from its own re-links will show 0 after its
  next `status`/`sync`.

## [1.3.0] — 2026-08-06

1.2.0 made a shared log *possible*; this release makes the three seams it exposed actually hold. Two
of them were silent — the failure mode was a workspace that believed it had synced, or had cleared
drift, and had not. Binding is no longer three hand-edited settings that nothing checked against each
other. Local, unlinked workspaces are unaffected by all of it: node ids, the fold's verdict, and every
graph a solo repo builds are identical to 1.2.0.

Minor, not major: **2.0 stays reserved for the hosted line.**

### Added — `yigraf online` (workspace binding)
- **`yigraf online <link-url>`** — redeem a single-use link code, generated in the web console, for a
  per-machine token; then bind. It replaces hand-writing `online.project`, `online.remote` and a
  `YIGRAF_TOKEN` export, which was three chances to bind to the wrong project with no check that any
  of them agreed. Humans do all identity work in the browser: there is no OIDC client here, no
  callback port, no refresh, and a self-hoster runs the identical flow against their own server.
- **The code is a redemption code, not the credential.** If the pasted string were itself the bearer
  token, every assertion authored through it would carry the same `actor` and the audit trail would
  say nothing. The machine token it returns goes to `~/.config/yigraf/credentials.json` at mode 0600,
  keyed by host — never `config.yaml`, which is committed. `$YIGRAF_TOKEN` still takes precedence,
  which is what keeps CI working with no interactive link step (a link code is single-use and lasts
  ~15 minutes, so it is the wrong shape for a pipeline; reveal a token in the console instead).
- **Three checks, on a side-effect-free preflight** so a failure never burns the user's single-use
  code. *Repo identity* compares root-commit SHAs — a remote URL changes on rename, re-host or org
  move and the root commit survives all three — because the shared graph is full of
  `implements`/`concerns` edges anchored to code symbols, and binding to a project about a different
  codebase leaves every one of them dangling: the graph still folds, still renders, and is quietly
  meaningless. *Wire version* refuses a bind that could not round-trip, rather than risking it (no
  `--force` there, deliberately: a repo mismatch is a judgement call, an unsupported wire is not).
  *Replica state* moves a mirror already carrying another project's cursor aside under `--force` —
  renamed, never deleted.
- **`yigraf online` with no argument, and `yigraf whoami`** — am I connected, and as whom. One call to
  the server, so the answer never requires reading a graph, and it is the fastest way to tell "my
  token is wrong" from "my project name is wrong", which otherwise look identical.
- Every way the server can refuse — unknown, expired, spent, revoked code; a human invitation pasted
  in place of a machine link code; a non-member — is translated into a specific correction at exit 0
  (design law #1), never a status code.
- **`sync.WIRE_VERSION`** (= 1) — the version of the four wire shapes, advertised by the server and
  compared at bind time. A new *optional* field old clients ignore is not a bump; a renamed, removed
  or re-meant one is.
- Config: `online.repo_fingerprint` — written by `yigraf online`, safe to commit (it is a public git
  SHA), and re-derived by `yigraf sync` before every push. That catches the one case bind-time cannot:
  a `config.yaml` copied into a different repository.

### Fixed — edits stopped propagating once a locator had been pushed
- **Intents and tasks now carry a revisioned assertion id** (`int:<slug>@<hash>`,
  `task:<plan>/<n>@<hash>`) with the locator in the body. mem:063 defines an id as the content-hash of
  its body — two writers who say the same thing collapse to one event — and these two families broke
  it, keying on a slug or a positional locator while their *mutable* state (a task's `[ ]`/`[x]` and
  its `implements` anchors, an intent's `status`) lived in the body. Consequence: `yigraf sync`'s push
  set is `a.id not in known_ids`, so once a locator had been pushed, **every later edit was skipped as
  already-known** — `link` re-anchors, completions and `--status satisfied` silently never propagated,
  and where a revision did reach a replica, `merge_assertion`, `causal_order` and the fold each picked
  a different winner. The fold materializes the node under `body.locator`, so `task:plan/1` is still
  the node every cross-family edge targets and nothing downstream changes.
- **Causal parents are rewritten from locators to the revision ids they name.** A parent must name an
  *assertion*; without the rewrite the online log's prefix-closed ingest check would reject every
  dependent assertion, and `causal_order` would silently drop the ordering constraint that makes edges
  resolve in one pass.
- **A replica may no longer revert what the working tree says.** All four authored families are
  git-committed files (design law #6), so a replica assertion naming a node this workspace already
  materialized is declined — `fold_assertions` gains `defer_families`, and the *caller* states the
  policy because the fold is family-agnostic. Without it, `_fold_replica` running after the local fold
  let a teammate's older snapshot undo local completions; and because `memory.memory_id` hashes what a
  memory *claims* and deliberately not its drift anchors, the replica's pushed copy overwrote an
  anchor `reaffirm` had just re-stamped — so `yigraf drift` re-reported drift the principal had just
  cleared, and no amount of reaffirming could clear it. The test is per-**node**, not per-family: a
  teammate's belief you do not hold folds in exactly as before.
- **`yigraf install` no longer promises a download that later happens at the worst moment.** fastembed
  caches into `$TMPDIR`, and macOS reaps `/var/folders/…/T` by access time: the ~130 MB ONNX blob is
  evicted while the kilobyte metadata files survive, leaving a *dangling snapshot symlink*, so every
  later load silently re-fetched it through `hf_xet` with no wall-clock bound — a `remember` hung 10+
  minutes at 0% CPU. Two guards, because either alone is insufficient. `embeddings.model_cache_dir`
  pins the artifacts to `~/.cache/yigraf/models`, somewhere the OS does not reap, so "downloaded once"
  means once. And every *implicit* path — `get_embedder`, therefore every `context`, `remember` and
  hook — now opens the model `local_files_only`, so a cache miss costs a lexical fallback rather than
  an unbounded download on the agent's critical path (design law #5). Fetching becomes an explicit
  verb, `fetch_model`, run by `yigraf install` where the caller is already waiting on setup and the
  wait can be reported.
- **The drift report's "also affected" ripple re-surfaced what the direct path deliberately withheld.**
  Every ripple line ends in "re-verify it still holds", so a node with no honest re-verification must
  not appear there — and three did. `is_surfaced` withholds a done task's `implements` drift precisely
  so the agent is never asked to rubber-stamp a closed task (`int:drift-done-suppression`), and
  reverse reachability handed it straight back one call later, re-framed as a reconcile prompt and
  double-counting what `stale` already reports. New `drift.is_reverifiable` is the node-shaped
  counterpart, stated per-node so it also covers a done task reached by a *derived* relation
  (`depends_on` over `implements ∘ calls`), which the edge-shaped test never sees; superseded memories
  and archived intents are the same shape. Measured on yigraf's own graph when this landed: 10 of 11
  ripple lines were unactionable — the section was ~9% signal.

### Added — divergence, the case design law #6 assumed git would clean up
- **`⚠ n diverged` in `status`, and a named list at the end of `sync`.** "The local file wins" is a
  complete answer only while the losing copy survives somewhere. In a repo that *commits* its
  `yigraf/` artifacts it does — two machines editing one plan is an ordinary git merge on the
  markdown. In a repo that gitignores them (yigraf's own does, and any repo may) there is no merge
  point, so declining the replica's revision discards the only other copy permanently, with each
  machine convinced it is current. The declined set is therefore inspected rather than dropped: an
  assertion whose id this workspace also authored is a harmless echo, one whose id is unknown is a
  locator two workspaces genuinely disagree about. The fold's verdict is unchanged either way — what
  changes is that the discarded locator is named instead of vanishing, and the guidance forks on
  whether git actually holds the other side. Silent when there is none (design law #4).

### Changed
- Config gains `embeddings.cache_dir` (empty ⇒ `~/.cache/yigraf/models`; `$FASTEMBED_CACHE_PATH` is
  honoured as an explicit choice) and `online.repo_fingerprint`. Both default to the prior behaviour.
- `embeddings.status()` reports `cache_dir`; new `embeddings.model_cached()` is the honest form of "is
  semantic recall on" — `backend_available` only says the *library* imports, and the gap between the
  two is exactly the silent-lexical state this release closes.

### Upgrading
- **Local-only workspaces: nothing to do.** Node ids are unchanged (the locator), so a rebuild
  produces an identical graph.
- **A workspace that already pushed under 1.2.0** will re-push every intent and task under its new
  `@<rev>` id, so a shared log ends up holding both the old fixed-id copies and the new revisioned
  ones. Merging is a commutative set-union and nothing is lost or overwritten, but the older copies
  remain as inert history. No public server exists yet, so this is expected to affect no one; it is
  recorded because a shared log's contents should never be a surprise.

## [1.2.0] — 2026-08-04

The first release in which yigraf is **usable by more than one person at a time** — and still, by
default, entirely local. Nothing here opens a socket unless you configure it to: `online.project` and
`online.remote` ship empty, `yigraf sync` says so and exits 0, and a workspace that never links behaves
exactly as 1.1.1 did. The **2.0** number stays reserved for the hosted line; this is the client half,
and it is additive.

### Added — resolution across a team (`int:team-reconciliation`)
- **`resolution.py` — verdicts are first-class appends.** `reconcile` / `supersede` / `dispute` are now
  authorable by a principal who owns *neither* belief. The verdict names both operands by id and
  projects the resolving edge between them, so it needs write access to no one's files. This is what a
  conflict only its own authors may close costs you: it deadlocks the moment one of them leaves.
- **`fold._apply_projection`** — the one place an assertion may emit an edge between two *other* nodes,
  with shadow-protection when two verdicts compete for an ordered pair. Verdicts are read back off
  resolution *nodes*, never the projected edge, so a dispute and a later reconcile both count in either
  operand order.
- **`yigraf dispute`** — nominate two beliefs as contradictory: the durable "open a PR" step. A
  nomination is an assertion, so it rides the log and every client sees it. `contradiction` unions
  these with the cosine sweep, which matters because the sweep is index-derived and fails open to
  silence — right for one developer, wrong for a team, where the same merged log must yield the same
  open set everywhere.
- **`extract._fold_replica`** — a teammate's belief folds onto your **local** structure base, so their
  intent anchored to `sym:foo` drifts when *you* edit `foo`. Only assertions cross the wire; structure
  stays locally derived, so the shared log never needs a copy of anyone's code.
- **`responsibility.py`** — whoever pushes second merges. Of two conflicting beliefs the higher `seq`
  was written into a world that already contained the other, so its author owes the reconcile. Derived
  from the log's existing order, never a stored assignment; identity comes from the server-stamped
  actor, never a client's claim.

### Added — the principal's notice channel (`int:obligation-notice`)
- **A `Stop` hook that names newly-unresolved obligations to the human, once, with the command that
  clears each one.** The statusline already counted conflicts, stale completions, and drift, and that
  count reliably produced no action: a warning present on every refresh reads as furniture within a
  day, and it carries neither a locator nor a verb. `obligations.py` re-shapes what `stale_completions`,
  `detect_conflicts`, and `compute_drift` already return — no new detection, no new thresholds — and
  diffs them against a session-keyed latch in gitignored `.local/`.
- It returns **only** the universal `systemMessage` field. Never `decision: "block"` (design law #5 is
  unconditional, and the sharpest obligation here — a pending supersede of a human-attested node — is
  one the agent structurally *cannot* clear, so a gate would deadlock); never `additionalContext`
  (mem:012 keeps human-facing graph health off the agent's budget). Edge-triggered, so `/clear`
  correctly re-announces what is still open and resolution stays silent.
- Config: `status.obligation_notice` (`true`) and `status.obligation_notice_max` (`5`).

### Added — the online client
- **`yigraf sync`** — pull the team's delta, push what the log hasn't seen. The pulled delta's Merkle
  links are re-derived client-side before anything is folded in, so a server that dropped, reordered,
  or forged an event is caught here. Push is idempotent by `event_key`, and needs no queue: the push
  set is re-derived every run as the git-committed file log minus the replica's known ids, so an
  assertion that never landed simply goes out next time. (A queue in `.local/` wouldn't survive a
  clone, and would be a second source of truth to reconcile.)
- Config: an `online:` block (`project`, `remote`, `replica`) — all empty by default. The bearer token
  comes from `YIGRAF_TOKEN` and never from `config.yaml`, which is committed, and a token in git is a
  leaked token.
- `maturity_survival_floor` — an optional git-durability gate on promotion to `settled`.

### Changed
- **`reconcile` now always authors a resolution append**, rather than writing `equivalent_to`
  frontmatter onto the left belief when it happened to be local. That silently broke the `memid-v1`
  invariant: `memory.memory_id` does not cover `equivalent_to`, so the edit changed an assertion's
  *body* while leaving its *id* fixed — two different bodies sharing one id, which `yigraf sync`
  (identifying by id) could never see, so the reconciliation stayed local forever. Legacy frontmatter
  is still **read** for compatibility, and deliberately does not block re-authoring, so a pre-sync
  workspace can promote its old local reconciliations to real appends.
- **`maturity_survival_floor` abstains where survival cannot be measured.** `survival` scores 0 both
  for "landed in the tip commit" and for "git has never seen this file". Read as a quantity that
  conflation is conservative and correct; read as a *gate* the same 0 inverts, so in any workspace
  whose artifacts are untracked an armed floor meant nothing could ever settle, silently and forever.
  A gate that cannot be evaluated must not be the thing that denies. `build` now warns when a floor is
  armed but unmeasurable.

### Fixed
- **A failed push was an unhandled traceback.** `HttpRemote._request` let raw urllib errors escape and
  the sync loop caught only `IngestRejected`, so being offline crashed rather than reported. New
  `RemoteUnavailable` is kept distinct from the other two because all three want opposite handling: a
  chain break is an integrity stop (exit 1, replica untouched), a rejection is permanent (reported
  per-assertion, the run continues), and this one is weather — say so and let the next run carry it.
- **A refused credential reached the operator as a 114-line Typer traceback.** `HttpRemote` re-raises a
  non-429 4xx as itself on purpose — a bad token fails identically on every retry, so it must not read
  as "try again later" — but that is a *transport* contract, and `cli.sync` never caught it. A 401,
  403, or 404 is now `_guidance` at exit 0, the same contract the missing-token and unset-config gaps
  already had: all three are one misconfiguration the caller can fix and re-run. The 404 message
  deliberately does not guess between "no such project" and "you are not a member", because the server
  answers both identically so that membership is not an existence oracle.

### Documentation
- **The guide gains a "Working with a team" section** — linking a workspace, what crosses the wire and
  what doesn't, resolving a conflict you didn't author, and whose turn it is.
- **`SKILL.md` §4 taught drift only.** `reconcile` and `attest` are live verbs the skill never named,
  so an agent told to resolve a conflict had to guess. It now covers all three re-verify signals and,
  for a pending conflict, says plainly that the agent cannot clear it.
- Retired the pre-mem:033 "maturity is git-derived / settled after K commits" claim from the four
  places still carrying it (`counters.py`'s module header, `extract`, `cli`, `graph`). Promotion has
  been a read-time verdict over sidecar upholds since mem:047; the header described the model mem:033
  replaced, which made it actively misleading next to the code it headed.

## [1.1.1] — 2026-08-01

Follow-ups to the 1.1.0 typed edge algebra from a review of that release, plus a
documentation pass. No new capability — every change here makes yigraf match what
it already claimed.

### Changed
- **`serves` now rejects a task target.** Its signature was the bare `plan`
  *family*, which also admits `plan/task` — so `remember --serves task:x/1`
  landed silently while the command's own guidance said only `int:<slug>` or
  `plan:<slug>` were valid. The signature is now `plan/plan`, matching what the
  guidance always claimed. A task is a unit of work, not a goal; pin a decision
  to a task's code with `--concerns`.
- **The `yigraf drift` blast-radius section reads `also affected (verify these
  too)`**, not `transitively affected`. The section was never all-transitive: a
  depth-1 hit is a *direct* edge onto the drifted locus that `compute_drift`
  didn't report (it reports an edge only when that edge's own anchor stopped
  matching). Each line now states its composed relation as an arrow plus a hop
  count — `mem:abc —concerns→ sym:a.py#f (extracted, direct)` versus
  `task:m/1 —depends_on→ sym:a.py#f (inferred, 2 hops)` — so an agent can tell
  an asserted anchor from a derived entailment without decoding the heading.

### Fixed
- Removed a dead `contextlib` import left in `onlinelog.py` when
  `PostgresAssertionStore` moved out, and corrected two docstrings that still
  described it as shipping here.
- `relations.Reach` documented `path[0]` as reaching `target`, which is false for
  a reverse walk — there `target` *is* `path[0]`. The docstring now states both
  directions.

### Added
- `reach()`'s dominance pruning is now pinned against a brute-force oracle over
  both walk directions, including dense cycle-rich graphs. The prune is only
  sound because bottleneck confidence is non-increasing while depth is
  non-decreasing, and its failure mode is silent — a wrong prune drops a
  blast-radius hit rather than raising.

### Documentation
- **Code comments no longer describe `graph.json` as the live committed
  projection.** mem:059 retired it for the gitignored SQLite materialized view,
  but the comments never followed. `counters.py` was the worst: its module
  docstring opened on *"v0 keeps `graph.json` fully recomputable"*, explained
  that branches reconcile through a union-merge driver no longer registered, and
  pointed the shared-counter model at *"v1 / Enterprise"* work that is now 2.0
  (`int:yigraf-online-v1`). `graph.py` asserted outright that `graph.json` is
  committed. Corrected across `counters.py`, `graph.py`, `cli.py`, `memory.py`,
  `extract.py`, `update.py`, and `status.py`. Anything describing the retirement
  *accurately* was left alone — `graphdb.py`, the ignore entry for a stale pre-1.0
  file, and the hidden `graph-merge` command; `merge_node_link` keeps its wording
  but is now labelled LEGACY, since that command is its only caller.
- **The guide documents the drift blast radius**, which shipped in 1.1.0
  undocumented: how to read `node —relation→ target (confidence, hops)`, why an
  `extracted, direct` hit appears there rather than in the drift lines above it,
  and that only soft drift ripples.
- The 1.0.0 entry below listed two extras, `[embeddings]` and `[mcp]`, **neither
  of which has ever existed** — both are core dependencies. Corrected in place.
- `docs/guide.md` no longer hardcodes a test count, and the landing page reads
  `v1.x` rather than a pinned version, so neither can drift again.

## [1.1.0] — 2026-08-01

Still the **local** engine (`int:yigraf-local-v1`). The hosted, multi-user line
remains **2.0** — see the 1.0 **Roadmap** below; nothing here moves toward it.

### Added — the typed edge algebra (`relations.py`)
- yigraf's arrows always carried an *implicit* signature (`implements` goes
  task→sym, `serves` goes memory→intent, `calls` goes function→function), but
  nothing named the type. That grammar is now explicit, and it buys two things a
  hand-rolled traversal can't:
  - **Composition** — a partial `compose(r1, r2)` says which relation you get by
    following one edge then another. `implements ∘ calls ⇒ depends_on` means the
    graph *entails* facts nobody wrote down, and a path that stops composing is
    pruned rather than walked.
  - **A confidence semiring** over `EXTRACTED > INFERRED > AMBIGUOUS` — weakest
    link along a path, best across alternative paths. A derived multi-hop edge is
    capped at `INFERRED`, so a query can always tell "someone linked this" from
    "the graph inferred this."
  Everything in the module is read-time and pure: a derived relation is never
  persisted, because persisting it would make an entailment look like a claim.
- **`yigraf drift` now reports blast radius.** Past the directly-anchored drift,
  it names the governed nodes that only *transitively* depend on a drifted symbol
  — a task whose implementing code merely *calls* it, a memory concerning its
  container — under a new `transitively affected (verify these too)` heading.
  Additive and gated: with no cross-family edges to ripple, it prints nothing
  (silence is a feature).
- **The edge grammar is enforced at the write boundary.** An ill-typed plan edge
  now raises before it reaches disk instead of landing and being flagged later by
  the read-time audit; `remember --serves` rejects a wrong-typed target (a
  `sym:`, a memory id) with guidance and exit 0, where it previously only
  warned about a non-existent one.

### Fixed
- `intent`, `supersede`, `plan`, and `remember` no longer fail on a workspace
  whose subdirectory hasn't been scaffolded yet — the destination directory is
  created on write.

### Removed
- **`PostgresAssertionStore` and the `[postgres]` extra.** The MIT engine now
  ships only the `AssertionStore` *port* plus the stdlib `SqliteAssertionStore`
  reference adapter; a hosted deployment supplies its own concrete adapter and
  pulls its own driver. Keeping the substrate out of the public package is
  deliberate — the engine has no server-only dependencies, and storage is the
  deployment's concern. The single-sourced contract still holds because the port
  stays here, and adapters are checked against it.

  This is the one behavior change that can break an existing install, and it
  breaks *quietly*: `pip install yigraf[postgres]` still succeeds under 1.1.0 —
  pip and uv treat an unknown extra as a warning, not an error — but it now
  installs no driver, so the failure surfaces later as an ImportError rather
  than at install time. If you were pulling psycopg that way, depend on it
  directly. It is versioned as a minor rather than a major because the adapter
  was scaffolding for the unreleased 2.0 hosted line — never wired into any
  local command, and reachable only by a deployment that would now supply its
  own.

## [1.0.0] — 2026-07-16

First stable release.

**yigraf 1.0 is the _local_ engine**: the complete AGM+JTMS belief-revision graph
over code, intent, plan, and memory, running self-contained inside a single
repo/folder with **no network**. The source of truth is an append-only,
content-addressed set of assertion files committed to git (git-union-merges for
free); the queryable graph is a gitignored, recomputable SQLite materialized view.
Multi-user / hosted operation is the 2.0 line — see **Roadmap** below.

This release promotes the project's design contracts to `satisfied`
(26 intents), verified by a fully green offline suite (546 tests) and a
fresh-repo end-to-end run of the working loop.

### The graph — four node families + cross-family edges
- **structure** — files, modules, symbols, and calls from tree-sitter, with a
  reformatting-stable, AST-normalized content hash (`structure-index`).
- **intent** — the SHALL/MUST contracts and goals code serves, evolvable in the
  graph: retire/reactivate via a status change, or reverse via a traversable
  int→int `supersedes` edge — no hand-editing (`intent-evolution`).
- **plan** — tasks in a DAG with state; a task declares the symbols that
  implement it, anchored to their current content (`enforceable-link`).
- **memory** — the durable *why* behind a change, re-surfaced when the code it
  concerns changes (`memory-family`).

### Retrieval — legible and token-cheap
- `context` is the one read command: governing intent, plan, implementing
  signatures, prior decisions, and drift return through a single token-budgeted
  slice rendered as **locators + signatures, not source** (`token-cheap-context`).
- The packet reserves per-family budget shares so no family is starved by a flood
  in another; every code node carries the justification by which it entered the
  slice, and a surfaced signal's explanation is never dropped by budget reduction
  (`packet-legibility`).
- Optional local semantic recall (`bge-small`) improves seeding; absent, retrieval
  degrades gracefully to the lexical seeder — never a hard dependency
  (`semantic-recall`).

### Enforceable links & drift
- A linked symbol whose body changed since anchoring is flagged as drift; a pure
  rename is not (`drift-detection`).
- Whole-file and line-range anchoring — `file:<path>` and `file:<path>:L<a>-L<b>`,
  hashing raw bytes — so infra/glue files (Dockerfile, buildspec, shell) are
  governable (`file-anchoring`).
- Drift is treated as **evidence-invalidation**: a drifted anchor marks its
  dependent belief STALE (re-verify), never automatically false — so a body change
  never silently retracts a decision or poisons maturity (`drift-as-stale`).
- Drift on a task its plan marks **done** is withheld from the surfaced signal
  (relinking a closed task is rubber-stamping) while still computed internally so
  the satisfied-but-unverified-intent check keeps firing (`drift-done-suppression`).
- Proof obligations: the invariants an edit must preserve — derived from the
  governing MUST/SHALL contracts and active acceptance criteria — are injected at
  the moment of action (`proof-obligations`).

### Memory — one coherent certainty model
Three orthogonal axes on a memory node, all overlaid at read time (never stored):
- **maturity** — earned behaviorally: promoted `working` → `settled` after it
  survives K review-encounters un-superseded; demoted only on a recorded
  contradiction, never by the passage of commits (`memory-maturity`).
- **attestation** — agent vs human; human attestation sets a sticky trust floor,
  and an agent supersede of a human-attested node is held pending and surfaced as
  a conflict, never applied silently (`memory-attestation`).
- **grounding** — `inferred | docs | empirical`; low-grounding beliefs surface as
  re-verify TODOs and can be upgraded when evidence arrives; `grounded_by` names
  the evidence that earns the `empirical` tier (`memory-grounding`).
- **Knowledge mining** lands mined/reviewed reasoning as `proposed` candidates
  with near-zero retrieval weight that expire unless a real encounter confirms
  them (`knowledge-mining`); **review-compound** turns a confirmed review finding
  into a durable node anchored to the reviewed locus (`review-compound`).
- **Conditioned rejections**: a rejected alternative can carry `valid_when` /
  `invalidated_when` premises and is surfaced only while they hold — so a
  rejection whose reason lapsed stops steering the agent away (`conditioned-rejections`).
- **Intent elicitation**: the agent queries the principal only on an unavoidable
  preference-fork, capturing the answer as a human-attested intent — never on
  ambiguity it can resolve by competence (`intent-elicitation`).

### Belief revision & concurrent writes (local)
- Multi-writer coordination is modeled as an append-only, content-addressed,
  causally-stamped log of assertions folded into a materialized (never lockable,
  never committed) graph — resolving writes by log-append, not locks/leases
  (`concurrent-write-model`). Conflicting live beliefs about the same anchor
  surface as an explicit knowledge conflict (belief revision), never
  last-writer-wins. Integrity via a Merkle hash chain; a provenance-typed partial
  order informs — never decides — which side of a conflict dominates.

### Hosts & delivery
- yigraf speaks into the agent's context at the moment of action. Push is
  delivered per host at the highest fidelity that host's own extension points
  allow: event-scoped hooks (Claude Code, Codex), an always-on ambient rule
  (Antigravity and the VS Code family), and pull-only via MCP everywhere else
  (`multi-host`, `host-push-adapters`, `hook-surfacing`).
- The MCP server exposes the full loop — read tools (`context`, `status`) and
  write tools (`link`, `remember`, `note_constraint`, `supersede`) —
  host-agnostically (`mcp-server`).
- A host-agnostic `status` line summarizes scale, drift, freshness, and semantic
  index for a thin per-host ambient surface, without spending the agent's context
  budget (`status-surface`).

### Packaging
- Requires **Python 3.11+**. 16 tree-sitter grammars bundled (Python, Go, JS/TS,
  Rust, Java, C/C++, Ruby, C#, Kotlin, Scala, PHP, Swift, Bash, SQL).
- Semantic recall (fastembed/ONNX) and the MCP server are **core** dependencies —
  full power out of the box, no extra to install. Optional extras: `[embeddings-torch]`
  (the opt-in torch backend for semantic recall) and `[postgres]` (the hosted-line
  Postgres adapter; removed in 1.1.0).
- MIT licensed. Published to PyPI as `yigraf`.

### Roadmap — not in 1.0
- **yigraf 2.0 — online / hosted** (`int:yigraf-online-v1`, *proposed*): the same
  belief-revision model behind a hosted service so multiple users and their agents
  work concurrently against one project graph — a durable, ordered, replayable
  ingest log with synchronous structural/causal validation and asynchronous
  semantic-coherence checking. The log/Merkle/provenance/ingest-validation engine
  is scaffolded (`onlinelog.py`); the hosted store, service process, and
  end-to-end client sync are 2.0 work.
- Deferred residuals now homed under 2.0: the per-conflict belief-revision
  resolution UI (consuming the derived `accepted`/`dominant` fields), and a native
  TaskList host-adapter (blocked until a host exposes a writable task API).

[1.3.1]: https://github.com/mansilla/yigraf/releases/tag/v1.3.1
[1.3.0]: https://github.com/mansilla/yigraf/releases/tag/v1.3.0
[1.2.0]: https://github.com/mansilla/yigraf/releases/tag/v1.2.0
[1.1.1]: https://github.com/mansilla/yigraf/releases/tag/v1.1.1
[1.1.0]: https://github.com/mansilla/yigraf/releases/tag/v1.1.0
[1.0.0]: https://github.com/mansilla/yigraf/releases/tag/v1.0.0
