# yigraf — Spec Lifecycle

> How a spec is authored, evolved, and marked finished — folding OpenSpec's planning strength into
> the graph **without** its ceremony. **Authoritative decision: `DESIGN.md` R9 (R9a/R9b/R9c).** Where
> this doc conflicts with the Decision Log, the log wins. Background: `docs/research/openspec-analysis.md`,
> `docs/yigraf-vision.md` §5, `docs/graph-design.md` §1–§2.

## 0. The principle

OpenSpec's ceremony — the four-artifact change folder (`proposal`/`specs`/`design`/`tasks`) and the
`propose → apply → archive` + delta-spec (`ADDED`/`MODIFIED`/`REMOVED`) workflow — exists to
compensate for OpenSpec having **no graph and no code awareness**. It re-bundles related concerns
into a folder and tracks change as a folder lifecycle because it has nothing else to connect them or
to verify completion against.

**yigraf has the graph.** So it keeps OpenSpec's *substance* (behavioral scenarios, an explicit
design/approach, a guided authoring flow) and its *philosophy* (fluid, no rigid phase gates) while
dropping the packaging that the graph makes redundant. Three moves: enrich the intent node (R9a),
evolve specs as durable nodes (R9b), and make "finished" enforceable (R9c).

## 1. R9a — What a spec carries (the enriched intent node)

The `intent` node keeps `statement` + `status` and **gains `scenarios` and an optional `design`
field**. Still **one file = one node** (D2; `graph-design.md` §4) — no change folder.

| field | meaning | source in OpenSpec |
| --- | --- | --- |
| `statement` | the behavioral contract, one line (SHALL/MUST) | spec requirement |
| `scenarios` | Given/When/Then examples — the *testable* behavior, and the target of the verified-done check | spec scenarios |
| `design` *(optional)* | the approach / *how* | `design.md` |
| `status` | `proposed` → `active` → `satisfied` → `archived` (soft guide, R9b) | — |

```markdown
intents/session-expiry.md
---
id: int:session-expiry
family: intent
type: requirement
status: active
---
## Requirement
The system SHALL expire a session after 30 minutes of inactivity.

## Scenarios
- Given a session idle for 30m, When a request arrives, Then respond 401 and clear the session.
- Given an active session, When a request arrives, Then refresh the idle timer.

## Design (how)
Optimistic-locked refresh; TTL tracked in the session store. (Rationale lives in memory, not here.)
```

**Deliberately dropped:** the `proposal.md` / `specs/` / `design.md` / `tasks.md` change-folder
bundle. Those concerns already decompose across families — proposal-*why* → **memory** (a node that
`serves` this intent), tasks → **plan** nodes (`tracks` this intent), the spec itself → this
**intent** node — joined by edges, not a folder.

## 2. R9b — How a spec evolves (durable nodes, git + supersedes)

Specs are **long-lived nodes edited in place.** There is **no `propose→apply→archive` workflow and
no delta-spec folders.** Change is tracked by mechanisms yigraf already has:

| OpenSpec mechanism | yigraf realization |
| --- | --- |
| change folder (a unit of change) | a normal git commit touching `intents/*.md` |
| delta spec `ADDED`/`MODIFIED`/`REMOVED` | the git diff of the intent file |
| superseding/replacing a spec | a `supersedes` / `refines` edge (`graph-design.md` §2) |
| `archive/<date>-<slug>/` | `status: archived` + GC archival (R3); git is the history |
| `apply` (mark change done) | the **verified-done** check (§3) |

The existing `status` field stays as a **soft guide** for the human/agent, never an enforced gate
(consistent with OpenSpec's "fluid not rigid").

## 3. R9c — What "finished" means (enforceable, not self-reported)

Two layers, kept distinct:

- **Asserted** — `status: satisfied`, set by the agent or human. Cheap, like ticking a box. This is
  all OpenSpec can offer.
- **Verified** *(derived, computed — never written back)*:
  ```
  verified(intent) ==  status == satisfied
                    ∧  ∃ at least one live `implements` edge from the intent (or a task that
                       `tracks` it) to a structure node
                    ∧  no drift on those edges   (current anchor hash == stored anchor; §glossary)
  ```

A spec that is `satisfied` but **not** `verified` (no link, or a drifted link) is **surfaced as a
reconcile message** — at `PostToolUse` when the agent touches related code, and in `yigraf context`
output — and is **never hard-gated**. Fail-open, consistent with R8 and the drift model (R4/R5). Drift
on a previously `verified` spec **re-opens it** — the thing OpenSpec structurally cannot do, because
it has no code graph.

**Worked example.** `int:session-expiry` is `active`. A task `tracks` it and the agent links the
implementing symbol (`implements` edge, anchored at commit). The agent sets `status: satisfied` →
now `verified` (live edge, no drift). Later someone edits `refresh()`; its `content_hash` changes →
drift → `verified` flips false → next time the agent touches that file the hook injects: *"int:session-expiry
is marked satisfied but `auth/session.py#refresh` changed since it was anchored — re-verify the
scenarios still hold, or relink."* No box stays ticked on stale code.

## 4. Delivery — the guided flow is a skill, not ceremony

The part of OpenSpec users actually value — being *walked through* `why → scenarios → design → tasks`
— is **separable from the artifacts**. It ships as the **authoring skill** (M5 / skill body): the
skill drives the conversation and emits the R9a intent file + plan tasks + graph edges. No folder
state machine, no slash-command lifecycle required to get the assistance.

The proposal-*why* the skill elicits is captured as **memory** nodes (`serves` the intent), which
re-inject at `SessionStart(clear)` (R8) — so the reasoning survives `/clear` and is *better* placed
than OpenSpec's archived `proposal.md` that nobody re-reads.

## 5. Milestone fit

| piece | lands in |
| --- | --- |
| `scenarios` + `design` fields on the intent node (R9a) | **v0**, M2 (intent artifact reader) — small schema add |
| `verified` predicate + reconcile surfacing (R9c) | **v0**, M3 (drift) + M4 (`context`) + M5 (PostToolUse) |
| `supersedes`/`refines` for spec evolution (R9b) | edge exists in v0; full evolution semantics with the **memory milestone** |
| proposal-*why* → memory capture; full guided authoring flow | **memory milestone** / delivery (skill) — not the v0 spine |

Net: R9 is mostly an **enrichment of the v0 intent/plan layer**, not a new subsystem — exactly the
"OpenSpec substance, graph-native ceremony, enforceable completion" combo R9 pins.
