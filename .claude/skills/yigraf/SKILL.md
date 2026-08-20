---
name: yigraf
description: Keep intent, code, and the reasoning behind them in sync when changing code in this repo. Read this skill before driving the CLI — the wrong verb rubber-stamps or destroys a trail. Before you report done, run `yigraf status`: up to date means no drift AND no stale, not the same as no open tasks.
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

Two companions to `context`, for the two questions it structurally cannot answer:
- **Handed an id?** `yigraf show <id>` reads that one node in full — every anchor, the whole `why`,
  and which of its anchors are drifting right now. `context` searches by *meaning*, so an id reaches
  it as a bag of characters and comes back as whatever sits nearest; that reads like an answer and
  isn't one. Drift lines, conflict lines and the session-start manifest all hand you ids.
- **Don't know what to ask for?** Session start lists the *titles* of memories the packet didn't show
  ("Also known"). You can't formulate a query for knowledge you don't know exists, and a fresh session
  doesn't know any of it exists — so skim the titles, then `show` or `context` what looks relevant.

## 0b. Before you say you're done: `yigraf status`
"Up to date" means **no drift AND no stale**. Those are different from "no open tasks", and an empty
`context` packet is evidence of neither — `context` answers the *topic* you asked about, while
`status` is the only surface that reports both counts unconditionally. `yigraf drift` explains any
drift; `yigraf drift --stale` lists the stale completions (that's what `⚠ n stale` counts).

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
- Changed your mind? Never edit a decision in place — `yigraf supersede mem:<id> "<new decision>" --why "<what changed>"`. The old one stays as a rejected alternative, and the new one **inherits the old one's `--concerns`/`--serves` anchors** unless you re-aim with explicit flags — a correction that loses its anchor never resurfaces at the edit hook on the exact symbol it warns about.
- Decision still holds after you edited the code it governs? `yigraf reaffirm mem:<id>` — re-stamps the anchor and clears the drift (the honest counterpart to `supersede`: don't re-`remember`, that duplicates).
- Decision holds but its **subject moved** (the code lives somewhere else now, or the anchor was
  mis-declared at capture)? `yigraf reanchor mem:<id> <old> <new>` moves one anchor with **no
  supersedes trail** — a locus repair is not a mind-change, and filing it as one writes a false entry
  into the most valuable structure in the graph. An anchor that never belonged at all →
  `yigraf unlink mem:<id> <ref>` (works for `concerns` and `grounded_by`).
- A belief about how a file is *used* rather than what it contains ("status.md holds ONLY status")?
  `--governs file:<path>`: surfaces at the edit hook exactly like `--concerns` but carries no content
  hash, so it **never drifts** — a content anchor on a usage policy demands a rubber-stamp reaffirm on
  every edit that obeys it, and a ⚠ that is usually noise trains you to clear it without reading.
- Governing an infra/glue file with **no code symbol** (Dockerfile, buildspec, `*.sh`, `*.json`)? Anchor to the file: `--concerns file:<path>` (whole file), or `--concerns file:<path>:L10-L40` for a line range — region-scoped, so an unrelated edit elsewhere in the file doesn't drift it. `sym:` is for code; `file:` is for everything else. (A whole-file `file:` anchor on *indexed code* is refused — use a symbol or a line range there.)
  Prefer a **line range** only for a file that grows at the END — a log, an append-only record. A
  curated list edited in the middle silently *slides* the range onto unrelated text while leaving it
  syntactically valid, so a later reaffirm re-stamps the wrong region. When the locus is code, anchor
  a **symbol** even if the claim feels like it's about a passage — a symbol moves with its body. For a
  usage policy over a whole document, use `--governs` (§2). And note anchor granularity: a *class*
  anchor hashes member names, not method bodies — a belief about what a method computes must anchor
  the method, or it never resurfaces when that arithmetic changes. If what you're asserting is that
  the file *exists* rather than what's in it, don't cite it as `--evidence` at all.
- The human genuinely chose this (you asked, they answered)? `yigraf attest mem:<id>` records the
  principal's endorsement — a sticky trust floor that ranks it up and holds any later agent
  `supersede` of it *pending* a human. Use it for an elicited preference; never to bless your own call.
- A rule that is load-bearing on **every** task, not just this code? `yigraf remember … --pin` (or
  `yigraf pin mem:<id>`) injects it in full at every session start. Relevance ranking structurally
  cannot reach a rule like that — it resembles no particular topic — so this is the only way it gets
  seen. Keep the set tiny; the budget binds and drops the rest.

A `--concerns` link is **anchored** like `implements`: edit that code later and yigraf surfaces a
"re-verify this decision still holds" reconcile. That's the payoff — the next agent to touch the code
sees the decision and its rationale without reading the history.

**yigraf vs. your host's own memory** — they hold different things, so use both. A yigraf memory is
*retrieved by relevance and anchored to code*: durable but topical, and it is the only one that can
tell you your own edit just invalidated it. Your host's project memory is *loaded verbatim every
session*: small and always-on. Anchored-and-topical → yigraf. Small-and-universal → host memory, or
`--pin`. Writing a code-anchored finding into a flat file loses the drift signal, which is the whole
reason to have yigraf at all.

## 3. Author specs as you plan
- `yigraf intent <slug> -s "The system SHALL …" --scenario "Given …, When …, Then …" [--design "…"]`
- `yigraf plan <slug> -t "<title>" --task "<description>"` then `yigraf link task:<plan>/1 int:<slug>`
  to track the intent.

## 4. The three re-verify signals: drift, stale, conflict
`yigraf context` and the hooks push these at you as you work, so you rarely have to go looking —
**but they are scoped**: the hooks to the file you touched, `context` to the topic you asked about. At
the end of a task that is not enough. `yigraf status` is the authority, and it is the one surface that
reports every count unconditionally (§0b). Each signal has **one** resolving verb; using the wrong one
either rubber-stamps a belief you didn't check or destroys a reasoning trail. Read the claim before
choosing — `yigraf show mem:<id>` prints it in full, and `yigraf drift` now prints it inline.

**Drift** — a live link's anchor no longer matches: soft (the symbol's body changed) or hard (it's
gone), on `implements` (task→code), `concerns` (decision→code), or `grounded_by` (decision→evidence).
A pure rename auto-re-anchors and never surfaces. Re-verify the code still satisfies the thing, then:
- a task's `implements` → `yigraf link task:<id> sym:…` (re-anchors; use this for a symbol that moved
  *and* changed — `link` on the new locus, never unlink-then-link)
