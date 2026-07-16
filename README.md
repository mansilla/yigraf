<p align="center">
  <img src="https://raw.githubusercontent.com/mansilla/yigraf/main/assets/logo.png" alt="yigraf" width="120" height="120">
</p>

<h1 align="center">yigraf</h1>

<p align="center"><em><strong>"Why I Graph?"</strong> — the memory your coding agent doesn't have.</em></p>

yigraf gives your AI coding agent a memory that survives `/clear`: one connected graph over your
code, what it's *for*, what's *left to do*, and *why* it ended up this way — and it hands the agent
exactly the right slice of that, right when it's working.

It's a tool **for the agent**, not another dashboard for you. You're the principal: you set the
direction and answer the occasional judgment call. The agent does the work — and now it does it
without forgetting.

## Why

Your agent is brilliant and amnesiac. Every `/clear` wipes what it knew. And the code itself never
told the whole story: it records *what* runs, never *why* it's shaped that way, *what* it's supposed
to guarantee, or *what* you were halfway through changing. So every session your agent relearns the
repo from scratch, re-reads files it already understood, and re-litigates decisions you settled weeks
ago — sometimes undoing them.

yigraf keeps that missing context as a living graph next to your code, and feeds the relevant piece
back to the agent at the moment it acts. The agent stops starting over.

## What yigraf gives your agent

Four questions an agent can't answer from source alone — and loses on every reset:

| The question | yigraf calls it | What it holds |
|---|---|---|
| **What is this?** | `structure` | your code — files, symbols, calls (parsed, 16 languages) |
| **What is it *for*?** | `intent` | the specs and guarantees the code must uphold |
| **What am I doing?** | `plan` | goals and tasks, and which code implements them |
| **Why is it this way?** | `memory` | the decisions, the reasoning, the roads not taken |

The magic is in the **links between them**. A task points at the symbols that implement it. A decision
is pinned to the code it concerns. A spec governs a region of the repo. So when your agent asks "what
governs this file?", yigraf can answer — and when code drifts away from the thing that was supposed to
hold, yigraf notices and says so.

## Get started — just tell your agent

yigraf is a tool for agents, so setting it up is a job for your agent. In any repo, say:

> **"Install github.com/mansilla/yigraf and wire it into this project."**

A capable agent installs the CLI, indexes your code, and connects yigraf to your host — Claude Code,
Codex, Cursor, and friends are auto-detected; anything else gets the universal MCP server. It won't
touch your `requirements.txt` (yigraf is a dev tool, not a runtime dependency).

Rather do it yourself? Three lines:

```bash
pipx install yigraf     # isolated CLI (or: pip install yigraf / uv tool install yigraf)
yigraf init && yigraf build     # create the workspace + index your code
yigraf install                  # wire your agent host (auto-detects; falls back to MCP)
```

Full install options (per-OS, from source, MCP config, semantic-recall tuning) live in the
**[guide](docs/guide.md)**.

## Using it — just talk to your agent

You don't run yigraf; you tell your agent to. It listens on your repo and speaks up at the right
moments — but you can always prompt it directly:

- **Starting something?** *"Before you change the auth flow, ask yigraf what governs it."* Your agent
  pulls the intent, the plan, and the past decisions that touch that code — so it works with the grain
  instead of relearning from scratch.
- **Saw a drift warning?** *"Check what yigraf's drifts are about."* Each one means code moved away
  from something that was supposed to hold. Your agent walks them and either confirms it still holds or
  flags what changed.
- **yigraf flagged a conflict?** *"Let's go through the conflicts one by one."* Two live beliefs
  disagree about the same code. You decide which wins — yigraf never silently picks.
- **Made a real decision?** *"Remember why we did this, and what we ruled out."* It's saved as a
  memory and resurfaces the next time someone touches that code.
- **Coming back to a project?** *"Ask yigraf what's in flight."* The active plan and open tasks come
  back, so a thread dropped last week picks up where it left off.

That's the whole loop. Your agent handles the mechanics ([`context`](docs/guide.md#retrieve),
[`link`](docs/guide.md#link), [`drift`](docs/guide.md#drift),
[`remember`](docs/guide.md#memory)); you stay in plain language. The deeper mechanics — how drift is
detected, how conflicts resolve, how a memory earns trust — are in the **[guide](docs/guide.md)**.

## Works with your host

yigraf reaches your agent two ways: **pull** (the agent asks yigraf for context over
[MCP](docs/mcp.md) — works everywhere) and **push** (yigraf injects the governing slice the moment the
agent edits a file — where the host has the hooks for it). You always get pull; you get push at the
best fidelity your host allows.

| Host | Pull | Push | Wire it |
|------|:----:|:----:|---------|
| Claude Code, Codex | ✓ | edit-time hooks | `yigraf install` |
| Cursor, Windsurf, Kilo, Antigravity | ✓ | always-on rule | `yigraf install` |
| any other MCP host | ✓ | — | point it at `yigraf mcp` |

Details and the full per-host matrix: **[docs/hosts.md](docs/hosts.md)**.

## Learn more

- **[Guide](docs/guide.md)** — install in depth, the full workflow, and how drift, conflicts, and
  memory maturity actually work.
- **[Hosts](docs/hosts.md)** · **[MCP setup](docs/mcp.md)** · **[Statusline](docs/statusline.md)** —
  wiring yigraf into your tools.
- **[Language support](docs/language-support.md)** — the tested capability matrix across 16 languages.

## Status

**yigraf 1.0 is local** — everything runs self-contained inside a single repo/folder, no network, no
account. Multi-user, hosted, real-time collaboration is the **2.0** roadmap. MIT licensed.
