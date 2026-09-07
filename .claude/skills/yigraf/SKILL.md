---
name: yigraf
description: "Keep intent, code, and the reasoning behind them in sync when changing code in this repo. Read this skill before driving the CLI — the wrong verb rubber-stamps or destroys a trail. Before you report done, run `yigraf status`: up to date means no drift, no stale AND no unsettled rename, not the same as no open tasks."
---
<!-- yigraf-skill-version: 1.11.1 -->

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
"Up to date" means **no drift, no stale, and no unsettled rename**. Those are all different from "no
open tasks", and an empty `context` packet is evidence of none of them — `context` answers the *topic*
you asked about, while `status` is the only surface that reports every count unconditionally.
`yigraf drift` explains any drift and lists any pending rename; `yigraf drift --stale` lists the stale
completions (that's what `⚠ n stale` counts); `yigraf gc --apply` settles the renames (`⚠ n rename`).

Settle the renames **first**. It is the only one of the three that stops being fixable: the re-anchor
is a content-hash match, so the next semantic edit to that body destroys it. Drift and stale wait.

**A refusal exits 0, on purpose.** When yigraf declines a recoverable thing — an unresolved locator,
a near-duplicate, a name already taken — it prints how to fix it and exits **0**, because a non-zero
exit trains an agent to stop calling the tool. The consequence is that `$?` cannot tell you a capture
was refused: **read the output**. A capture that succeeded says `Captured mem:<id>`; anything else did
not write.

## 1. Link, then close, when a task is done (the seam)
Two steps, in this order, once per completed task (not per edit):
1. `yigraf link task:<plan>/<n> sym:<path>#<name>` — names what the task built and anchors it to the
   symbol's current content.
2. `yigraf close task:<plan>/<n>` — marks it done by writing the checkbox in the plan file.

**Closing is a verb, not a hand-edit.** `close` refuses a task that implements nothing, so "done" and
"anchored" land together — a completion with no anchor can never go STALE, which is the whole point of
recording it. Use `--force` only when the task genuinely shipped no symbol, `--reopen` to undo.
`yigraf tasks [<plan>] [--open|--done|--stale]` lists what is outstanding without depending on a
semantic query matching; `yigraf plan <slug> --append-task "…"` adds work to a live plan.

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
  `yigraf unlink mem:<id> <ref>` (works for `concerns` and `grounded_by`). Reanchoring onto a locus the
  node **already carries** cannot move anything, so it drops `<old>` and says so — that is a removal,
  and no verb adds a `concerns` anchor back.
- Decision holds but what you WROTE about it is wrong (a `--why` your shell mangled, a typo in the
  claim)? `yigraf amend mem:<id> --why "<the reasoning, stated right>"` repairs the record, also with
  no supersedes trail. It reports a NEW id — a memory id is a hash of its own statement/why/rejected —
  and it refuses on a node something else already names or that has been pushed, where the honest verb
  is `supersede`. Don't reach for it if your mind changed at all: it rewrites rather than keeping both.
- Composing a long `--why`? Write it to a file and pass `--why-file <path>` instead. A shell rewrites
  backticks, `$vars` and `!history` inside a quoted string and yigraf cannot tell — a mangled `--why`
  is unrecoverable prose, not a syntax error — and a refused command then costs a path to re-send
  rather than the whole argument. Every capture verb takes it.
- The `--why` has to CARRY the argument, not point at where it is. `--why "see mem:<id>"`, or "the
  belief is unchanged and the argument is in the node this supersedes", defers a reasoning nobody ever
  wrote — in the field four such pointers all resolved to nodes with no argument at all, so the trail
  was load-bearing and empty at the same time. Capture follows the pointer and refuses when it lands on
  nothing; citing a node that *does* argue its case is fine and says nothing. Found one already in the
  store (`yigraf show` reports `⚠ Hollow Why`)? `yigraf amend mem:<id> --why "<the argument>"`.
- A belief about how a file is *used* rather than what it contains ("status.md holds ONLY status")?
  `--governs file:<path>` (or `file:<path>#<section>`): surfaces at the edit hook exactly like
  `--concerns` but carries no content
  hash, so it **never drifts** — a content anchor on a usage policy demands a rubber-stamp reaffirm on
  every edit that obeys it, and a ⚠ that is usually noise trains you to clear it without reading.
- Governing an infra/glue file with **no code symbol** (`Dockerfile`, a buildspec, `*.json`, `*.yml`)? Anchor to the file: `--concerns file:<path>` (whole file), or `--concerns file:<path>:L10-L40` for a line range — region-scoped, so an unrelated edit elsewhere in the file doesn't drift it. `sym:` is for code; `file:` is for everything else. (A whole-file `file:` anchor on *indexed code* is refused — use a symbol or a line range there.)
  **A shell script is not in that list**: `.sh`/`.bash` are indexed as code by default, so
  `file:deploy.sh` is refused by the rule in the sentence above. Anchor one of its functions
  (`sym:deploy.sh#rollback`). A script with no functions has no symbol to anchor, and a line range is
  the wrong tool for a file that gets edited in the middle — so either give the claim a function to
  point at, or make it a `--governs file:deploy.sh` policy (§2), which is about how the file is *used*
  and carries no hash to be refused over.
  **A claim about one part of a markdown document takes `--concerns file:<path>#<section>`** — the
  heading's slug (case-folded, every run of other characters collapsed to one `-`). That is the one
  sub-file anchor addressed *by name*: it survives a rewrap, a re-level, an edit in a subsection, and
  any insertion above it, and a heading **rename** re-anchors instead of drifting. Get the slug wrong
  and yigraf lists the real ones.
  A **line range** is addressed by *position*, so use it only where nothing is inserted above the
  region — a log, an append-only record. Edit a curated list in the middle and the range silently
  *slides* onto unrelated text while staying syntactically valid: a later reaffirm re-stamps the wrong
  region, after which a rewrite of what you actually meant drifts **nothing**. In markdown, reach for
  `#<section>`; in code, anchor a **symbol** even if the claim feels like it's about a passage — a
  symbol moves with its body. For a usage policy over a whole document or one section, use `--governs`
  (§2). And note anchor granularity: a *class* anchor hashes member names, not method bodies — a
  belief about what a method computes must anchor the method, or it never resurfaces when that
  arithmetic changes. If what you're asserting is that the file *exists* rather than what's in it,
  don't cite it as `--evidence` at all.
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
  to track the intent. Add to a live plan with `--append-task`; never hand-edit the artifact.

## 4. The four re-verify signals: drift, stale, conflict, unsettled rename
`yigraf context` and the hooks push these at you as you work, so you rarely have to go looking —
**but they are scoped**: the hooks to the file you touched, `context` to the topic you asked about. At
the end of a task that is not enough. `yigraf status` is the authority, and it is the one surface that
reports every count unconditionally (§0b). Each signal has **one** resolving verb; using the wrong one
either rubber-stamps a belief you didn't check or destroys a reasoning trail. Read the claim before
choosing — `yigraf show mem:<id>` prints it in full, and `yigraf drift` now prints it inline.

**Drift** — a live link's anchor no longer matches: soft (the symbol's body changed) or hard (it's
gone), on `implements` (task→code), `concerns` (decision→code), or `grounded_by` (decision→evidence).
A pure rename is not drift — it re-anchors itself — but it is not free either; it is the fourth
signal below. Re-verify the code still satisfies the thing, then:
- a task's `implements` → `yigraf link task:<id> sym:…` (re-anchors; use this for a symbol that moved
  *and* changed — `link` on the new locus, never unlink-then-link)
