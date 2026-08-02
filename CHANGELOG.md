# Changelog

All notable changes to yigraf are recorded here. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/); yigraf uses
[semantic versioning](https://semver.org/).

## [Unreleased]

Follow-ups to the 1.1.0 typed edge algebra, from a review of that release.

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

[1.1.0]: https://github.com/mansilla/yigraf/releases/tag/v1.1.0
[1.0.0]: https://github.com/mansilla/yigraf/releases/tag/v1.0.0
