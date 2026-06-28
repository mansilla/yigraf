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
- **Memory** — capture decisions + the reasoning behind them; recall by **meaning** (optional embeddings)
  or lexically; a decision earns `settled` after surviving K commits un-superseded; `gc` archives churn.
- **Token-cheap retrieval** — `yigraf context "<topic>"` returns a scoped, budgeted slice (locators +
  signatures, not file dumps) — measured ≈2.5× cheaper than reading the file.
- **Agent integration** — Claude Code hooks inject governing intent + drift on edit and re-inject the
  plan after `/clear`; a skill teaches the rituals. The `yigraf` CLI works with any agent.

### Requirements (and what each is for)

| Requirement | Why |
|---|---|
| **Python ≥ 3.11** | yigraf runs as a Python CLI |
| **A git repo** | drift anchoring and git-derived maturity read git history (degrades gracefully without git) |
| **Tree-sitter grammars** | structure extraction — **bundled**, no setup |
| **An agent harness** | Claude Code gets hooks + a skill out of the box; any other agent can drive the CLI |
| **An embeddings backend** *(optional, `[embeddings]` extra)* | semantic recall of memory/intent by meaning; **falls back to lexical** retrieval if absent — never required |

## Quickstart

```bash
# 1. install (now on PyPI)
pip install yigraf

# 2. in your repo: create the workspace and index the code
cd your-repo
yigraf init
yigraf build

# 3. wire it into Claude Code (hooks + skill)
yigraf install-claude-hooks

# 4. use it
yigraf context "session expiry"          # a scoped, token-cheap slice for a topic
yigraf intent session-expiry -s "The system SHALL expire a session after 30m idle."
yigraf link task:auth/1 sym:src/auth/session.py#refresh   # anchor a task to its code
yigraf remember "chose monotonic clock" --why "wall-clock skews under NTP"
yigraf drift                             # report any intent↔code drift
```

## Installation

yigraf is on **PyPI**. It needs **Python ≥ 3.11**; the tree-sitter grammars are bundled, so there's
nothing else to set up. For a CLI you use across repos, an isolated install (pipx or `uv tool`) is nicest.

**Any platform — pick one:**

```bash
pip install yigraf                 # into the current environment
pipx install yigraf                # isolated CLI (recommended)
uv tool install yigraf             # isolated CLI, via uv

# with semantic recall (numpy + sentence-transformers):
pip install "yigraf[embeddings]"
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

Two opt-in installers wire yigraf into your tooling:

- **`yigraf install-claude-hooks`** — writes `.claude/settings.local.json` (machine-local hooks, *not*
  committed) and `.claude/skills/yigraf/SKILL.md`.
- **`yigraf install-hooks`** — adds a git **post-commit** hook that keeps `graph.json` synced to `HEAD`.

## Language support

16 languages, indexed at two depths (bespoke extractors for Python/Go/JS-TS, a generic tags-query tier
for the rest). The full **tested** capability matrix — symbols / calls / imports / inheritance / drift,
per language — is in **[`docs/language-support.md`](docs/language-support.md)**.
