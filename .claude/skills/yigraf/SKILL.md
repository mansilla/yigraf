---
name: yigraf
description: Use when implementing or changing code in this repo to keep intent, code, and the reasoning behind it in sync. Before starting work, run `yigraf context "<topic>"` to surface governing intents, plans, prior decisions, and drift. After finishing a task, run `yigraf link <task> <symbol>` to name the symbols that implement it, and `yigraf remember` the non-obvious choices you made.
---

# yigraf — the intent↔code spine

This repo is indexed by **yigraf**: one graph over code structure, intents (specs), plans, and the
**memory** of why the code is the way it is — with enforceable links (`implements`, `concerns`)
whose drift is surfaced when code and the thing that governs it diverge. A few rituals keep it
useful — the hooks are a safety net, not a substitute. Forget the exact verbs/flags? `yigraf cheatsheet`
(or `--json`) prints the whole surface — paste-able into a subagent's prompt.

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
- `yigraf remember "<the decision, one line>" --type decision --why "<reasoning>" --serves int:<slug> --concerns sym:<path>#<name> [--rejected "<the alternative + why not>"] [--grounding empirical]`
- `--grounding` records *how sure* you are: `inferred` (default — a reasoned assertion, surfaces as a
  re-verify cue), `docs` (distilled from written rationale), `empirical` (confirmed by a live spike/test/prod
  signal). Upgrade later when evidence lands: `yigraf reaffirm mem:<id> --grounding empirical`.
- A correction or rule → `yigraf note-constraint "<rule>" --concerns sym:<path>#<name> [--rejected "<ruled-out alternative>"]`
  (flagged as a candidate to promote into an enforced check).
- `--serves`/`--concerns` may name a node that doesn't exist *yet* — a forward-reference is accepted with a
  soft warning and a dangling edge (it resolves/anchors once the code or intent lands); it never blocks.
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

## 4. Drift means re-verify
You don't poll for drift — `yigraf context` and the edit hook surface it for you: soft drift (a linked
symbol's body changed) or hard drift (it's gone), for both `implements` (task→code) and `concerns`
(decision→code) links. A pure rename auto-re-anchors. When drift surfaces, re-verify the code still
satisfies the spec/decision, then re-anchor: `yigraf link task:<id> sym:…` for a task's `implements`,
`yigraf reaffirm mem:<id>` for a decision's `concerns` that still holds (or `supersede` it if your mind
changed). After an edit-heavy session that drifted many decisions on one locus, `yigraf reaffirm
<sym|file>` reaffirms **every** memory concerning that locus in one call — scoped to a locus you
actually re-verified (there's no blanket "clear all drift" — that would rubber-stamp). (`yigraf drift`
exits non-zero on drift — that's the commit/CI gate, not something you poll.)

## 5. Evolve an intent (retire or reverse a spec)
Specs change too — but **never hand-edit a superseded intent into place**; use one of two supported paths:
- **Retire / reactivate** (obsolete, no replacement): `yigraf intent <slug> --status archived` (or
  `active` / `satisfied`). The contract text is left untouched — no clobber.
- **Reverse** (the premise turned out false): `yigraf supersede-intent <old-slug> <new-slug> -s "<new
  SHALL contract>" --why "<what changed>"`. This creates the replacement (active), archives the old, and
  writes a real `int→int` **supersedes** edge — so `context` can traverse from the replacement back to
  what it replaced (a bare `superseded_by:` line would be invisible to the graph). The `--why` is
  captured as a memory serving the new intent — the perishable reason the reversal happened.

## 6. Ask the principal only on a real preference-fork
Most forks you resolve by competence — **decide, then `remember` it** (agent-attested); the principal
can endorse it later. Ask a question ONLY on a genuine *preference-fork*: two technically-sound branches
that diverge on something **the principal owns** (a product/policy/priority call you can't settle from
the code). Then:
- Ask **one** question through your host's normal question UI (not a yigraf primitive — yigraf never
  interrupts the user; mem:046).
- Persist the answer as a **human-attested intent** so it's asked once *ever*: `yigraf intent <slug>
  -s "<the principal's answer as a SHALL>"` then `yigraf attest int:<slug>`. A later agent (post-`/clear`)
  sees the human-attested spec and doesn't re-ask.
- `yigraf attest mem:<id>` records the principal endorsing a decision (a sticky trust floor). Attesting a
  memory that pending-supersedes a human-attested node **applies** the held change (resolves the conflict
  a "⚠ Conflict (pending)" line surfaced). Only mark human when the human *actually* chose — the trust
  floor rests on that honesty (you are the scribe, the principal is the source).
- Default when unsure: **do not ask** — decide, `remember`, and let the human `attest` if they care.
