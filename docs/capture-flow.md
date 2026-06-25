# yigraf — Capture Flow

> How nodes and edges get *written*: the skill + hook mechanics, boundary detection, anchor writing,
> and dedup/supersede. The "write" counterpart to `docs/retrieval-design.md` (the "read").
> Builds on `docs/memory-model.md` (capture decision: agent-asserted at commit boundaries) and
> `docs/graph-design.md` (artifacts = truth, anchors in frontmatter, counters in graph.json).

## 0. What capture must satisfy (recap of decisions)

- **Agent-asserted, at a commit boundary** — record only when a decision's consequence lands in an
  artifact (a Write/Edit, or a task marked done), never mid-reasoning. Pre-action churn stays invisible.
- **Certainty earned behaviorally** — new nodes are `working`; survival promotes them to `settled`.
- **Mind-changes via supersession** — never edit-in-place a decision; append a new node + `supersedes`.
- **Low friction** — the agent does it because a skill makes it cheap and a hook nudges; the human
  types nothing.

Two things get captured: **edges** (`implements`/`tracks` — the v0 spine) and **memory nodes**
(`decision`/`constraint`/… — the memory milestone). Same flow; the milestone just adds node types.

## 0a. Capture trigger taxonomy (capture ≠ just the `implements` link)

"Capture" spans several distinct *events*, each writing different node/edge types and — critically —
firing at a **different kind of boundary**. The earlier draft was code-edit-centric (only the
PostToolUse boundary); in fact yigraf hooks **three boundary kinds**:

- **A. Conversational/turn boundaries** — UserPromptSubmit, Stop/end-of-turn (events 1, 4, correction)
- **B. Plan-approval boundary** — plan-mode exit / plan artifact accepted (event 2)
- **C. Code/task boundaries** — PostToolUse on Write/Edit, task-done (event 3)

| # | Event | Writes | Boundary = the *conclusion* | Detection | Family |
| --- | --- | --- | --- | --- | --- |
| 1 | **Intent realized** | `intent` node | a design/thinking iteration *settles* on what to build | `yigraf intent` (skill); nudge on first action after a design discussion | intent |
| 2 | **Plan approved** | `plan`+`task` nodes, `tracks`/`requires` edges | plan is approved (steps/tasks clear) | `yigraf plan`; **plan-mode-exit** hook (boundary B) | plan |
| 3 | **Task/impl done** | `implements` edge + anchor; decision memory | task finished / impl stage complete | `yigraf link`; PostToolUse + task-done ritual (boundary C) | structure↔intent/plan, memory |
| 4 | **Durable user instruction** | `memory` (preference/constraint/learned-fact) | user states a durable rule/idea | `yigraf remember`; **UserPromptSubmit** nudge (boundary A) | memory |
| + | **Correction/feedback** | `constraint` memory, **promotable to an enforced check** | user corrects agent / review lands | `yigraf note-constraint`; boundary A | memory |
| + | **Supersession** (*cross-cuts 1–4*, not a 5th event) | new node + `supersedes` edge | any capture contradicts an existing node | dedup-at-write (§4) | any |
| + | **Bootstrap mining** (batch, deferred) | nodes/edges from comments/commits/PRs | one-time / on-demand | build-time extractor | any |

**Invariants across all events** (unchanged): capture at the *conclusion* of the boundary, never
mid-stream (events 1 & 4 are exactly "final conclusion of a thinking step"); agent-asserted via
explicit verbs; `working` maturity earned to `settled` by survival; changes via supersede, never
in-place edits.

The §2 boundary-detection and §1 write-surface below now cover all three boundary kinds (not just C).

## 1. The write surface (CLI verbs the agent calls)

