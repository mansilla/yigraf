# yigraf guide

The [README](../README.md) is the pitch and the plain-language loop. This is the reference: how to
install it, the commands your agent runs under the hood, and how drift, conflicts, and memory maturity
actually work.

---

## Install

yigraf is on **PyPI** and needs only **Python ≥ 3.11**. Everything else is bundled — the tree-sitter
grammars (16 languages), the MCP server, and semantic recall (fastembed / ONNX, no torch) — so one
install gives you full power. For a CLI you use across repos, an isolated install is nicest:

```bash
pipx install yigraf         # isolated CLI (recommended)
uv tool install yigraf      # isolated CLI, via uv
pip install yigraf          # into the current environment
```

**macOS:** `brew install python@3.12 pipx && pipx install yigraf`
**Debian/Ubuntu:** `sudo apt-get install -y python3 python3-pip pipx git && pipx install yigraf`
**Windows:** `winget install Python.Python.3.12`, then `winget install Git.Git`, then `pip install yigraf`

Git isn't strictly required, but drift anchoring and maturity read git history — yigraf degrades
gracefully without it.

**From source (development):**

```bash
git clone https://github.com/mansilla/yigraf.git
cd yigraf && uv sync
uv run yigraf --help
uv run pytest          # the full suite, offline (no network, no model download)
```

### Wire it into your host

```bash
yigraf install              # auto-detects your host(s), wires each at its best tier, MCP as fallback
yigraf install --plan       # preview what it would wire, without applying (add --json for machine form)
```

Auto-detection covers Claude Code, Codex, Cursor, Windsurf, Kilo, and Antigravity; anything else uses
the universal MCP server. Per-host wiring is in [hosts.md](hosts.md); MCP config per host is in
[mcp.md](mcp.md); the Claude Code statusline is in [statusline.md](statusline.md).

### Semantic recall (optional tuning)

Semantic recall is **on by default** via the bundled fastembed backend — nothing to install. On the
first `yigraf build`, the small `bge-small` model downloads once from the HuggingFace Hub. Two knobs
in `yigraf/config.yaml` under `embeddings.backend`:

- **`none`** — turn it off; retrieval falls back to lexical (keyword) seeding.
- **`sentence-transformers`** — the torch backend (`pip install "yigraf[embeddings-torch]"`). Only
  worth it for Apple-Silicon MPS throughput; the two backends agree to ≈0.9999 cosine.

---

## The workflow

