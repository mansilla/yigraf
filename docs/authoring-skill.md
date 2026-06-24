# yigraf — Authoring Skill (the guided spec flow)

> The **delivery** side of R9: how OpenSpec's guided planning UX (`why → scenarios → design → tasks`)
> is re-expressed as a fluid Claude Code skill over the graph — **no folder/state-machine ceremony**.
> Governed by `DESIGN.md` R9 + the R9 delivery corollary; spec semantics in `docs/spec-lifecycle.md`;
> ships in **M5** (`docs/BUILD-PLAN.md`). Read/write mechanics: `docs/retrieval-design.md`,
> `docs/capture-flow.md`.

## 0. What it is / when it fires

A Claude Code skill (`SKILL.md` body) that turns a fuzzy "let's build X" into a **linked, verifiable
spec → finished code**, using the `yigraf` verbs as the context API. It replaces OpenSpec's
`/opsx:propose … apply … archive` with a conversation over the graph: same guidance, none of the
change-folder bookkeeping (which the graph makes redundant — R9b).

Fires when the user signals intent to build or change something ("let's add X", "spec out Y") or is
invoked explicitly. It is **suggestive, never gated**: the user may jump phases, skip design, or
reopen scenarios mid-implementation.

## 1. The flow

```
   user intent
       │
   0 ORIENT ───► yigraf context "<topic>"       find existing intents/code/why; dedup
       │           └─ overlaps an existing spec? → refine / supersede, don't duplicate (R9b)
   1 WHY ───────► capture goal + reasoning       → memory node `serves` intent (mem-milestone;
       │                                            v0: parked in the intent's notes / decision_log)
   2 SCENARIOS ─► yigraf intent                   statement (SHALL/MUST) + Given/When/Then  ◄── the heart
       │
   3 DESIGN ────► yigraf intent (design field)    the *how* (optional); rejected alts → memory
       │
   4 TASKS ─────► yigraf plan                      task nodes; `tracks`→intent, `requires` order
       │
   5 IMPLEMENT ─► yigraf link <task> <symbol>      `implements` edge, anchored at commit (the seam)
       │           └─ PostToolUse nudges if a symbol under an active task is edited unlinked
   6 FINISH ────► set status: satisfied → verified?  satisfied ∧ live link ∧ no drift (R9c)
                   └─ later drift re-opens it (no "archive and forget")
```

## 2. Phase → verb → graph result → what it replaces

| Phase | `yigraf` verb | Graph result | OpenSpec analog |
| --- | --- | --- | --- |
| **0 Orient** | `yigraf context` | (read) — finds existing intents to refine vs. duplicate | *(none — graph advantage)* |
| **1 Why** | — (`remember`, mem-milestone) | memory node `serves` intent; v0: `decision_log` | `proposal.md` |
| **2 Scenarios** | `yigraf intent` | intent node: `statement` + `scenarios` | `specs/` requirements + scenarios |
| **3 Design** | `yigraf intent` (`design`) | `design` field; rejected alts → memory | `design.md` |
| **4 Tasks** | `yigraf plan` | plan + task nodes; `tracks`/`requires` | `tasks.md` |
| **5 Implement** | `yigraf link` | `implements` edge, anchored | *(none — OpenSpec can't link code)* |
| **6 Finish** | set `status: satisfied` | `verified` predicate computes (R9c) | `apply` / `archive` |

## 3. The two invariants that keep it graph-native (not ceremony)

1. **Fluid, never gated.** The skill *suggests* the next phase but blocks nothing — OpenSpec's "fluid
   not rigid," enforced by *not building phase gates*. The only hard signal is the derived `verified`
   check at the end, and even that is **surfaced, not blocking** (R9c).
2. **Context-first, dedup-by-default.** Phase 0 is non-negotiable: always `yigraf context` before
   authoring, so a new spec **refines/supersedes** an existing one (`supersedes` edge) rather than
   spawning a duplicate. This is what replaces OpenSpec's change-folder bookkeeping — the graph
   already knows what exists.

## 4. Worked dialogue (compressed)

> **User:** let's make sessions expire after idle.
> **(0)** `yigraf context "session expiry"` → no existing intent; `auth/session.py#refresh` is the
>   live code. New spec.
> **(1→2)** "What should happen on idle vs. active?" → co-writes scenarios → `yigraf intent` creates
>   `int:session-expiry` (SHALL expire after 30m; 2 scenarios).
> **(3)** "Optimistic-locked refresh — a DB lock would serialize a hot path." (rejected pessimistic
>   lock → memory, mem-milestone) → fills `design`.
> **(4)** `yigraf plan auth-hardening` → task "implement idle expiry" `tracks → int:session-expiry`.
> **(5)** implements it, commits → `yigraf link task:auth-hardening/1 auth/session.py#refresh`.
> **(6)** sets `status: satisfied` → `verified` ✓. If `refresh()` changes later, the spec re-opens.

## 5. How hooks complement the skill (R8)

- **PostToolUse** (`Edit|Write`) — nudges the phase-5 link when a symbol under an active task is
  edited unlinked, and surfaces drift / `satisfied`-but-unverified reconcile lines (R9c).
- **SessionStart** (`clear|compact`) — re-injects the active plan + governing intents, so a flow
  interrupted by `/clear` **resumes** instead of restarting.

The skill is the *guidance*; the hooks are the *safety net* — the agent gets nudged even when it
forgets the ritual.

## 6. v0 vs. memory-milestone behavior

The skill ships and runs in **v0** for phases **0, 2, 4, 5, 6** (intent + plan + link + the `verified`
check — all v0 mechanics, `docs/yigraf-v0.md`). Phases **1 and 3's *why*-capture into memory nodes**
light up at the **memory milestone**; until then the skill still elicits the reasoning but parks it
in the intent's `decision_log` rather than `remember`-ing it as a linked node.

## 7. Open / deferred for the real `SKILL.md`

- **Authored against M2's actual verb surface.** This is the *flow* sketch; the literal `SKILL.md`
  (frontmatter + body) is written once `yigraf intent/plan/link` exist, so it doesn't drift from
  flags that aren't final.
- **Scenario structure.** v0 scenarios are prose Given/When/Then in the body. Whether to make them
  machine-parseable (for future test generation) is a **post-v0** question — leave prose for now.
- **`remember` verb + the why→memory capture** arrive with the memory milestone (capture lead is the
  open decision in `memory-model.md` §5).