- a task's `implements` whose symbol is gone for good, or that was declared wrongly →
  `yigraf unlink task:<id> <target>`. `link` keys by the exact locator, so a re-link after a move
  *appends* rather than replaces; without `unlink` the old entry is drift no verb can clear. This is a
  graph edit, not a mind-change — it leaves no supersedes trail, because the declaration was simply
  never (or is no longer) true.
- a decision's `concerns` that still holds → `yigraf reaffirm mem:<id>` (never re-`remember` — that
  duplicates; never `supersede` unless your mind actually changed)
- a decision's anchor whose subject MOVED → `yigraf reanchor mem:<id> <old> <new>` (a locus repair,
  no supersedes trail); one that never belonged → `yigraf unlink mem:<id> <ref>`
- `grounded_by` → `yigraf reaffirm mem:<id> --grounding empirical --evidence <ref>` if you re-observed
  the evidence — **the `--evidence` re-stamp is what clears it**; without it the command is refused
  rather than exiting clean over a standing ⚠. Otherwise downgrade the claim to `inferred`, or retire
  a dead ref with `yigraf unlink mem:<id> <ref>` — an `empirical` tier whose evidence moved is unearned
- an edit-heavy session that drifted many decisions on one locus → `yigraf reaffirm <sym|file>`
  reaffirms every memory concerning that locus at once. Scoped to a locus you *actually re-verified* —
  there is deliberately no blanket "clear all drift", because that is rubber-stamping.

**Stale completion** — a task marked **done** whose implementing symbol drifted. The completion isn't
false, it's *unverified*: the evidence for "done" moved. Re-verify, then `yigraf link task:<id> sym:…`
to re-anchor — or reopen the task if the change actually regressed it. Never flip it to `todo`
automatically. You won't see these at the edit hook (a closed task must not nag mid-edit); they surface
in `yigraf context`, at SessionStart, and to your principal at the turn boundary. This is what
`status`'s `⚠ n stale` counts — `yigraf drift --stale` lists them. (Plain `yigraf drift` says "No
drift." even when stale items exist; that isn't a contradiction, it's the suppression above.)

**Conflict** — two live beliefs saying nearly the same thing about the same code, never reconciled.
Either the cosine sweep found them, or a principal *nominated* them with `dispute`. **`yigraf
conflicts` lists every open pair** with its shared anchor and the verbs that resolve it — that is what
`status`'s `⚠ n conflict` counts, and it exits non-zero exactly like `drift`, so a count is never a
dead end. Read both sides (`yigraf show <id>`), then:
- they're compatible / one refines the other → `yigraf reconcile mem:<a> mem:<b>`
- one genuinely wins → `yigraf supersede mem:<loser> "<the surviving claim>" --why "…"`
- you can see they conflict but the call isn't yours → `yigraf dispute mem:<a> mem:<b> --why "…"`.
  This *nominates* the pair: it blocks nothing, both stay live, but the open question is now durable
  and actor-stamped so it rides the log to everyone — unlike a swept finding, which is index-derived
  and invisible to anyone without an index. Use it instead of silently moving on.
- **pending** conflict (an agent supersede of a human-attested decision is held, never applied) → you
  cannot clear this one. It needs `yigraf attest` from a human. Surface it and move on. (`attest` is
  also a verb you can *reach for* — see §2 — when the principal has genuinely made the call.)
- same provenance tier with no preferred side → that is not a bug. Two equal-authority beliefs stay an
  open question for the principal rather than being tie-broken. Ask, or `dispute` it.

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