- a task's `implements` whose symbol is gone for good, or that was declared wrongly →
  `yigraf unlink task:<id> <target>`. `link` keys by the exact locator, so it replaces the old entry
  only where yigraf has *proved* the move (see the rename signal below) and appends otherwise; a move
  yigraf could no longer prove — because you edited the body too — leaves an old entry `unlink` is the
  only way out of. This is a graph edit, not a mind-change — it leaves no supersedes trail, because the
  declaration was simply never (or is no longer) true.
- a decision's `concerns` that still holds → `yigraf reaffirm mem:<id>` (never re-`remember` — that
  duplicates; never `supersede` unless your mind actually changed). **Read the claim before you
  reaffirm it.** Nothing in the command proves you did, and a clearing drift count feels like progress
  either way — so past a few single-id reaffirms in a row yigraf asks for
  `--verified "<what you actually re-read>"`, one line, recorded locally. If you find you cannot write
  that line, you did not re-verify it; if the claim did *not* survive the reading, the verb is
  `supersede`.
- a decision's anchor whose subject MOVED → `yigraf reanchor mem:<id> <old> <new>` (a locus repair,
  no supersedes trail); one that never belonged → `yigraf unlink mem:<id> <ref>`. A botched *record*
  rather than a moved anchor (garbled why, typo in the claim) → `yigraf amend mem:<id> --why "…"`
- `grounded_by` → `yigraf reaffirm mem:<id> --grounding empirical --evidence <ref>` if you re-observed
  the evidence — **the `--evidence` re-stamp is what clears it**. A bare `yigraf reaffirm mem:<id>`
  does *not*: it succeeds, exits 0, re-stamps the `concerns` anchors, and then prints that the
  grounds-drift still stands. **A clean exit is not proof you cleared it** — read the output, not
  `$?`. Otherwise downgrade the claim to `inferred`, or retire a dead ref with
  `yigraf unlink mem:<id> <ref>` — an `empirical` tier whose evidence moved is unearned.
  Two things about grounds-drift that no message will tell you, because both are *silences*:
  **soft** `grounded_by` drift is only ever shown on an `empirical` belief. Once the tier is
  `inferred` (the capture default) or `docs`, the honest downgrade has already done what the warning
  exists to trigger, so yigraf stops nagging. The corollary is the trap: an `--evidence` ref on a
  non-`empirical` belief **can go stale without a word**. Hard drift — the ref is gone entirely —
  still surfaces at every tier.
