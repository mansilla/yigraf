# yigraf eval harness

Does yigraf actually change how an agent works? This harness answers that with an **A/B**: the same
question through `claude -p` **with** yigraf's hooks and **without** them, on the same repo, N times
each — then reports the deltas. It's the instrument that turns "legible + enforceable" from a design
claim into a measured one, and it's the **gate for the source-vs-signature experiment** (flip the
render knob, re-run, compare).

Methodology is lifted from the CodeGraph study (`origins/codegraph`), adapted to yigraf's governance
framing. See `docs/research/` and the codegraph comparison for the why.

## What it measures (and what it deliberately doesn't)

**Optimize for sufficiency, not token cost.** The headline metrics are **tool calls, Read count, Grep
count, and wall-time** — because an agent falls back to Read/Grep the instant a tool's answer is
insufficient, and a token-cheap answer that triggers a Read is *more* expensive end-to-end (extra
round-trip + latency). Tokens are reported too, but as a secondary, noisy signal — never the target.

Tokens are summed **per assistant turn** (from each message's `usage`), not read off the final
`result` object, so the count is robust across Claude Code versions.

## Floor-model policy — keep it Sonnet

Every arm runs `--model sonnet --effort high`. **Always.** Two reasons, the second mattering more:
Sonnet doesn't burn budget, and **Sonnet is the deliberate floor** — an affordance that lands on a
weaker model generalizes *up* to every stronger host, while one that only works on Opus/Fable doesn't
generalize *down* to the agents most users actually attach yigraf to. Both arms always use the same
model. Don't raise it without a specific reason.

## Run-to-run variance is real — report the median

Agent runs vary a lot run-to-run. Use **≥2 runs/arm** (CodeGraph uses 4), report the **median**, and
quote a range, never a single run. `--runs 4` is a good default once you care about the number.

## Usage

```bash
# A/B the built-in case battery on this repo (yigraf, self-hosted)
uv run python scripts/eval/run_ab.py --repo . --runs 4 --isolate

# A single ad-hoc question
uv run python scripts/eval/run_ab.py --repo . --question "what governs auth/session.py?" --runs 2

# Parse a transcript you already captured (offline; no claude needed)
uv run python scripts/eval/parse_run.py scripts/eval/runs/<ts>/why-this-code__with__0.jsonl
```

### How the two arms are isolated

The arms differ in **exactly one thing**: whether yigraf's `PostToolUse` + `SessionStart` hooks are
wired. The harness generates two settings files and passes each via `claude --settings`:

- **with** → the same hooks `yigraf install-claude-hooks` installs, pointed at `--hook-cmd`
  (default `uv run yigraf`).
- **without** → `{"hooks": {}}`.

Both arms also get `--strict-mcp-config --mcp-config <empty>` so ambient MCP servers can't pollute the
comparison.

> **Two ambient channels can leak the affordance into *both* arms — `--isolate` moves both aside.**
> `--settings` *merges* over the repo's `.claude/settings.json`, so committed yigraf hooks could wire
> the hook into the *without* arm. And `.claude/skills/` — the yigraf **Skill** itself says *"run
> `yigraf context` first"*, so an agent in a yigraf-skilled repo re-verifies governance with **no hook
> at all**, which the enforceable judge can't distinguish from a hook-driven re-verify. **`--isolate`
> moves aside `.claude/settings.json` / `settings.local.json` *and* `.claude/skills/`** for the run
> (restored after), so the arms differ in exactly one thing — the hooks. It is **required** for the
> enforceable case on yigraf-on-yigraf; the first live run skipped the Skill and got a confounded null
> (both arms ran `yigraf context` from the Skill).

## Enforceable axis (yigraf's moat — now auto-judged)

The structural cases prove *legibility* (fewer tool calls to the same answer). The **enforceable** case
(`drift-reverify` in `cases.yaml`) probes the thing only yigraf has: does the **drift hook change
behavior**? The agent is asked to edit a *governed* symbol; its own edit drifts the implements-anchor,
so the PostToolUse hook surfaces the drift + what governs the code. The **with** arm should acknowledge
that governance and re-verify (or re-link); the **without** arm (no hook) edits blind.

`run_ab.py` scores this automatically with **`judge.py`** — a deterministic, offline-testable scorer
that reads each arm's transcript and detects enforcement *behaviour*: governance acknowledged in the
agent's reasoning (drift / a requirement / a decision / re-linking) **or** a verification action (a
`yigraf context`/`drift`/`link` call, **or reading the graph/artifacts** — `graph.json` or an
`intents/`/`memory/`/`plans/` file, via the Read tool *or* a Bash `cat`/`grep`/`python`). The
**verdict fires only when the hook changed behaviour** — WITH re-verified AND WITHOUT edited blind.
With `--runs N` each run is judged independently and the **rate** is reported (n=1 → quote the run):

```
ENFORCED: 4/4 run(s)
    run 0: True — with-yigraf re-verified (governance×2, verify-actions×1); without-yigraf edited blind
    run 1: True — …
```

- Enforceable cases run with optional `setup`/`teardown` shell steps (in the repo, per run). `teardown`
  restores the working tree after each run — the shipped case uses `git checkout -- <file>`. Adapt the
  symbol/file to your repo.
- **The edit must actually land**, or there's no drift and the hook never fires. Headless `claude -p`
  has no one to approve a Write prompt (stdin is `/dev/null`), so the harness runs
  `--permission-mode bypassPermissions` by default (identical in both arms; safe because teardown is
  git-reversible). Without it the symbol never drifts and *both* arms look "blind" — a false negative,
  not a real verdict. Override with `--permission-mode acceptEdits` to restrict to file edits only.
- Judge a pair of transcripts directly: `python scripts/eval/judge.py <with>.jsonl <without>.jsonl`.
- Add a model judgment for the nuanced call: `--llm` (one extra `claude` call over a compact trace).

The deterministic scorer is the contract (unit-tested in `tests/test_eval_judge.py`); the LLM judge is
an optional second opinion.

## Files

| file | role |
|---|---|
| `run_ab.py` | orchestrator — runs both arms × N, tabulates with-vs-without deltas |
| `parse_run.py` | stream-json transcript → metrics; **no `claude` dependency**, unit-testable offline |
| `cases.yaml` | the question battery + the enforceable scenario |
| `runs/<ts>/` | captured transcripts + the exact per-arm settings used (gitignored) |
