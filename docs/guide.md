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
uv run pytest          # 546 tests, offline
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
*incomparable* — the conflict stays open for you, never auto-resolved by a tiebreak. This is the local
form of belief revision; the richer per-conflict resolution UI is 2.0 (online) work.

---

## Files yigraf creates

`yigraf init` lays down a `yigraf/` workspace at your repo root:

```
yigraf/
├── config.yaml            # committed — enabled languages, ignore globs, retrieval/maturity tunables
├── intents/<slug>.md      # committed — SHALL/MUST specs (requirement / goal / capability)
├── plans/{active,completed}/  # committed — plans + tasks (the filesystem is the state)
├── memory/<id>-<slug>.md   # committed — decisions / constraints + the "why"
├── index/                  # gitignored — embedding index (rebuildable)
├── cache/                  # gitignored — extraction cache
└── .local/                 # gitignored — the SQLite graph view (graph.db) + volatile telemetry
```

The **committed** Markdown (`intents/`, `plans/`, `memory/`, `config.yaml`) is the shareable source of
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
