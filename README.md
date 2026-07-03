<p align="center">
  <img src="https://raw.githubusercontent.com/mansilla/yigraf/main/assets/logo.png" alt="yigraf" width="120" height="120">
</p>

# yigraf

> **yigraf — "Why I Graph?"** A tool **for AI coding agents, not for humans.** It answers, *for the
> agent*, the **why's** and **what-for's** of its current state — the questions an agent can't recover
> from source alone and loses on every `/clear`. A human is the *principal* whose intent it carries; the
> agent is the operator and the audience.

## What is yigraf?

yigraf is a **harness primitive** for AI coding agents: it projects your repo into one connected graph
over four kinds of knowledge —

- **structure** — the code itself (*what is this?*)
- **intent** — specs/requirements (*what is it for?*)
- **plan** — goals and tasks (*what's left?*)
- **memory** — decisions and their reasoning (*why is it this way?*)

— and keeps them linked, so the right slice of an agent's work is both **legible** (scoped, token-cheap
retrieval instead of re-reading files) and **enforceable** (an intent↔code *drift check* that fires when
code and the thing governing it diverge). It retrofits onto an existing repo — `yigraf init` and go.

The problem it solves: an agent's working memory is wiped on every `/clear`, and source code doesn't
record *why* it's the way it is or *what* it's supposed to do. yigraf persists that context as a
queryable graph and re-surfaces the relevant piece exactly when the agent needs it.

### Capabilities

- **Structure index** — tree-sitter parsing into file/module/symbol nodes with a reformatting-stable
  content hash, across **16 languages** (see [`docs/language-support.md`](docs/language-support.md)).
- **Intent & plan** — author specs and task plans as Markdown; link a task to the symbols that implement
  it, **anchored** to their current content.
- **Drift detection** — when anchored code changes, yigraf surfaces *"re-verify this still holds, then
  re-link or supersede."* A pure rename re-anchors automatically; a body change is honest drift. (This is
  the part that makes yigraf governance, not just an index.)
- **Memory** — capture decisions + the reasoning behind them; recall by **meaning** (semantic recall,
  on by default) or lexically; a decision earns `settled` after surviving K commits un-superseded; `gc`
  archives churn.
- **Token-cheap retrieval** — `yigraf context "<topic>"` returns a scoped, budgeted slice (locators +
  signatures, not file dumps) — measured ≈2.5× cheaper than reading the file.
- **Agent integration (any host)** — an **MCP server** (`yigraf mcp`) exposes the graph as tools
  (`context`/`status`/`link`/`remember`) to *any* MCP host (Codex, Antigravity, Cursor, Claude Code);
  where a host has lifecycle hooks (Claude Code, Codex) those also **push** governing intent + drift on
  edit and re-inject the plan after a reset. The `yigraf` CLI works with any agent. See
  [`docs/hosts.md`](docs/hosts.md).

### Requirements

