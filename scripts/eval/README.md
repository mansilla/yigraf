# yigraf eval harness

Does yigraf actually change how an agent works? This harness answers that with an **A/B**: the same
question through `claude -p` across three arms — full install, docs-only, and no-yigraf-at-all — on the
same repo, N times each, then reports the deltas. It's the instrument that turns "legible + enforceable" from a design
claim into a measured one, and it's the **gate for the source-vs-signature experiment** (flip the
render knob, re-run, compare).

Methodology is lifted from the CodeGraph study (`origins/codegraph`), adapted to yigraf's governance
framing. See `docs/research/` and the codegraph comparison for the why.

## What it measures (and what it deliberately doesn't)

**Optimize for sufficiency, not token cost.** The headline metrics are **tool calls, Read count, Grep
count, and wall-time** — because an agent falls back to Read/Grep the instant a tool's answer is
insufficient, and a token-cheap answer that triggers a Read is *more* expensive end-to-end (extra
round-trip + latency). Tokens are reported too, but as a secondary, noisy signal — never the target.

Tokens come from the final **`result.usage`**, with the per-assistant-turn sum kept only as a fallback
when a transcript has no result object. Summing per turn — which this harness used to do, for
"robustness across Claude Code versions" — is wrong in *both* directions, measured on a live run:
streaming turns carry a **partial** `output_tokens` (observed `3, 3, 3, 1` → "10" for an answer whose
real total was **814**, ~80× under), and every turn repeats the same `cache_read_input_tokens`, so
summing double-counts the prompt prefix (162,973 reported vs 64,354 actual, ~2.5× over). A robust
reading of the wrong quantity is still the wrong quantity.

## Floor-model policy — keep it Sonnet

Every arm runs `--model sonnet --effort high`. **Always.** Two reasons, the second mattering more:
Sonnet doesn't burn budget, and **Sonnet is the deliberate floor** — an affordance that lands on a
weaker model generalizes *up* to every stronger host, while one that only works on Opus/Fable doesn't
generalize *down* to the agents most users actually attach yigraf to. Every arm always uses the same
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
uv run python scripts/eval/parse_run.py scripts/eval/runs/<ts>/why-this-code__ambient__0.jsonl
```

### The three arms — and the two different claims they separate

A two-arm with/without design **conflates two questions that need different baselines**. The harness
runs three arms and reports both deltas:

| Arm | Hooks | Instruction files (`AGENTS.md`, `CLAUDE.md`, `.claude/skills/`) |
|---|:---:|:---:|
| `with` | ✅ | present |
| `ambient` | ❌ | present |
| `off` | ❌ | hidden |

- **Q1 — does the *hook* change behaviour?** → `with` vs `ambient`. This isolates event-scoped push
  (yigraf's moat) from the mere instruction to pull context.
- **Q2 — does *installing* yigraf change behaviour?** → `with` vs `off`. This is the user-facing claim.

The arms get their hooks via `claude --settings`: **with** → the hooks `yigraf install-claude-hooks`
installs, pointed at `--hook-cmd` (default `uv run yigraf`); the others → `{"hooks": {}}`. All arms also
get `--strict-mcp-config --mcp-config <empty>` so ambient MCP servers can't pollute the comparison.

> **`--isolate` is effectively required, and it now works per-arm.** *Every* arm hides
> `.claude/settings{,.local}.json`, because `--settings` *merges* over them and committed yigraf hooks
> would wire the hook into the hookless arms too. The **`off` arm alone** additionally hides
> `.claude/skills/`, `AGENTS.md` and `CLAUDE.md`.
>
> Three channels leak the affordance, each found by a live run producing a confounded null. The Skill
> (`SKILL.md` says *"run `yigraf context` first"*) was known. **The instruction files were not, and they
> are the bigger leak:** a hookless arm read `AGENTS.md`/`CLAUDE.md`, announced *"per the project's
> workflow"*, and ran `yigraf context` with no hook wired at all. On any repo whose own docs preach the
> tool — yigraf's own, above all — that makes both arms converge and the delta ~0 **by construction**.

**`off` keeps the `yigraf/` workspace on disk.** The intents and decisions are still there as plain
markdown the agent can grep and Read. Hiding them would make the questions unanswerable and turn the
comparison into a trivial win; the honest question is whether yigraf's *retrieval* beats grepping the
same facts, not whether having facts beats having none.

## Enforceable axis (yigraf's moat — now auto-judged)

The structural cases prove *legibility* (fewer tool calls to the same answer). The **enforceable** case
(`drift-reverify` in `cases.yaml`) probes the thing only yigraf has: does the **drift hook change
behavior**? The agent is asked to edit a *governed* symbol; its own edit drifts the implements-anchor,
so the PostToolUse hook surfaces the drift + what governs the code. The **with** arm should acknowledge
that governance and re-verify (or re-link); the hookless arms edit blind.

`run_ab.py` scores this automatically with **`judge.py`** — a deterministic, offline-testable scorer
that reads each arm's transcript and detects enforcement *behaviour*: governance acknowledged in the
agent's reasoning (drift / a requirement / a decision / re-linking) **or** a verification action (a
`yigraf context`/`drift`/`link` call, **or reading the graph/artifacts** — `graph.json` or an
`intents/`/`memory/`/`plans/` file, via the Read tool *or* a Bash `cat`/`grep`/`python`). The
**verdict fires only when the treatment changed behaviour** — `with` re-verified AND the baseline edited
blind. It is reported against BOTH baselines, since "enforced" means the hook's effect vs `ambient` and
the whole install's effect vs `off`.
With `--runs N` each run is judged independently and the **rate** is reported (n=1 → quote the run):

```
ENFORCED vs ambient: 4/4 run(s)
    run 0: True — with-yigraf re-verified (governance×2, verify-actions×1); baseline edited blind
    run 1: True — …
ENFORCED vs off: 4/4 run(s)
    run 0: True — …
```

- Enforceable cases run with optional `setup`/`teardown` shell steps (in the repo, per run). `teardown`
  restores the working tree after each run — the shipped case uses `git checkout -- <file>`. Adapt the
  symbol/file to your repo.
- **The edit must actually land**, or there's no drift and the hook never fires. Headless `claude -p`
  has no one to approve a Write prompt (stdin is `/dev/null`), so the harness runs
  `--permission-mode bypassPermissions` by default (identical in every arm; safe because teardown is
  git-reversible). Without it the symbol never drifts and *all* arms look "blind" — a false negative,
  not a real verdict. Override with `--permission-mode acceptEdits` to restrict to file edits only.
- Judge a pair of transcripts directly: `python scripts/eval/judge.py <with>.jsonl <baseline>.jsonl`.
- Add a model judgment for the nuanced call: `--llm` (one extra `claude` call over a compact trace).

The deterministic scorer is the contract (unit-tested in `tests/test_eval_judge.py`); the LLM judge is
an optional second opinion.

## Files

| file | role |
|---|---|
| `run_ab.py` | orchestrator — runs all three arms × N, tabulates the Q1 (vs `ambient`) and Q2 (vs `off`) deltas |
| `parse_run.py` | stream-json transcript → metrics; **no `claude` dependency**, unit-testable offline |
| `cases.yaml` | the question battery + the enforceable scenario (yigraf-self subjects; adapt per repo) |
| `runs/<ts>/` | captured transcripts + the exact per-arm settings used (gitignored) |