Five verbs. Your agent runs them; you speak the [plain-language versions](../README.md#using-it--just-talk-to-your-agent).

### Build

`yigraf build` parses your code into file / module / symbol nodes, each with an **AST-normalized**
content hash — so reformatting, comment edits, and moved whitespace don't count as change; only real
structural edits do. Re-run it any time; it's incremental and keyed to a fingerprint of its inputs.

### Author

Write **intents** and **plans** as Markdown, and capture **memory** as you decide things:

```bash
yigraf intent session-expiry -s "The system SHALL expire a session after 30m idle."
yigraf plan auth -t "Auth hardening" --task "add idle-timeout to session refresh"
yigraf remember "chose a monotonic clock" --why "wall-clock skews under NTP" \
                --concerns sym:src/auth/session.py#refresh --rejected "time.time() deltas"
```

The Markdown files under `yigraf/` are the source of truth (see [Files](#files-yigraf-creates)); the
graph is derived from them.

### Link

`yigraf link` records which code implements a task (or which intent a task tracks) and **anchors** the
link to that symbol's current content hash:

```bash
yigraf link task:auth/1 sym:src/auth/session.py#refresh    # implements → a symbol
yigraf link task:auth/1 int:session-expiry                 # tracks → an intent
```

The anchor is what makes the link *enforceable*: if the symbol's body later changes, the link
**drifts** and yigraf asks for a re-verification. You can also anchor to whole files or line ranges for
infra/glue that has no parsed symbol: `file:Dockerfile` or `file:deploy.sh:L10-L40`.

### Retrieve

`yigraf context "<topic>"` is the one read command. It returns a scoped, **token-budgeted** slice —
locators and signatures, not file dumps — with the governing intents, the implementing symbols, prior
decisions, open tasks, and any drift:

```bash
yigraf context "session expiry"
```

It's ranked and capped (defaults: 4000-token budget for the CLI, 800 for hook injection), with a
reserved share per node family so a flood of one kind never starves the others. Every code node it
returns carries the reason it was included.

### Enforce

`yigraf drift` reports where code has moved away from what governs it. `yigraf status` prints the
one-line health summary (scale, drift, freshness, conflicts, semantic index). With a host wired, both
happen automatically — see [Drift](#drift) next.

---

## Drift

Drift is yigraf's core enforcement signal: **an anchored belief whose code changed underneath it.**
Three kinds:

- **soft** — the symbol still exists but its body changed since anchoring. *Re-verify it still holds.*
- **hard** — the symbol is gone (deleted). *The link needs re-pointing or the belief retiring.*
- **rename** — the symbol moved to a new name but is otherwise intact. yigraf recognizes it and does
  **not** cry wolf; re-link to the new locator to re-anchor.

Crucially, **drift never means "false."** A body change marks the dependent belief **STALE
(re-verify)** — it never silently retracts a decision or a task's completion, and never poisons the
maturity signal. You clear drift honestly, with the verb that matches what actually happened:

| What happened | Verb |
|---|---|
| The task's implementation is still correct against the new code | `yigraf link` (re-anchor) |
| A decision still holds; the code it concerns just moved | `yigraf reaffirm` (re-stamp in place) |
| The decision itself changed | `yigraf supersede` (new node, edge back to the old) |

**Reaffirm what you actually re-read** — not a reflexive sweep. Rubber-stamping drift you didn't
verify is the failure mode yigraf is built to prevent.

**Done tasks are special:** a closed task's implements-link has no honest re-verification (the work
shipped), so its drift is *withheld* from the surfaced signal — you won't be nagged to relink shipped
work. yigraf still computes it internally, so a *satisfied intent* whose only implementing link drifted
is still flagged as unverified.

### Blast radius — what else the drift reaches

The three kinds above are all reported because **that edge's own anchor** stopped matching. But a
change reaches further than the edges that happen to have drifted. Under an `also affected (verify
these too)` heading, `yigraf drift` walks *backwards* from each drifted symbol and names the governed
nodes it can reach — a task whose implementing code merely **calls** it, a memory that concerns its
**container**:

```
soft drift: task:auth/1 → sym:src/auth/session.py#refresh (body changed since anchored)

also affected (verify these too):
  ⚠ mem:0a1 —concerns→ sym:src/auth/session.py#refresh (extracted, direct) — re-verify it still holds
  ⚠ task:api/3 —depends_on→ sym:src/auth/session.py#refresh (inferred, 2 hops) — re-verify it still holds
```

Read each line as *node —relation→ what it reaches*, then how that relation was established:

- **`extracted, direct`** — a real one-hop edge someone asserted, onto the very symbol that drifted.
  It isn't in the list above it because *its* anchor still matches (or it's anchored under a different
  algorithm, or it's a forward reference to something not built yet). Nothing is double-reported: a
  node already named by a drift line is excluded here.
- **`inferred, N hops`** — nobody wrote this down; yigraf **composed** it. `implements ∘ calls` entails
  `depends_on`, so a task reaches code it never linked directly. Derived edges cap at `inferred` and
  are never stored — recomputing them at read time is what keeps an entailment from looking like a
  claim someone made.

So the heading says "also," not "transitively" — the section mixes both, and each line tells you which
it is. Only *soft* drift ripples: hard drift means the symbol is gone from the graph entirely, so
there are no incoming edges left to walk back through and the direct line is the whole signal.

Like the rest of yigraf this is silent when it has nothing to say: a repo with few cross-family edges
has nothing to ripple, and the heading never appears.

---

## Memory

*The certainty model.* A memory node isn't just true or false. It carries three **orthogonal** axes,
all computed at read time (never frozen into the stored file):

### Maturity — *has it survived?*

A memory an agent captures lands at **`working`** (a live belief, no ranking bonus). It earns
**`settled`** only after it survives **`maturity_k` review-encounters un-superseded** (default `k=3`)
— an encounter being a `reaffirm`, or surviving an edit-hook surfacing on non-drifted code. It is
demoted **only on a recorded contradiction** (a `supersede`) — **never by the mere passage of
commits**. Mined or review-sourced candidates land lower still, at **`proposed`**, with near-zero
retrieval weight, and expire unless a real encounter confirms them (that's what makes aggressive
mining safe). `yigraf gc` archives superseded churn and abandoned proposals — it never deletes a
genuine `working`/`settled` decision by silence.

### Attestation — *who endorsed it?*

`agent` (the default) or `human`. Human attestation (`yigraf attest`) sets a **sticky trust floor**:
an agent's attempt to `supersede` a human-attested node is **held pending** and surfaced as a
conflict, never applied silently.

### Grounding — *what backs it?*

`inferred` (a reasoned guess), `docs` (read from documentation), or `empirical` (a live observation).
Low-grounding beliefs surface as **re-verify TODOs** in context; grounding can be upgraded when
evidence arrives, and `grounded_by` names the evidence that earns the `empirical` tier.

---

## Conflicts & belief revision

When two **live** beliefs concern the same anchor with **opposing** content, yigraf raises an explicit
**knowledge conflict** — it never silently keeps one (no last-writer-wins). This is a *surfaced
signal*, computed like drift, never a write-time gate: your writes always land; the disagreement is
made visible for a human to resolve.

To *inform* (never decide) resolution, yigraf ranks the two sides by a **provenance-typed partial
order**:

> human > MUST-contract > empirical > architectural > plan-assumption > structural > LLM-inferred

The higher-provenance side is named the *dominant* one. If both sides are the **same** tier they're
*incomparable* — the conflict stays open for you, never auto-resolved by a tiebreak.

### Resolving one

A resolution is always an **append** — a small artifact under `yigraf/resolutions/`, never an edit of
either belief. That matters for two reasons that turn out to be the same reason: you frequently own
*neither* belief (both arrived over the shared log), and editing a belief in place would change its
body while leaving its content-addressed id fixed, making the resolution invisible to sync.

```sh
yigraf reconcile <a> <b> --why "both true, different altitudes"   # equivalent_to — both stay live
yigraf supersede  <old> "the new belief" --why "the mind changed" # retracts the old one
yigraf dispute    <a> <b> --why "these cannot both hold"          # opens a conflict
```

`dispute` is the one that *adds* a finding rather than closing one, and it's why the family exists.
Conflict detection is otherwise derived from embeddings, which fails open to silence when there's no
local index — fine alone, wrong on a team, where the same log would yield a different open set on
every machine. A dispute is an assertion, so it rides the log and everyone sees it, index or not. It
blocks nothing; it makes the disagreement a named, actor-stamped open question.

---

## Working with a team

yigraf works fully offline. Point it at a shared log and your teammates' assertions join *your* graph.

You don't configure this by hand. In the web console — the browser is where all identity work happens —
open your project's **Machines** tab, generate a link code, and paste the URL it gives you:

```sh
yigraf online https://your-server/link/ygl_…   # redeem it, bind this workspace, first sync
yigraf online                                  # ...and later: am I connected, and as whom?
yigraf sync --dry-run                          # what would move
yigraf sync                                    # pull the team's assertions, push yours
```

That one command redeems the code for a **per-machine** token, writes it to
`~/.config/yigraf/credentials.json` at mode 0600 (never `config.yaml` — that file is committed, and a
token in git is a leaked token), and fills in `online.project`, `online.remote` and
`online.repo_fingerprint` for you.

Before it writes anything it checks that this repo and that project are about the same codebase, by
comparing your **root-commit SHA** against the project's. That check exists because the shared graph is
full of `implements`/`concerns` edges anchored to code symbols: bind to a project about a different
codebase and every one of them dangles — the graph still folds, still renders, and is quietly
meaningless. `yigraf sync` re-checks it before each push, which catches the one case binding can't: a
`config.yaml` copied into another repository.

A link code is single-use and lasts about 15 minutes, so it is the wrong shape for CI. For a pipeline,
reveal a token in the console instead (it is shown once) and put it in your secret store:

```sh
export YIGRAF_TOKEN=…          # wins over the credentials file, for CI and containers
```

**Only assertions cross the wire — your source never does.** Structure is always re-derived locally
from your own checkout, which is why drift stays computable on your machine and the server never needs
a copy of anyone's code.

The payoff is that drift becomes a team signal. A teammate's decision anchored to `sym:app.py#greet`
lives in your graph with no file on your disk — and the moment *you* edit `greet`, it drifts:

```
$ yigraf drift
soft drift: mem:ade398d0 → sym:app.py#greet (body changed since anchored)
```

Sync is git-shaped and conflict-free by construction. A pull cryptographically re-derives the Merkle
links over the delta before folding it in, so a server that dropped, reordered, or forged an event is
caught client-side. A push is never rejected for *disagreeing*: assertions are content-addressed and
belief is re-derived from the whole set, so merging two logs is a commutative set-union. Two people
asserting the same claim collapse to one node; two people asserting opposed claims both land, and the
pair surfaces afterwards as a conflict for a principal. The only writes the server refuses are
structurally malformed ones, and it tells you how to fix them.

### Whose turn is it?

git's rule, and yigraf's: **whoever pushed second merges.** Of two conflicting beliefs, the one with
the higher log position was written into a world that already contained the other — so its author owes
the resolution, and `sync` says so at the moment they pull:

```
$ yigraf sync
Synced my-project: pulled 3, pushed 1 — head seq 41 (9d1edb2fb9ac).
⚠ You now own 1 open conflict — your belief landed later, so the resolution is yours:
  mem:bb20f921 ⟂ mem:f3eb2912 ← sym:app.py#greet
    you wrote mem:bb20f921, which landed on top of mem:f3eb2912 (log seq 2 > 1) — the later writer resolves
    → yigraf reconcile mem:bb20f921 mem:f3eb2912   — or: yigraf supersede <loser> "<the surviving claim>"
```

Conflicts that are someone *else's* turn cost one line, not a block. Nothing is assigned or stored —
the log's order already carries the answer, and it is silent when you owe nothing. Note that position
is *push* order, not authoring order: write something offline on Monday and push it Friday and you are
the later writer, exactly as git would make you rebase.

A belief that arrived over the wire also **matures on the shared log's clock**. Maturity asks how much
history a decision has outlived un-superseded; for your own artifacts that is commits on your branch,
and for a teammate's — which has no file in your history at all — it is appends to the shared log. Both
are consulted and the stronger wins, so a teammate's long-standing decision no longer reads as brand
new, and adopting a shared log never resets durability your own decisions already earned in git.

---

## Files yigraf creates

`yigraf init` lays down a `yigraf/` workspace at your repo root:

```
yigraf/
├── config.yaml            # committed — enabled languages, ignore globs, retrieval/maturity tunables
├── intents/<slug>.md      # committed — SHALL/MUST specs (requirement / goal / capability)
├── plans/{active,completed}/  # committed — plans + tasks (the filesystem is the state)
├── memory/<id>-<slug>.md   # committed — decisions / constraints + the "why"
├── resolutions/<kind>-<id>.md  # committed — verdicts on a conflicted pair (reconcile/supersede/dispute)
├── index/                  # gitignored — embedding index (rebuildable)
├── cache/                  # gitignored — extraction cache (incl. replica.db, the synced log mirror)
└── .local/                 # gitignored — the SQLite graph view (graph.db) + volatile telemetry
```

The **committed** Markdown (`intents/`, `plans/`, `memory/`, `resolutions/`, `config.yaml`) is the shareable source of
truth — it travels with the repo, so the next agent or teammate inherits the *why*, and it
git-union-merges cleanly because it's append-friendly text. The queryable graph is the **gitignored
`.local/graph.db`** — a recomputable SQLite materialized view, never committed (a binary DB can't
union-merge), rebuilt from source whenever inputs change. Derived and volatile state (the embedding
index, extraction cache, usage telemetry) is gitignored and rebuilds on demand. yigraf writes its own
`yigraf/.gitignore`, so you don't add anything to your repo's ignore rules.

---

## Hosts & MCP

- **[hosts.md](hosts.md)** — the full per-host push/pull matrix and what each installer wires.
- **[mcp.md](mcp.md)** — running `yigraf mcp` as a server and the per-host MCP config.
- **[statusline.md](statusline.md)** — the Claude Code `[Yigraf]` bar + context-window gauge.
- **[language-support.md](language-support.md)** — the tested capability matrix across 16 languages.