Just Python and (ideally) git — everything else is bundled (see [Installation](#installation)).

| Requirement | Why |
|---|---|
| **Python ≥ 3.11** | yigraf runs as a Python CLI |
| **A git repo** *(recommended)* | drift anchoring and git-derived maturity read git history — degrades gracefully without it |
| **An agent host** | any MCP host via `yigraf mcp`; Claude Code & Codex also get push hooks; or drive the `yigraf` CLI from any agent |

## Quickstart — just tell your agent

yigraf is a tool *for agents*, so installing it is a job for your agent. In any repo, say:

> **"Please install github.com/mansilla/yigraf in this project."**

A well-behaved agent will install the CLI, run `yigraf install --plan` to **show you the capability
menu**, let you choose, then wire it into your host — without touching your `requirements.txt` (yigraf
is a dev/agent tool, not a runtime dependency). Semantic recall is on by default, so "full power" needs
no extra steps.

Prefer to do it by hand? The same four steps:

```bash
pip install yigraf          # or: pipx install yigraf / uv tool install yigraf
cd your-repo
yigraf init                 # create the yigraf/ workspace
yigraf build                # index the code into the graph
yigraf install              # wire your agent host — auto-detects Claude Code / Codex / Antigravity, else MCP
```

Preview what `install` will wire, without applying anything (add `--json` for the machine-readable form
an agent parses):

```bash
yigraf install --plan
```

Then use it:

```bash
yigraf context "session expiry"          # a scoped, token-cheap slice for a topic
yigraf intent session-expiry -s "The system SHALL expire a session after 30m idle."
yigraf link task:auth/1 sym:src/auth/session.py#refresh   # anchor a task to its code
yigraf remember "chose monotonic clock" --why "wall-clock skews under NTP"
yigraf drift                             # report any intent↔code drift
```

## Installation

yigraf is on **PyPI** and needs only **Python ≥ 3.11**. Everything else is bundled — the tree-sitter
grammars (16 languages), the MCP server, and semantic recall (fastembed / ONNX, **no torch**) — so one
install gives you full power out of the box. For a CLI you use across repos, an isolated install (pipx
or `uv tool`) is nicest.

```bash
pip install yigraf                 # into the current environment
pipx install yigraf                # isolated CLI (recommended)
uv tool install yigraf             # isolated CLI, via uv
```

### macOS

```bash
brew install python@3.12 pipx     # Python 3.11+ and pipx
pipx install yigraf
```

### Linux

```bash
# Debian/Ubuntu — ensure Python 3.11+ and git
sudo apt-get update && sudo apt-get install -y python3 python3-pip pipx git
pipx install yigraf
```

### Windows

```powershell
winget install Python.Python.3.12    # Python 3.11+
winget install Git.Git               # drift anchoring uses git; install Git for Windows
pip install yigraf                   # or: pipx install yigraf
```

### From source (development)

```bash
git clone https://github.com/mansilla/yigraf.git
cd yigraf
uv sync                  # create the venv + install deps (incl. dev tools)
uv run yigraf --help
uv run pytest
```

### Semantic recall (optional tuning)

Semantic recall is **on by default** via the bundled fastembed backend — nothing to install. Two knobs,
in `yigraf/config.yaml` under `embeddings.backend`:

- **`none`** — turn it off; retrieval falls back to lexical (keyword) search.
- **`sentence-transformers`** — swap onto the torch backend (`pip install "yigraf[embeddings-torch]"`).
  Only worth it for Apple-Silicon MPS throughput or the exact fp32 model; the two backends agree to
  ≈0.9999 cosine, so quality is effectively identical.

On the first `yigraf build`, the small `bge-small` model downloads from the HuggingFace Hub (the only
time HF is involved; the one-time "unauthenticated Hub" notice is harmless).

## How yigraf works

yigraf projects your repo into one graph and keeps it in sync with the *why*:

1. **Index** — `yigraf build` parses your code into file/module/symbol nodes, each with an
   AST-normalized content hash (so reformatting and comments don't count as change).
2. **Author** — write **intents** (specs) and **plans** (tasks) as Markdown; capture **memory**
   (a decision + its reasoning) with `yigraf remember`.
3. **Link** — `yigraf link <task> <symbol>` records which code implements a task and **anchors** the
   link to that symbol's current content hash.
4. **Retrieve** — `yigraf context "<topic>"` returns a scoped, token-budgeted slice: the governing
   intents, the implementing symbols (as locators + signatures), prior decisions, open tasks, and any
   drift — a small map, not a pile of file dumps.
5. **Enforce** — when a symbol's anchored content changes, yigraf reports **drift** so the change gets
   re-verified against what governs it (or the link re-anchored / the decision superseded).

With Claude Code wired up (`yigraf install-claude-hooks`), steps 4–5 happen automatically: a
**PostToolUse** hook injects governing intent + drift the moment the agent edits a governed file, and a
**SessionStart** hook re-injects the active plan after a `/clear` — so a flow interrupted by a context
reset resumes instead of restarting. The hook stays silent on ungoverned, undrifted edits (no nagging).
It also wires a **statusline** — the spinning `[Yigraf]` graph-health bar (symbols, intents, open tasks,
drift, freshness) plus a **context-window gauge** (`ctx ▰▰▱▱ 42%`) — so you see the graph's shape and how
full the window is on every refresh, without spending the agent's context. It's a dependency-free Python
adapter (`yigraf statusline`), so the gauge works out of the box (no `jq`, no shell). The statusline is a
Claude Code surface; an existing statusLine of yours is left untouched.

The statusline also checks PyPI **at most once a day** (cached in the gitignored `.local/` sidecar,
fail-open) and shows an `⬆ <version>` marker when a newer yigraf is released — `yigraf status` in a
terminal then prints the one-line update command. No background job, no scheduler.

### Works with any host (two channels)

yigraf reaches an agent through **pull** (the agent calls a tool) and/or **push** (yigraf injects at the
moment of action). **MCP is the universal floor** — `yigraf mcp` exposes the graph as tools to any
MCP host. **Push hooks are a thin complement where a host has them** (Claude Code, Codex). They're not
exclusive: on Claude Code/Codex you can run both. The full per-host matrix and wiring is in
[`docs/hosts.md`](docs/hosts.md); MCP config per host is in [`docs/mcp.md`](docs/mcp.md).

| Host | Pull (MCP) | Push (hooks) | Wire it |
|------|:---------:|:------------:|---------|
| Claude Code | ✓ | ✓ | `yigraf install-claude-hooks` |
| Codex CLI | ✓ | ✓ | `yigraf install-codex-hooks` |
| Antigravity IDE | ✓ | — | `yigraf install-antigravity` |
| Cursor / Windsurf / other MCP | ✓ | — | point at `yigraf mcp` (`docs/mcp.md`) |

## Files yigraf creates

`yigraf init` lays down a `yigraf/` workspace at your repo root:

```
yigraf/
├── config.yaml                 # committed — enabled languages, ignore globs, retrieval tunables
├── intents/<slug>.md           # committed — requirement / goal / capability specs
├── plans/{active,completed}/   # committed — plans + tasks (the filesystem is the state)
├── memory/<id>-<slug>.md       # committed — decisions / constraints + the "why"
├── graph.json                  # committed — the graph projection (recomputable state only)
├── index/                      # gitignored — embedding index (rebuildable)
├── cache/                      # gitignored — extraction cache
└── .local/                     # gitignored — volatile telemetry (usage / last_seen)
```

The **committed** artifacts (`intents/`, `plans/`, `memory/`, `graph.json`, `config.yaml`) are the
shareable record — they travel with the repo, so the next agent or teammate inherits the *why*. Derived
and volatile state stays gitignored and rebuilds from source. yigraf also writes a self-contained
`yigraf/.gitignore`, so nothing extra needs to be added to your repo's ignore rules.

Opt-in installers wire yigraf into your tooling (machine-specific wiring is gitignored; the shareable
SKILL/AGENTS/rules are committed):

- **`yigraf install`** — **auto-detects** your host (Claude Code / Codex / Antigravity) and wires each;
  falls back to the universal MCP server for anything else. `--host <name>` targets one explicitly.
- **`yigraf install-claude-hooks`** — `.claude/settings.local.json` (machine-local hooks) + `SKILL.md`.
- **`yigraf install-codex-hooks`** — `.codex/hooks.json` (SessionStart + best-effort PostToolUse).
- **`yigraf install-antigravity`** — `.agents/rules/yigraf.md` + prints the MCP-server config to add.
- **`yigraf install-hooks`** — a git **post-commit** hook that keeps `graph.json` synced to `HEAD`.

For any other MCP host, run `yigraf mcp` as the configured server (see [`docs/mcp.md`](docs/mcp.md)).

## Language support

16 languages, indexed at two depths (bespoke extractors for Python/Go/JS-TS, a generic tags-query tier
for the rest). The full **tested** capability matrix — symbols / calls / imports / inheritance / drift,
per language — is in **[`docs/language-support.md`](docs/language-support.md)**.
