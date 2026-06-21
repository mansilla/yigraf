# yigraf

A **harness primitive** for AI coding agents: one connected graph over four node families —
**structure** (code), **intent**, **plan**, and **memory** — that makes the right slice of an
agent's work **legible** (scoped, token-cheap retrieval) and **enforceable** (an intent↔code *drift
check* that fires when code and its governing intent diverge). It retrofits onto existing repos.

Design is in [`docs/DESIGN.md`](docs/DESIGN.md) (the authoritative decision log) and sequenced into
milestones in [`docs/BUILD-PLAN.md`](docs/BUILD-PLAN.md). Python; Claude Code first.

> **Status: M0 — scaffold.** `yigraf init` lays down the workspace. Structure indexing (M1),
> intent/plan linking (M2), drift detection (M3), retrieval (M4), and the Claude Code hooks/skill
> (M5) follow.

## Quickstart (dev)

```bash
uv sync                 # create the venv + install deps (incl. dev tools)
uv run yigraf --help
uv run yigraf init      # create ./yigraf/ in the current repo
uv run pytest
```

## Layout

- `src/yigraf/` — the package. A **src layout** is used deliberately: `yigraf init` creates a data
  directory named `yigraf/` at a repo root, so keeping the package under `src/` lets yigraf run on
  its own repo (the M6 dogfood goal) without the two `yigraf/` paths colliding.
- `docs/` — the design corpus. `DESIGN.md` wins over any detail doc.
- `origins/` — reference clones (OpenSpec, Graphify) studied during design; not part of the package
  (gitignored).

## The `yigraf/` workspace (what `init` creates)

```
yigraf/
├── config.yaml                  # committed — languages, ignore globs, K, retrieval weights
├── intents/<slug>.md            # committed — requirement/goal/capability nodes
├── plans/{active,completed}/    # committed — plan + task nodes (filesystem-as-state)
├── memory/<id>-<slug>.md        # committed — decision/constraint/… nodes (memory milestone)
├── graph.json                   # committed — derived projection; recomputable state only (R1)
├── index/                       # gitignored — embedding index (rebuildable)
├── cache/                       # gitignored — content-extraction cache
└── .local/                      # gitignored — volatile telemetry (usage / last_seen)
```