| verb | writes | event (§0a) |
| --- | --- | --- |
| `yigraf intent "<statement>" [--type requirement\|goal]` | a new `intents/<slug>.md` node | 1 — intent realized |
| `yigraf plan "<title>" [--tasks …] [--tracks <intent>]` | a `plans/active/<slug>.md` node + task sub-nodes + `tracks`/`requires` edges | 2 — plan approved |
| `yigraf link <intent\|task> <symbol> [--as implements\|tracks]` | a cross-family edge + **anchor** (target's current `content_hash`) into the source artifact's frontmatter | 3 — task/impl done |
| `yigraf remember --type <t> [--serves <id>] [--concerns <sym>] [--rejected "<alt>"] --why "<…>" "<statement>"` | a new `memory/<id>-<slug>.md` node + its edges + anchors | 3 (decision) / 4 (user idea) |
| `yigraf supersede <old-id> --why "<…>" "<statement>"` | a new node (intent/plan/memory) with `supersedes: [<old-id>]` | supersession (any) |
| `yigraf note-constraint [--concerns <sym>] "<rule>"` | a `constraint` memory node (flagged promotable to a check) | correction/feedback |

All verbs: append-only to artifacts, then incrementally update `graph.json` (nodes/edges + bump
counters). They never block the agent's actual work (fail-open).

## 2. Boundary detection — *when* the agent is prompted to capture

Two complementary mechanisms (mirrors retrieval's two triggers):

**(a) Skill-driven (primary, in-flow).** The yigraf skill body instructs the agent, as part of its
working loop: *"After you implement a task, `yigraf link` it to the governing intent. When you make a
non-obvious choice (picked an approach over a named alternative, set a constraint, worked around
something), `yigraf remember` it — one line of why + the rejected option."* This is the
ReCAP-aligned capture: the reasoning `T` already exists in the agent's head at that moment; the skill
just makes persisting it a habit.

**Linking cadence — once per task completion, not per edit.** A link is a `(task → symbol)`
relationship, so it's a *task-boundary* event. A task touches many files but only ~1–3 symbols
*implement* its behavior (the rest are tests/imports/incidental), so a finished task yields ~1–3
`yigraf link` calls, made together at completion — single-digit calls/day at typical throughput
(~3.5 PRs/day). This sparsity is *why* explicit-only is viable: linking is a low-frequency deliberate
act, not a per-edit tax. We make it reliable by **piggybacking on the task-done ritual** the agent
already performs (skill: *"to mark a task done, name the symbols that implement it"*) — so link
frequency ≡ task-completion frequency, structurally, not a separate thing to remember. The agent
links *implementing* symbols, not every file touched (quality over coverage). Bonus: linking at
task-end anchors the drift hash to the **final** implemented state (correct), not an intermediate one.
Missed links are caught by the background **done-but-unlinked sweep** (§7) — so in-the-moment
compliance need not be perfect.

**(b) Hook-driven nudge (backstop, boundary-triggered) — one hook per boundary kind (§0a).** Each is
fail-open and silent-unless-relevant; each *detects a boundary*, the agent *decides* whether there's
something to capture:

- **Boundary A — conversational** (`UserPromptSubmit`, `Stop`): on a user message that looks like a
  durable instruction/preference/correction, nudge → `yigraf remember`/`note-constraint` (events 4,
  correction). On end-of-turn after a settled design discussion, nudge → `yigraf intent` (event 1).
- **Boundary B — plan approval** (plan-mode exit / accepted plan artifact): nudge → `yigraf plan`
  (event 2), creating the plan + tasks + `tracks` edges.
- **Boundary C — code/task** (`PostToolUse` on Write/Edit, task-done): the original commit boundary
  for `yigraf link` + decision memory (event 3), detailed below.

> Hook event names above are Claude Code's; per the multi-tier integration philosophy, each host maps
> to whatever boundary signals it exposes (some hosts lack one or more — those events fall back to
> skill-driven capture (a) only). Exact per-host wiring is a v0 implementation detail.

**Boundary C in detail.** After the agent edits a file, the `PostToolUse` hook (fail-open,
silent-unless):
- computes whether the touched symbol has an `implements`/`concerns` edge already;
- if the edit touches code tied to an **active task** with no `implements` edge yet → inject a nudge:
  *"You edited `auth/session.py#refresh` while task auth/3 is active — link it with `yigraf link`?"*;
- if the edit changed a symbol that an existing edge anchors (hash moved) → that's **drift**, surfaced
  by the retrieval hook (not re-captured here).

The hook **detects the boundary**; the agent **decides** whether there's a decision worth recording
(the hook can't know intent, only that code moved). No nagging: silent when the locus is unrelated to
any active task/intent.

> Boundary = a Write/Edit (decision became code) **or** a task checkbox flipped to done. We do **not**
> capture on every tool call or mid-reasoning — that's the whole point of "conclusion, not musing."

**(c) Pre-`/clear` distillation (deferred backstop).** A Stop/PreCompact hook can run a distillation
pass ("extract decisions not yet captured") — listed in memory-model §2 as option B, deferred until
agent-asserted capture proves insufficient.

## 3. Anchor writing (how drift gets armed)

When `link`/`remember`/`note-constraint` creates an `implements`/`concerns` edge, it records the
target symbol's **current `content_hash`** as the edge's `anchor` in the *declaring artifact's*
frontmatter (graph-design §4):
```yaml
concerns: [{sym: sym:auth/session.py#refresh, anchor: H1a2b}]
```
This is the moment drift detection is "armed": later, when `current_hash(refresh) ≠ H1a2b`, retrieval
surfaces the reconcile instruction. Re-running `link` on the same pair **re-anchors** (the agent
re-verified the link holds) — that's how the agent clears a drift warning.

## 4. Dedup & supersede — keeping the graph clean at write time

Before creating a memory node, `remember` checks for collision (cheap, since we already have the
embedding index + counters):

1. **Near-duplicate** (high embedding cosine to an existing *active* node with overlapping
   `concerns`/`serves`) → **don't create a twin**; bump the existing node's `usage`/`refs_in`
   (reinforcement) and, if the `why` adds detail, append it. Prevents the graph filling with
   restatements of the same decision.
2. **Contradiction** (high similarity but opposite statement on the same `concerns` target) → this is
   a *mind-change*: create the new node with `supersedes: [old]`. Counters do the rest —
   `old.superseded_in += 1`, it sinks in ranking but stays as a `rejected-alternative` if it was ever
   referenced (else GC-eligible). This is exactly the "agent changes its mind" case handled cleanly.
3. **Genuinely new** → create the node.

Threshold-based; the agent can force-create with `--new`. Dedup is *advisory at write time* and also
re-run during the background GC pass (graph-design §3) so duplicates that slip through get merged later.

## 5. Lifecycle of one captured decision (end-to-end)

1. Agent implements idle-expiry in `refresh()`, marks task auth/3 progressing.
2. Skill prompts it → `yigraf link task:auth/3 sym:auth/session.py#refresh --as implements`
   → edge + `anchor: H1` written to the plan file; `refresh.refs_in += 1`.
3. Agent chose optimistic locking over a pessimistic lock → `yigraf remember --type decision
   --serves int:session-expiry --concerns sym:…#refresh --rejected "pessimistic row lock" --why
   "refresh path is hot; retry cheaper than serializing" "session refresh uses optimistic locking"`
   → `mem:001` created (`maturity: working`, `survival: 0`), edges + anchors written, embedded.
4. Three task-boundaries later, un-superseded → background pass promotes `mem:001` to `settled`.
5. Agent later switches to pessimistic → `yigraf supersede mem:001 …` → `mem:002` created,
   `mem:001.superseded_in = 1` (kept as rejected-alternative — it was referenced).
6. Someone edits `refresh()` → hash ≠ H1 → drift surfaced on next touch (capture not re-run; agent
   re-links to clear).

## 6. v0 vs later

- **v0:** `yigraf link` (implements/tracks) + the PostToolUse boundary nudge + anchor writing + drift.
  No memory nodes yet, so no embedding-based dedup — dedup is trivial (edge exists or not).
- **Memory milestone — M7+M8 (done):** `remember`/`supersede`/`note-constraint` (M7); embedding
  near-duplicate dedup at write time (M8, §4). **Still M9:** maturity promotion + GC of churn (they
  need the runtime `survival`/`usage` counters); and *contradiction* detection (M8 ships the near-dup
  half only — §7).
- **Later:** pre-`/clear` distillation (option B); the boundary-A/B nudges (UserPromptSubmit /
  plan-mode-exit, §0a); artifact mining for bootstrap (memory-model §2.4).

## 7. Open / tunable

- Dedup cosine threshold (near-dup vs new) and contradiction detection (same-target + opposing
  statement — heuristic vs a cheap LLM check via the host). *(M8 status: the near-dup guard ships at
  `dup_cosine=0.9` — advisory, `--new` forces, `supersede` bypasses — but the threshold is coarse
  (`bge-small` paraphrases sit ~0.8–0.9, so looser twins slip through) and **contradiction detection
  is not yet built**. Tune + add the opposing-statement check in M9 / alongside the GC merge pass.
  caveats M8.)*

- **Nudge assertiveness** — *how often the PostToolUse hook speaks up.* The hook fires on every
  Write/Edit; the question is when it bothers to inject "link this?". High = nudge on every unlinked
  edit during an active task (max recall, but most edits — typos, imports, tests — aren't link-worthy,
  so the agent learns to ignore the channel, muting drift warnings too). Conservative = only on
  substantive edits to non-trivial symbols, ~once per task (may miss some, but a missed link is
  recoverable; a muted tool is not). **Decision: conservative** — protect the signal; sweep missed
  links via the background "done-but-unlinked" check.

- **Auto-link vs always-explicit** — *who writes the edge when one should exist* (separate axis from
  the nudge). Auto-link: yigraf infers `implements` from circumstance (symbol edited while task
  active → task marked done) and writes the edge itself, `INFERRED` — zero friction but risks **false
  edges → false drift alarms**. Always-explicit: edge exists only if the agent ran `yigraf link`,
  `EXTRACTED` — high trust, but gaps if the agent forgets. **Decision: explicit for v0** — the drift
  check's value is its trustworthiness, and false alarms erode trust faster than gaps; matches the
  agent-asserted principle. Auto-link revisited later as opt-in.

Combined stance: gentle/occasional nudge + explicit-only linking + a background sweep that flags
implemented-but-unlinked tasks (rather than fabricating links in the moment).
