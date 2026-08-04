---
name: yigraf
description: Use when implementing or changing code in this repo to keep intent, code, and the reasoning behind it in sync. Before starting work, run `yigraf context "<topic>"` to surface governing intents, plans, prior decisions, and drift. After finishing a task, run `yigraf link <task> <symbol>` to name the symbols that implement it, and `yigraf remember` the non-obvious choices you made.
---

# yigraf — the intent↔code spine

This repo is indexed by **yigraf**: one graph over code structure, intents (specs), plans, and the
**memory** of why the code is the way it is — with enforceable links (`implements`, `concerns`)
whose drift is surfaced when code and the thing that governs it diverge. A few rituals keep it
useful — the hooks are a safety net, not a substitute.

## 0. Orient before you touch code (always)
Run `yigraf context "<what you're about to work on>"`. **This is the one command you need to read the
graph** — the governing requirement(s), the implementing symbols (signature by default, full source
when configured), the open tasks, the prior **decisions and their *why***, and any **drift** all come
back through it, as a token-cheap map. Don't reach for a separate query or drift tool. If a spec
already covers your change, refine it; don't duplicate. If a decision already settled the question,
follow it (or `supersede` it on purpose).

## 1. Link when a task is done (the seam)
When you finish a task, name the symbols that implement it:
`yigraf link task:<plan>/<n> sym:<path>#<name>` — this anchors the link to the symbol's current
content. Linking once per completed task (not per edit) is enough.

## 2. Capture the *why* (decisions & constraints)
When you make a non-obvious choice — picked an approach over a named alternative, set a constraint,
worked around something — persist the reasoning that `/clear` would otherwise lose. One line of why
plus the rejected option is enough; capture at the *conclusion*, not mid-thinking.
- `yigraf remember "<the decision, one line>" --type decision --why "<reasoning>" --serves int:<slug> --concerns sym:<path>#<name> [--rejected "<the alternative + why not>"]`
- A correction or rule → `yigraf note-constraint "<rule>" --concerns sym:<path>#<name>` (flagged as a
  candidate to promote into an enforced check).
- Changed your mind? Never edit a decision in place — `yigraf supersede mem:<id> "<new decision>" --why "<what changed>"`. The old one stays as a rejected alternative.
- Decision still holds after you edited the code it governs? `yigraf reaffirm mem:<id>` — re-stamps the anchor and clears the drift (the honest counterpart to `supersede`: don't re-`remember`, that duplicates).
- Governing an infra/glue file with **no code symbol** (Dockerfile, buildspec, `*.sh`, `*.json`)? Anchor to the file: `--concerns file:<path>` (whole file), or `--concerns file:<path>:L10-L40` for a line range — region-scoped, so an unrelated edit elsewhere in the file doesn't drift it. `sym:` is for code; `file:` is for everything else. (A whole-file `file:` anchor on *indexed code* is refused — use a symbol or a line range there.)

A `--concerns` link is **anchored** like `implements`: edit that code later and yigraf surfaces a
"re-verify this decision still holds" reconcile. That's the payoff — the next agent to touch the code
sees the decision and its rationale without reading the history.

## 3. Author specs as you plan
- `yigraf intent <slug> -s "The system SHALL …" --scenario "Given …, When …, Then …" [--design "…"]`
- `yigraf plan <slug> -t "<title>" --task "<description>"` then `yigraf link task:<plan>/1 int:<slug>`
  to track the intent.

## 4. The three re-verify signals: drift, stale, conflict
You never poll for these — `yigraf context` and the hooks surface them. Each has **one** resolving verb;
using the wrong one either rubber-stamps a belief you didn't check or destroys a reasoning trail.

**Drift** — a live link's anchor no longer matches: soft (the symbol's body changed) or hard (it's
gone), on `implements` (task→code), `concerns` (decision→code), or `grounded_by` (decision→evidence).
A pure rename auto-re-anchors and never surfaces. Re-verify the code still satisfies the thing, then:
- a task's `implements` → `yigraf link task:<id> sym:…` (re-anchors)
- a decision's `concerns` that still holds → `yigraf reaffirm mem:<id>` (never re-`remember` — that
  duplicates; never `supersede` unless your mind actually changed)
- `grounded_by` → `yigraf reaffirm mem:<id> --grounding empirical` if you re-observed the evidence,
  otherwise downgrade the claim to `inferred` — an `empirical` tier whose evidence moved is unearned
- an edit-heavy session that drifted many decisions on one locus → `yigraf reaffirm <sym|file>`
  reaffirms every memory concerning that locus at once. Scoped to a locus you *actually re-verified* —
  there is deliberately no blanket "clear all drift", because that is rubber-stamping.

**Stale completion** — a task marked **done** whose implementing symbol drifted. The completion isn't
false, it's *unverified*: the evidence for "done" moved. Re-verify, then `yigraf link task:<id> sym:…`
to re-anchor — or reopen the task if the change actually regressed it. Never flip it to `todo`
automatically. You won't see these at the edit hook (a closed task must not nag mid-edit); they surface
in `yigraf context`, at SessionStart, and to your principal at the turn boundary.

**Conflict** — two live decisions anchored to the same code saying nearly the same thing, never
reconciled. Read both, then:
- they're compatible / one refines the other → `yigraf reconcile mem:<a> mem:<b>`
- one genuinely wins → `yigraf supersede mem:<loser> "<the surviving claim>" --why "…"`
- **pending** conflict (an agent supersede of a human-attested decision is held, never applied) → you
  cannot clear this one. It needs `yigraf attest` from a human. Surface it and move on.
- same provenance tier with no preferred side → that is not a bug. Two equal-authority beliefs stay an
  open question for the principal rather than being tie-broken. Ask.

(`yigraf drift` exits non-zero on drift — that's the commit/CI gate, not something you poll.)

## 5. Evolve an intent (retire or reverse a spec)
Specs change too — but **never hand-edit a superseded intent into place**; use one of two supported paths:
- **Retire / reactivate** (obsolete, no replacement): `yigraf intent <slug> --status archived` (or
  `active` / `satisfied`). The contract text is left untouched — no clobber.
- **Reverse** (the premise turned out false): `yigraf supersede-intent <old-slug> <new-slug> -s "<new
  SHALL contract>" --why "<what changed>"`. This creates the replacement (active), archives the old, and
  writes a real `int→int` **supersedes** edge — so `context` can traverse from the replacement back to
  what it replaced (a bare `superseded_by:` line would be invisible to the graph). The `--why` is
  captured as a memory serving the new intent — the perishable reason the reversal happened.