- an edit-heavy session that drifted many decisions on one locus → `yigraf reaffirm <sym|file>`
  reaffirms every memory concerning that locus at once. Scoped to a locus you *actually re-verified* —
  there is deliberately no blanket "clear all drift", because that is rubber-stamping. A whole-file
  locus **covers the section anchors inside it**: `yigraf reaffirm file:docs/design.md` reaches a
  belief anchored to `file:docs/design.md#rules`, and names each section it touched. (It is a no-op on
  every section that did not change — which is exactly what the section anchor bought you.) It does
  *not* work the other way: naming a section never reaches the whole file.

**Unsettled rename** — a symbol or heading you renamed *moved the subject, not the belief*: yigraf
matches it by content hash and re-anchors the edge, so nothing drifts and nothing is lost. But that
match is re-derived from the **body** on every build, and the artifact still names the locator the
subject left. Edit that body before writing the move down and the rescue is gone: hard drift on a
locator that will never resolve, with no record anywhere of where the subject went. So settle it while
it is still free — `yigraf gc --apply` settles every pending one at once, or name the new locus
yourself (`yigraf link task:<id> sym:…` / `yigraf reanchor mem:<id> <old> <new>`). Only the locator
moves: the anchor hash and the commit it was stamped at are untouched, so no claim or completion is
re-dated. This is the one signal with an expiry, which is why the edit hook interrupts for it, why it
is counted on `yigraf status` as `⚠ n rename`, and why it is the first thing to settle before you
report done. `yigraf drift` lists each pending one; `yigraf gc` renders the full report.

Note what "edit that body" means: **semantically** edited. yigraf normalizes comments and formatting
away, so renaming a symbol *and* adding a comment to it is still a pure rename and still rescuable.
Renaming it and changing one expression is not.

**Stale completion** — a task marked **done** whose implementing symbol drifted. The completion isn't
false, it's *unverified*: the evidence for "done" moved. Re-verify, then `yigraf link task:<id> sym:…`
to re-anchor — or `yigraf close task:<id> --reopen` if the change actually regressed it. Never flip
it to `todo`
automatically. You won't see these at the edit hook (a closed task must not nag mid-edit); they surface
in `yigraf context`, at SessionStart, and to your principal at the turn boundary. This is what
`status`'s `⚠ n stale` counts — `yigraf drift --stale` lists them. (Plain `yigraf drift` says "No
drift." even when stale items exist; that isn't a contradiction, it's the suppression above.)

**Task reconcile** — not a fifth signal but the one prompt that means *good* news, and it is worded
unlike the rest, so it is easy to read as a warning: `⚠ task:<id> is open but its implementing
symbol(s) exist and are current`. It fires in `context` and at the edit hook when a task you never
closed is anchored to code that is present and un-drifted — i.e. the work looks shipped and the
checkbox disagrees. That is the natural trigger for **`yigraf close task:<id>`**. If the work is *not*
done, nothing is wrong: the anchor is a forward-declaration and the prompt is noise you can ignore.

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

(`yigraf drift` exits non-zero on **soft/hard drift only** — that's the commit/CI gate, not something
you poll. `yigraf conflicts` gates the same way on conflicts. A **pending rename** and a **stale
completion** exit 0 on every command, so they pass a gate silently: read the output, or gate on
`yigraf status --json`, which carries all four counts. That the rename is the one let through matters —
it is the signal §0b says to settle first, because it is the only one that stops being fixable, and the
commit boundary is the last moment before the edit that ends the rescue.)

## 5. Evolve an intent (retire or reverse a spec)
Specs change too — but **never hand-edit a superseded intent into place**; use one of two supported paths:
- **Retire / reactivate** (obsolete, no replacement): `yigraf intent <slug> --status archived` (or
  `active` / `satisfied`). The contract text is left untouched — no clobber.
- **Reverse** (the premise turned out false): `yigraf supersede-intent <old-slug> <new-slug> -s "<new
  SHALL contract>" --why "<what changed>"`. This creates the replacement (active), archives the old, and
  writes a real `int→int` **supersedes** edge — so `context` can traverse from the replacement back to
  what it replaced (a bare `superseded_by:` line would be invisible to the graph). The `--why` is
  captured as a memory serving the new intent — the perishable reason the reversal happened.
