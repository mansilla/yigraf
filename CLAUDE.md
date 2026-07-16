# yigraf — read this first

**yigraf is a tool for AI coding agents, not for human beings.** Every surface it exposes — the CLI
output, the hook injections, the error messages, the docs, this file — is designed to be *consumed by
an agent*, optimized for an agent's constraints (a finite context window, a working memory wiped by
`/clear`, no scrollback), and judged by whether it makes an agent's next action better. It is **not** a
tool for a human to "understand the codebase," read the plan, or browse the design. A human is the
*principal* whose intent yigraf carries; the **agent is the operator and the audience**.

## The name

**yigraf = "Why I Graph?"** It exists to answer, *for the agent*, the **why's** and **what-for's** of
its current state — the questions an agent cannot answer from source alone and loses on every reset:

- **What is this?** → `structure` (code symbols, files, calls — from tree-sitter)
- **What is it *for*?** → `intent` (the SHALL/MUST contracts and goals it serves)
- **What am I doing / what's left?** → `plan` (tasks in a DAG, with state)
- **Why is it this way?** → `memory` (the decisions, constraints, and rejected alternatives)

These four node families and the **cross-family edges** between them (`implements`, `tracks`,
`serves`, `concerns`, `supersedes`, `grounded_by`) *are* the answer. Retrieval is "ask once, get the
answer as a token-cheap slice." This is the whole product. (`grounded_by` names the evidence that
earns a memory's `empirical` grounding tier; like `concerns` it is anchored and drift-bearing.)

## The design law (apply it to every change)

When you add or change anything in yigraf, the test is **"is this better for the agent consuming
it?"** — never "is this nicer for a human to read." Concretely, this is why the code looks the way it
does, and the shape you must preserve:

1. **Errors teach abandonment — so recoverable conditions exit 0 with guidance, not a stack trace.**
   An unresolved locator, a near-duplicate, an existing name → `_guidance()` prints how to fix it and
   exits `0`, so the agent reads it and retries instead of learning "this tool fails, stop calling it."
   Only genuine stop-conditions (no workspace, the CI drift gate) exit non-zero. (`cli.py:_guidance`)
2. **Output is for a context window, not a screen.** `context` returns locators + signatures (not
   source by default), under a token budget, ranked — because the agent pays for every token and
   re-reading what's already encoded is the waste yigraf exists to remove. (`retrieval.py`)
3. **yigraf speaks *into* the agent's context, at the moment of action.** The value is delivered by
   Claude Code hooks: `PostToolUse(Edit|Write)` injects the governing intent + drift for the file just
   touched; `SessionStart(clear|compact)` re-injects the active plan + intents — *this is the
   mechanism by which memory survives `/clear`*. (`cli.py:_post_tool_use`, `_session_start`)
4. **Silence is a feature.** The edit hook returns `None` (injects nothing) unless the locus is
   actually governed or has drift. Respect the agent's attention budget; never nag on a routine edit.
   (`retrieval.py:context_for_locus`)
5. **Fail-open, always.** A hook or a query must never block or break the agent's work — every hook
   handler swallows exceptions and exits 0. (`cli.py:_run_hook`)
6. **Files are truth; the graph is a derived, recomputable projection.** The queryable graph is a
   *gitignored* SQLite materialized view (`.local/graph.db`) — never committed (a binary `.db` can't
   git-union-merge; the committed `graph.json` + its whole-graph merge lock are retired, mem:059). It's
   keyed by a content fingerprint of its inputs, so a read loads it and rebuilds only when source or
   assertion files changed. Never write volatile state (usage/last_seen/survival) into it — that's
   stripped at store time and re-applied as a read-time overlay. (DESIGN.md R1; `graphdb.py`)

If a proposed change optimizes for human ergonomics at the cost of any of these, it is probably wrong
for yigraf. State the agent-cost/benefit in the change, not the human-readability.

## The working loop (what the agent does with yigraf)

This is the loop the `yigraf` skill and `AGENTS.md` instruct an agent to follow on **any** repo:

```
yigraf context "<topic>"          # before touching code: governing intent, plan, prior why, drift
… do the work …
yigraf link task:<plan>/<n> sym:<path>#<name>   # name the symbols a task implements (anchors them)
yigraf remember "<decision>" --why "…" --concerns sym:<path>#<name> [--rejected "…"]   # persist the why
```

`context` is the **one read command** — intent, plan, implementing signatures, prior decisions, and
drift all come back through it. Don't reach for separate query/drift tools.

## Developing yigraf itself

yigraf is **self-hosted**: it indexes its own repo, so the loop above applies here too. Before
changing code, run `uv run yigraf context "<topic>"` to surface the governing intent and prior
decisions; after a task, `link` the symbols and `remember` the non-obvious choices.

- **Run / test:** `uv sync`, then `uv run pytest` (fast, no network). `uv run yigraf --help`.
- **Optional semantic recall:** `uv pip install -e '.[embeddings]'` (local `bge-small`). Absent ⇒
  retrieval degrades to the lexical seeder; never a hard dependency.
- **Docs:** the public references are [`README.md`](README.md) (overview, install, how-it-works) and
  [`docs/language-support.md`](docs/language-support.md) (the tested capability matrix). The internal
  design corpus (decision log, milestone notes, research) is not part of this repo or its history; the
  code comments that still cite it (e.g. `DESIGN.md R1`, `m3-notes.md §3`) are kept only as provenance
  shorthand. The authoritative *current* state is the code, the tests, and this file.
- **Layout:** package under `src/yigraf/` (src-layout is deliberate — `yigraf init` creates a data dir
  named `yigraf/` at a repo root, and the two must not collide).
- **Status:** **1.0 (local)** — the self-contained, no-network belief-revision engine is complete,
  self-hosted, and released (26 design intents `satisfied`). Counters are local + recomputable.
  The shared/committed counter model and hosted multi-user operation are **2.0 (online)** work
  (`int:yigraf-online-v1`, proposed).

## Conventions

- Commit messages and PRs follow the harness footer rules (see the agent's commit guidance). Only
  commit/push when asked.
- Match the surrounding code: terse module docstrings that cite the governing decision (e.g. `R1`,
  `M8`), dataclasses for results, no speculative abstraction.
