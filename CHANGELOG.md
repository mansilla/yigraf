# Changelog

All notable changes to yigraf are recorded here. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/); yigraf uses
[semantic versioning](https://semver.org/).

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
- Optional extras: `[embeddings]` (local semantic recall), `[mcp]` (MCP server).
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

[1.0.0]: https://github.com/mansilla/yigraf/releases/tag/v1.0.0
