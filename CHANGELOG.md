# Changelog

All notable changes to yigraf are recorded here. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/); yigraf uses
[semantic versioning](https://semver.org/).

## [1.12.1] — 2026-09-12

**1.12.0 took a deliberate loss and took it quietly. The loss stands; the quiet does not.**

Retiring an undeclared live `preamble:` key is right for the population it was written for — a repo
`init`ed at 1.9.0–1.10.0, carrying a copy that silently stopped tracking the CLI. But a hand-pin made
before `preamble_pinned:` existed produces the *same bytes*, and for that reader the same write is a
choice being overridden. 1.12.0 printed one line for both. A reader who had pinned deliberately got no
signal at all that anything of theirs had changed, which turned a bounded, recoverable loss into a
silent one — the shape of failure this whole line of work exists to remove.

Nothing was ever destroyed, and that is what makes a message a complete remedy rather than an apology:
the retired text is byte-identical to what the CLI ships and it stays in the file, commented out. The
defect was only that no one was told.

* **The ambiguous case says so.** `refresh_preamble` now reports *which* class it retired —
  `PREAMBLE_COPY_SUPERSEDED` (provably ours: only an `init` through 1.8.0 could have written it) or
  `PREAMBLE_COPY_CURRENT` (two possible histories, and the file cannot say which). A superseded copy
  still gets one line. A copy of the current text gets a ⚠ naming both histories, and the one-command
  recovery: uncomment the text that is still sitting there, together with `preamble_pinned: true`, and
  no release touches it again. A bool could not carry that difference, which is why the caller could
  not say it.
* **`install --plan` names the one committed file `install` touches.** The dry-run returns before the
  retirement by construction — inspect-only must write nothing — and the side effect was that the one
  preview a cautious reader has said nothing about the only git-tracked write in the whole installer.
  It now leads with it, under its own ⚠ heading, and tells you how to opt out **before** the write
  rather than how to recover after. `--plan --json` carries it too, for an orchestrator deciding
  whether to apply.

What is unchanged: the retirement itself, the marker, the widened match, and the reasoning in
[1.12.0] below. This does not reverse that decision — it makes it visible to the one reader for whom
it is a cost. (mem:4b41240905ebb217)

## [1.12.0] — 2026-09-11

**Three claims the store could not retract, and a byte-identity that had two victims on opposite
clocks.** All four from the 1.11.1 field report (feedback-v9).

### A preamble pin now declares itself, and an undeclared copy is retired

`preamble_behind` matched a preamble byte-exactly against what yigraf once shipped, and justified that
as *"proof the text in the file is ours rather than the team's."* Byte-exactness proves where text came
from; **it cannot prove how the copy got into the file.** `init` minting the key and a human running
the documented *"uncomment the block below to pin your own"* produce identical bytes. One predicate,
two victims, on opposite clocks:

* a **deliberate pin** of today's text would be silently deleted by the first release that amends the
  default — the pin ages into `SUPERSEDED_SESSION_PREAMBLES` and the next `install` rewrites it;
* and *until* that release, every repo `init`ed at **1.9.0–1.10.0** was invisible to the remedy. The
  default text last changed at 1.9.0 and minting stopped at 1.11.0, so those repos carry a live key
  matching the *current* default — `preamble_behind` was `False` and they were never migrated, keeping
  the exact two-copy hazard 1.11.0 exists to remove. Only 1.4.0–1.8.0 repos were reachable.

No ordering of the tuple separates them, because they are the same bytes. So provenance moves to where
the human's own action already is:

* **`preamble_pinned: true` ships inside the commented block**, so the one uncomment that takes
  ownership also declares it. `preamble_behind` and `refresh_preamble` skip any file carrying it,
  whatever the bytes say — and it outlives every later amendment, which byte-identity could not. It is
  the discipline `installed_skill_version`'s stamp already applies; the gap was only that the preamble
  had no stamp to read.
* **The match widens to every default we ever shipped, the current one included**, which reaches the
  stranded 1.9.0–1.10.0 population at last. `SUPERSEDED_SESSION_PREAMBLES` is unchanged and its
  invariant still holds — the current text must never be listed *there*, or a stale entry nags forever.
* **`preamble_behind` now reads `config.yaml` as committed** (`committed_config`) instead of taking a
  merged config, and that is load-bearing: `load_config` fills an absent `preamble:` from the default,
  so in a merged mapping a healthy 1.11+ file is indistinguishable from the stranded one. The file is
  the only place the difference exists.

⚠ **The cost, taken deliberately.** A pin made by hand *before* this release carries no marker and is
retired like a mint. That is a real choice being overridden, it is bounded to one transition, and it
is one uncomment from being re-made — with its declaration this time. Leaving the tuple alone would
instead strand the 1.9.0–1.10.0 repos permanently. Bounded loss over unbounded.

⭐ **The guard for this was already in the suite and could not fail**, which the field found by reading
the sdist: `test_a_current_preamble_pinned_by_hand_is_left_alone` built its fixture from
`DEFAULT_SESSION_PREAMBLE` **at run time**, while `test_the_current_default_is_not_also_listed_as_superseded`
guarantees that text is never in the tuple. The fixture moved with every release; a team's committed
file does not. `tests/test_feedback_v9.py` carries the field's own replacement, with the pinned bytes
**frozen as a literal** — their fix, their test, kept whole.

### `link` retires the `unanchored:` marker

`mark_task_unanchored` shipped a complete `unanchored=False` branch that **no CLI call site reached**,
so nothing cleared the marker `close --force` writes — verified across eleven verbs, `link` and
`unlink` and `--reopen` among them. Two states followed, and `close`'s own output invites the first:
it prints *"if the work later grows a symbol, `yigraf link` re-earns that."*

* **`--force` then `link` minted a state `close` refuses to write** — `unanchored:` *and* an
  `implements` edge — in which the shipped claim "an unanchored completion can never go STALE" is
  false: edit the anchored symbol and it reports STALE.
* **`--force` → `link` → `unlink` left the task permanently exempt** from `_capture_gaps`, which
  checks the marker *before* it looks for an implements edge. Two tasks in identical end states, and
  only the never-forced one was reported.

`link`'s `sym:`/`file:` branch now clears it, and says so. Confined to that branch: `link <task>
int:<slug>` declares that the task *tracks* an intent, which asserts nothing about whether it
implements a symbol. The marker is a claim about the task **now** — which is how `_capture_gaps` reads
it — not a historical fact about how it was closed.

`--force`'s help string said *"an unanchored completion can never go stale"*, the claim above
falsifies, and the cheatsheet renders it verbatim. It now says what `--force` actually does: it
**records** the choice. The MCP `close` tool description, accurate for 1.10.0 and silent since, says it
too.

### `reaffirm --evidence` says which list it wrote to

On a belief with no `grounded_by` list, `--evidence` reported *"grounds-drift cleared"* — describing an
event that never happened, on a node that had no grounds-drift to clear. A caller who arrived from the
`reanchor`/`unlink` drop ⚠ — whose own text correctly says *no verb adds a `concerns` anchor back* —
read that as compliance, and the locus had in fact landed on `grounded_by`, where it means the opposite
thing: evidence **for** the claim rather than code the claim **governs**, so it no longer surfaces as a
governed locus. The success line now claims cleared drift only when there was drift, and names the list
when a locus lands on it for the first time on a node that also carries `concerns` anchors.

### The migration says how to take the preamble back

`refresh_preamble` splices the `preamble:` key and nothing else — the right scope for a text write into
a committed file, and the reason a migrated ≤1.8.x config still reads *"Yours to rewrite"* directly
above a now-**commented-out** block, with the word "uncomment" nowhere in it. A reader who follows that
prose edits the text where they find it, leaves it commented, and commits a house rule every session
silently ignores. Widening the splice would be a much larger unrequested write, so the installer says
it instead, at the moment of the migration.

Not changed: the capture gap is still unnamed in the skill's §4 *"four re-verify signals"*. The runtime
⚠ names the exact command with the exact task id, fires uncapped at every SessionStart, and works on a
task that is already done — it is very nearly the whole channel, and a fifth entry costs the context
budget at every session start (design law #2). The two prose surfaces that were *wrong* rather than
merely absent are fixed above.

## [1.11.1] — 2026-09-07

**`close --force` was the escape hatch the refusal named, and taking it left the warning standing
forever.**

`close` refuses a task that implements nothing, and its refusal offers `--force` for the case where
the work genuinely shipped no symbol — a doc, a config, a decision. `--force` then wrote *nothing*: it
moved the checkbox and stopped. So "closed with no anchor, on purpose" and "closed and never linked"
were the same state on disk, and the capture-gap ⚠ — which fires on exactly that state — went on
reporting the completion at every SessionStart with no verb able to clear it. An advisory signal that
cannot be resolved by the verb it points at is not advice; it is trained noise, costing the agent's
attention budget every session against design law #4. Measured on yigraf's own graph: 2 of 158
completions, standing since feedback-v3 and feedback-v4.

* **`--force` records the choice.** A top-level `unanchored:` list in the plan file names the tasks
  that deliberately implement nothing, and `_capture_gaps` skips them. Not a key inside the task's
  `edges` spec: `edges` holds edges and this asserts the *absence* of one, and `remove_edge_from_plan`
  collects a task's spec once its last edge is gone — a marker parked there would be swept away by an
  unrelated `unlink`, and its silent loss would look exactly like the nag returning by itself.
* **`--force` is reachable as a repair.** The warning fires on a task that is by definition already
  done, where `close` answered "already done" and did nothing. It now records the marker there, so the
  guidance is followable from where the reader actually is.
* **The gap line names both exits.** It offered only `yigraf link`, and that exit does not always
  exist: both of yigraf's own gaps were prose living in a module-level constant (`hooks.py`
  `_SKILL_BODY`, `memory.py` `GROUNDINGS`), which tree-sitter does not index — so `link` refuses the
  only locus that would be honest. Anchoring such prose to a `file:…:L44-L56` range was rejected as
  silently wrong: a range is addressed by position, so any insertion above it slides it onto unrelated
  text and a later `reaffirm` re-stamps the wrong region.

The marker is written into the task's attrs and its revision **only when true**, so the 156 anchored
completions keep the exact revision ids they had and no phantom divergence is minted for a teammate to
resolve. What is unchanged: an unanchored completion still can never go STALE. That is the price of the
anchor it does not have, and it is the reason the guard exists — what is new is only that yigraf now
knows the absence was a choice rather than decay. (mem:8bb0997b54094ec7)

## [1.11.0] — 2026-09-06

**`⬆ preamble` was a nudge with no remedy but a paste, and every release minted more of them.**

1.9.0 taught the statusline to report a stale committed session preamble (feedback-v6 F#1). It
reported accurately and could do nothing else: `init` spliced the preamble into the repo's *committed*
`yigraf/config.yaml` as a live key, the file value wins at read time, and so upgrading the CLI reached
no repo that already existed. The remedy the notice named was "replace `session_start.preamble:` with
the current text" — by hand, per repo, forever. That is a chore that scales with the number of users,
which is another way of saying it does not get done; and because each release that amends the default
strands every repo initialized before it, the population needing the chore only grew.

Three changes, because the hazard has a source, a backlog, and a signpost:

* **`init` no longer mints a copy.** The preamble is written into `yigraf/config.yaml` **commented
  out**, so the key is absent and falls through to the text the installed CLI ships — upgrade yigraf
  and the rules move with it, with no second copy anywhere to go stale. The full text still rides
  along in the file, because a knob nobody can see is a knob nobody uses: reading the config is how a
  team learns the channel exists. Uncommenting is exact-reversible (strip `# ` and you have the block
  scalar the file used to carry), so owning the preamble stays one editor command — and from that
  point the rules are yours, never touched and never nudged again.
* **Every `install` verb retires an existing stale copy**, replacing it with the same commented block a
  fresh `init` writes — so a migrated repo lands exactly where a new one starts, rather than having
  today's text pasted back as a live key that goes stale again next release. It runs under the *same*
  byte-exact guard that raises the nudge: only a preamble byte-identical to one yigraf itself once
  shipped is touched, which is proof the text in the file is ours and not the team's. A rewritten
  preamble, a hand-pinned current one, and `preamble: ""` are all left alone.
* **The notice names the command.** `⬆ preamble` now says `yigraf install`.

This partially supersedes the 1.9.0 reasoning, which rejected "rewriting config.yaml on upgrade (it is
a committed, user-owned file)". That rejection still holds for what it actually covered — nothing here
writes on a read path, in a hook, or under `install --plan`, and `status` continues to report without
acting. What changed is the recognition that a byte-exact match against text we shipped is evidence
the *content* is not user-owned at all, whatever the file is; combined with an explicit `install`, the
write is the user asking yigraf to bring its own surfaces current, not yigraf editing their work.

The splice is textual rather than a YAML round trip, which would discard every comment in the file —
and that file is mostly comments, the only documentation of what each knob does. Where a `preamble:`
key cannot be located unambiguously, `refresh_preamble` declines and leaves the nudge standing: a
persistent notice costs one release, a wrong edit to a committed file costs trust.

Amending the default preamble remains a two-line change — append the outgoing text to
`SUPERSEDED_SESSION_PREAMBLES` in the same commit, or repos still carrying it go unreported. Tests now
pin both directions of that tuple.

## [1.10.0] — 2026-09-03

**An unset shell variable could overwrite a live plan, and the tool printed "Created".**

`yigraf plan ""` wrote `yigraf/plans/active/.md` — a dotfile with an empty id — and reported success.
That plan was *real*: it answered to the slug `.md`, took `link`, `--append-task` and `close`. Run the
same command again with the variable still unset and the second one silently replaced the first —
title, tasks, and the `edges:` block with its stamped `implements` anchor, `anchor_algo` and
`stamped_at`. Afterwards `task:.md/1` named a different task than it had a moment earlier, which
`plan`'s own docstring says cannot happen ("task numbers … are never reused, so an id already recorded
on a `link` edge cannot come to mean a different task"). It is the first data-loss path the field has
reported, and it needed one unset variable in a shell script to reach.

Two edits, because the two halves fail independently:

* **The empty string is refused**, on every verb that composes a slug into a path. It used to pass the
  guard twice over: `not value` short-circuited out, and `_PATH_SHAPED` does not match `""` either.
  The obvious one-liner is a regression the field flagged before we could ship it — `_require_slug` is
  also called from `tasks` with `None`, where `None` means *every plan*, so refusing falsy values
  breaks `yigraf tasks` with no argument. `None` returns; `""` gets its own refusal, naming the unset
  variable, at exit 0 like every other recoverable condition (design law #1).
* **`plan`'s anti-clobber check is keyed on the resolved path**, which is the half that actually stops
  the loss. It compared a glob's `path.stem`, and `Path(".md").stem` is `".md"`, not `""` — so the
  plan failed to find *itself*. `intent` and `supersede-intent` were never exposed because they test
  `dest.exists()`; this is them. The check no longer depends on the guard catching every shape that
  can round-trip badly.

The exit code stays 0. A refusal that writes nothing is not a tool failure, and the field agrees:
"a non-zero exit trains an agent to stop calling the tool." (feedback-v7 G#1)

**`section_offer_margin` did nothing on a whole class of document, and 1.9.0's notes claimed the
opposite.** The margin compares the winner against the runner-up — so where a document has exactly
*one offerable* section there is no runner-up, the comparison never runs, and the knob is skipped
entirely: `1e9` offered as readily as `2.0`, with nothing between inert and off. That is exactly the
shape 1.9.0 said was exempt by construction (`coding-conventions.md`: a title plus one `##`), and the
field measured that it was not — the test was written on the raw section count, which counts the
title too.

The exemption is now on **offerable** sections, which is what it always meant. An offer is a *choice*
— "this section, more than the others" — and one candidate is not a choice; it is also the case where
narrowing buys least, since "the file minus its preamble" is barely a narrowing. So the claim 1.9.0
made is now true, and the knob is live everywhere the offer can fire. A runner-up that scores *zero*
still passes at every margin, and that is the definition rather than a hole: the ratio is unbounded,
and it is the strongest signal the scorer produces. (feedback-v7 G#2)

**The default stays 2.0, and the reason is that the number that should set it did not exist.** The
field measured the other half of that finding on their own store — at `2.0` the offer fires on 2 of
12 eligible captures, at `1.0` on 12 of 12, and the suppressed cases run 1.14× to 1.74× the runner-up,
nowhere near ties. They also observed zero uptake: 12 of 12 anchors chosen whole-file by an
Opus-class agent with the skill provably in context, which is a measurement about where guidance has
to sit rather than about carelessness. But a recall curve is not an accept rate, and the honest
version of "should the default be lower" needs to know how often an offer is *right*, which nothing
recorded. So:

**The offer keeps a ledger.** `yigraf/.local/section-offers.json` — machine-local, gitignored, never
the graph, the same shape as `reaffirms.json` (design law #6). One row per whole-file markdown anchor
*considered*, carrying the candidate slug and **both scores**, written **before** the margin gate:

```json
{"at": 1788476756.6, "mem": "mem:d351…", "ref": "file:docs/d.md",
 "candidate": "z-band", "top": 8.09, "runner_up": 0.0, "offered": false}
```

Before the gate, because a row written where the offer is *printed* logs only what the margin let
through — the half that cannot re-fit a threshold. With both scores stored, one window re-scores
offline at every candidate margin through `sectionfit.Fit.wins_by`, the same gate the offer itself
uses, so a stored row and a live offer can never disagree. Acceptance needs no second record: it is
"does that memory now carry that anchor". `best_section` is unchanged as a verdict; the scoring is
split out into `section_fit`. (feedback-v7 G#4)

**`reanchor` reported a removal as a move.** Where the destination is already on the node there is
nothing to move onto it, so the old anchor is dropped — and the success line printed `old ⇒ new`
anyway, at exit 0, with no second sentence and the anchor count going 2 → 1. The removal is
defensible; the report was not, on a node no verb can add a `concerns` anchor back to. It now says
what it did, names the `unlink` that produces the same end state, and says the recovery is a
frontmatter edit. Confirmed by the field on `concerns` and `grounded_by`, `file:` and `sym:` alike.

The route in is closed at the other end too: the offer never hands over a `reanchor` onto a section
the node already carries — the fifth exemption, and the one that was missing. (feedback-v7 G#3)

**And the enumeration that claimed five copies had six.** F#1 made one source for "up to date means no
drift, no stale AND no unsettled rename" and pinned five prose surfaces against it. The field counted
and pointed at the sixth: the MCP `status` tool description, which a host reads to decide whether
calling `status` answers its question. It is in the pin now — an enumeration is a claim about
completeness, and this one is checked. (feedback-v7 §B)

15 new tests. No schema change; no migration. `.local/section-offers.json` appears on the first
capture that considers a whole-file markdown anchor and is safe to delete at any time.

## [1.9.1] — 2026-09-02

**"The memory your coding agent doesn't have" sold the half that everybody else also sells.**

The old positioning was accurate and commoditized. Storage is the easy half — notes files, RAG indexes
and half a dozen memory servers all promise an agent that stops forgetting. It also named only one of
the two failure modes this engine handles, and the quieter one is the expensive one: an agent acting
with full confidence on a belief that stopped being true three commits ago, because what survived the
`/clear` was true **once** and nothing had checked it since. Framed as memory, drift detection — the
part nothing else does — read as a side feature.

That second failure mode has a name in the literature. A **truth maintenance system** (Doyle, 1979)
holds justified beliefs, detects contradictions among them, and revises explicitly instead of
silently — which is what yigraf has been doing all along: `--why` and `--rejected` on every memory,
grounding tiers that keep "we measured this" from reading like "we assumed this", drift on anchored
code, `reaffirm`/`supersede`/`dispute` with no silent winner, and `supersedes` kept as an *edge* so the
retracted reasoning stays readable. The rebrand names shipped behavior; it promises nothing new.

The public surfaces now lead with **justify, detect, revise** — README, the landing page, and the PyPI
summary and keywords. The four questions and the graph algebra are unchanged; they are what the claim
rests on.

Deliberately **not** rebranded: the agent-facing strings — `--help`, the hook injections, `SKILL.md`,
`AGENTS.md` — which keep saying what is *in* the graph rather than what kind of system it is, because
that is what an agent needs at the moment of action. "A truth maintenance system" is a phrase for a
human deciding whether to install; in a hook injection it would cost tokens to say less. The design
law applies to the branding too.

*(Corrected in 1.10.0: as first written, this paragraph attributed one sentence — "one connected graph
over code, intent, plan, and memory" — to all four of those surfaces. It is the `--help` header and
`__init__.py`, and nothing else. `SKILL.md` opens on "the intent↔code spine" and says "one graph over
code structure, intents (specs), plans, and the memory of why the code is the way it is"; the
`AGENTS.md` block never carried the sentence at all. The point stands about all four; the quotation
was only ever true of one. Reported by the field, feedback-v7 §C.)*

One real gap closed along the way: the landing page carried no `og:`/`twitter:` tags at all, so every
shared link rendered bare. Added — pointing at the social card, whose subtitle now reads *truth
maintenance for your agent* in place of *one graph, for your coding agent*. (GitHub's own repo card
is a separate manual upload in Settings → Social preview.)

Copy and packaging metadata only — no engine change, no behavior change, no schema change.

## [1.9.0] — 2026-09-01

**Six surfaces that named the wrong thing — two of them told an agent a rescue was permanent damage,
at the exact moment it was still free.**

The third field report on the same day, against 1.8.0. It is mostly verification: everything 1.8.0
closed was re-run and confirmed. What is new is four findings, and three of them are one wrong sentence
apiece. That is not a reason to grade them low. A sentence yigraf prints at a drift moment is the input
an agent acts on, and 1.8.0 shipped every one of these green — which is the actual finding underneath
the four: **the wording moved with zero test movement.** Each fix here lands with the test that pins it.

Two items the report explicitly filed as *neither a finding* are closed here too, and one of them was
worse than reported: `show` was the last surface still calling a rescued rename permanent hard drift.
And the release adds one feature, which is what the report's own **null result** recommends — yigraf
now **offers** the section a whole-file markdown anchor is probably about, rather than warning about it.

### `reaffirm <file>` blamed the file you typed for an anchor that failed inside it

1.8.0's own D#4 widened the locus batch so a whole-file `file:<path>` reaches the section anchors under
it. That severed an identity the warning three lines below silently depended on: before, the only locus
that could fail was the one you named, so "`<target>` no longer resolves" was true by construction.
After, the thing that fails is routinely an anchor you never typed — and the batch loop kept only the
memory ids, dropping the loci `_reaffirm_concerns` had just handed it.

The result was a message that named a file still on disk, above a `reanchor` handover whose old-locus
was the healthy anchor. Following it was refused — one wasted round trip — except on a node carrying
**both** a whole-file and a section anchor, the natural shape of a store mid-migration onto section
anchors, where it *succeeded*: it replaced the healthy whole-file anchor, left the real hard drift
standing, and reported "The claim and its history are unchanged."

Worse, and the reason this led the release: `_reaffirm_concerns` hashes the stored locus and never
consulted the rename map, so a **renamed heading with the body untouched** — a rescue `drift` and `gc`
were both reporting as *settle with `yigraf gc --apply`* in the same store in the same minute — came
back from this verb as permanent hard drift. The rename is the one obligation with a deadline: the
rescue is re-derived from the body on every build and ends at the next semantic edit. Telling an agent
it is already lost is precisely what stops it from settling while it still can.

So the batch now carries the `(memory, locus)` **pair** through the loop, because two memories under
one file can fail at two different sections and neither half alone identifies what to repair. It asks
`compute_drift` for the rename map the way `link` already does — never guessing, so this surface and
`drift`/`gc` cannot disagree about one event — and reports a rescued rename as a rename, pointing at
`gc --apply`. The `reanchor` handover names the anchor that actually failed, so following it repairs
the drift instead of destroying a healthy anchor. Two smaller things with the same root go with it: the
`covers N section anchor(s)` echo no longer lists a section that was just deleted, and a memory that is
in *both* result lists is reported as **partially** repaired rather than as "drift cleared" directly
above its own ⚠.

### `gc` explained a falling `sym` count with the one diagnosis it cannot be

1.8.0 added a line explaining why the symbol count drops after a collection. It printed only in the
narrow case it was written for, and in that case both halves of its central clause were false: the
released node is a `file-anchor`, not a symbol, and the thing it names **is** in the current source —
it is simply not *indexed*, because docs are deliberately not extracted.

It cannot be otherwise by construction. `artifacts.mint_locus_node` returns early when the locus does
not resolve, so a `file:` locus genuinely absent from source mints no node at all — "not in the current
source" is exactly the case in which this line stays silent. A reader taking it at face value went
looking for a deleted function, which is the diagnosis cost the line exists to prevent. It now says
what it is: placeholder anchors for un-indexed files, still on disk, untouched.

### "Up to date" was defined two different ways depending on which file the host read

1.8.0 taught that "up to date" means no drift, no stale **and no unsettled rename** — in two of the
five places that define it, both inside `SKILL.md`. The session preamble, the `AGENTS.md` block and the
ambient MCP rule still taught the two-count version, byte-identical to 1.7.1.

That is not cosmetic, because `render_line` emits the literal `no drift` at zero and omits the `stale`
segment entirely at zero: the old two-clause predicate evaluates **TRUE** against a line printed
directly beneath it reading `⚠ 1 rename`. And the stale copies are the ones that reach the hosts with
no skill to correct them — Codex gets hooks + `AGENTS.md`, and a hookless Tier-A host gets the ambient
rule and not even the preamble, so the three-count definition was unreachable for it by construction.

The words are fixed in all five places. The actual fix is `status.UP_TO_DATE_SIGNALS`, one source for
the vocabulary, with a test pinning every prose surface against it — so the **next** signal added to
`status` fails loudly in whichever surface it did not reach. The old test could not have caught this:
it asserted `"rename" in text.lower()`, which the rename *block* satisfies whatever the preamble says.

There is a second copy hazard one file over, and it is why a code fix alone would have reached nobody.
`yigraf init` splices the preamble into the repo's **committed** `yigraf/config.yaml`, and the file
value wins at read time — so amending the default reaches no already-initialized repo. `yigraf status`
now carries `⬆ preamble` when a repo's committed preamble is byte-identical to an older shipped
default, with the full sentence at a terminal. Only an exact match to something we once shipped: the
file says the preamble is yours to rewrite, so a rewritten one stays silent, the same discipline
`installed_skill_version` applies to an unstamped skill. `yigraf cheatsheet --preamble` prints the
current text, because a nudge that names no way to get the replacement is guidance that cannot be
followed.

### `drift` is a gate on soft/hard drift, and now says so

`yigraf drift` exits non-zero on soft and hard drift; a **pending rename** and a **stale completion**
exit 0, on every command there is. The exit code is right and does not change — settling a rename
rewrites committed artifacts, so gating on it would demand a mutate-restage-recommit cycle on every
rename, which is how a pre-commit hook gets `--no-verify`'d. But `SKILL.md` §4 called it "the commit/CI
gate" without saying what it covers, while `drift --help` in the same release uses "drift" in the wider
sense that *includes* renames — so a reader who has just run `--help` reads the parenthetical against
that sense. The signal let through is the one §0b says to settle first, at the last boundary before the
edit that ends the rescue.

§4 now names the coverage and hands over `yigraf status --json`, which carries all four counts and
already works as the gate. The exit-code line itself — the only line in that function with no comment —
now carries the reason. Related, same root: the MCP `status` tool's docstring enumerated the counts,
the drift count and `sem`, so it read as exhaustive while `⚠ n rename`, `⚠ n stale` and `⚠ n conflict`
rode along unnamed in the line it returns; that docstring is what a host reads to decide whether
calling `status` answers its question.

### `show` called a rescued rename permanent damage — the last surface holding the sentence F#2 removed

`show.py` excluded renames from a node's drift list, which is right: `show` reads one node, not the
obligation set, and a rename is not drift — the content hash *matched*. But excluding it from the node
entirely made `show` the one agent-reachable surface that never mentioned the only signal with an
**expiry**, and the silence was not neutral. `show` reads the **artifact**, which still names the
locator the subject left, so the anchor line looked it up, missed, and printed `⚠ hard drift — the
locus is gone` about a move `drift` and `gc` were calling settleable in the same store in the same
minute. That is the exact false sentence this release removed from `reaffirm`, still standing on the
surface an agent lands on when it follows an id out of a drift line.

A rescued rename is now tested for **before** the missing-node case, so the anchor line says
`renamed ⇒ <new locus>`, and the node grows its own `⚠ Unsettled rename` block carrying the settle verb
and the cliff. The verb is forked by relation through the new shared `retrieval.rename_verb` — a task's
declaration is rewritten by re-`link`ing, a memory's anchor by `reanchor` — so `show` and the injected
packets cannot come to name different commands for one event. Uncapped, unlike the packet's copy:
`show` is the unbudgeted read, and a node carrying five renamed anchors needs five verbs.

### A path where a slug belongs was answered as an empty plan

`yigraf drift .` means *this repo*. `yigraf tasks .` meant *the plan named `"."`* and answered
`No plan .. Known: …` at exit 0 — so guessing the wrong calling convention produced a plausible
"nothing outstanding" on the one surface an agent asks what is left, where `yigraf status .` refuses
loudly at exit 2. Guidance is still guidance (exit 0, design law #1); what changed is that it names the
convention instead of reporting an empty result, and it does not recite the plan inventory, because the
mistake is the convention and not the name.

The same shape is worse than misleading on the verbs that **write**: `plan <slug>` composed straight
into `workspace / "plans" / "active" / f"{slug}.md"`, so `plan ../../x` landed outside the workspace.
One guard, one wording, on `tasks`, `plan`, `intent` and `supersede-intent` — it is one mistake.

### New: `remember` offers the section a whole-file markdown anchor is probably about

The field measured its own store (405 live memories, 340 `concerns` anchors, 41 whole-file markdown)
looking for a rule that separates a legitimate whole-file anchor from one that should have been a
`#section`, and returned a **null**. Every size-shaped signal overlaps almost completely — the 7–26
heading band alone holds 35 of the 41 — the best usable headings threshold costs 15 % false positives
at 32 % recall, and the most intuitive candidate, *has it actually drifted?*, fires on 7 of 13
**legitimate** anchors, because a living document drifts whether or not the anchor is wrong. Nothing
beats warning unconditionally, which is right two times in three: a mark a reader correctly learns to
ignore.

So the blocker is dissolved rather than solved, on their recommendation: **don't warn — offer the
section.** An offer needs no rule that separates. On a claim that really is about the whole document
the author reads one line, sees it is not what they meant, and keeps the anchor: no ⚠, nothing to clear
later, no training signal. Their mechanical version of exactly this named a plausible home for 19 of 25
mis-anchored items.

`yigraf.sectionfit` splits the target at its headings and scores each section by the claim's
distinctive terms, weighted by the file's **own** inverse section frequency — so a word appearing in
every section (`the`, and equally the document's own subject noun) weighs zero, and no stopword list is
needed or maintained. It stays silent unless one section wins by `section_offer_margin` (default 2×),
which is set for legibility rather than recall: a near-tie means the document says the claim's words in
two places, and naming one arbitrarily is what teaches a reader to stop reading the line. Silent too on
`--governs` (narrowing a policy anchor would change what the policy covers), on anchors that are
already a section or a line range, and on a document with no addressable subdivision — which is §7's
one required exemption (`coding-conventions.md`: numbered principles under a single title) falling out
of the design rather than being special-cased. `section_offer_margin: 0` switches it off.

The three measurements that did **not** become behaviour, and why: the `--governs` separator (commits
to the target in the 30 days before capture, a clean 4× gap with zero false positives) rests on n = 3;
the `results/` class (14 of 14 whole-file anchors under an append-only directory have an empty
`grounded_by` — `--concerns` where `--evidence` was meant) needs a notion of "a directory the repo
treats as a record", which yigraf does not have; and the whole measurement carries its author's own
bound — `#section` has zero uptake in that store, so it measures what the *right* anchor would have
been, not how often an author offered all three still picks wrong. The offer is the one form that is
correct under that bound, because it costs nothing when it is wrong.

### Also in this release: the Stop notice reaches Codex

The principal-facing turn-boundary notice (`int:obligation-notice`) — the one yigraf hook that speaks to
the *human* rather than into the model's context — was wired for Claude Code only, so a Codex project got
yigraf's context injections and none of its hand-off warnings. `install_codex_hooks` now registers the
same `yigraf hook stop` command alongside SessionStart and PostToolUse. It is the same handler, not a
port: Codex's hook contract mirrors the fields this uses, `systemMessage` included, and the handler emits
no `additionalContext` and no blocking decision, so the notice costs a UI line and zero model context.
The addition is installer-local, pinned by a regression test asserting Claude's own hook shape and Stop
command are byte-identical before and after a Codex install.

## [1.8.0] — 2026-09-01

**An expiring signal every cheap surface refused to mention, and eight other places where yigraf knew
something it would not say.**

Field feedback on 1.7.1 (the second send) reported eight findings, then an amendment that retracted one
of them and replaced it with a better one. All nine are closed here. They look unrelated and are not:
most are the same failure — a state yigraf had already computed correctly, reported through a surface
that could not act on it, in a word that meant something else. The last one is the exception, and the
one worth reading: a field yigraf never checked at all.

### A rename on a closed task was invisible to everything an agent runs

1.7.0 made an unsettled rename an expiring obligation and surfaced it at the edit hook, in a topic
query, and in `yigraf drift`. It was still invisible on a **done** task — which is the likely case,
since work ships and *then* somebody refactors its symbol. `drift.is_surfaced` withholds every
`implements` item on a closed task (int:drift-done-suppression), and the rename kind rode along.

The suppression is right and stays. What it withholds is a **re-verification prompt**: a closed task
has no honest re-verification, so relinking it is rubber-stamping. A rename is not that. The content
hash *matched* — positive proof the body did not change — so there is nothing to re-verify and nothing
to rubber-stamp, only a locator to write down. Reported as `No drift.` while `yigraf gc` listed the
pending rename, the effect was that the one signal with a **deadline** was reachable only through the
one verb nobody runs before handing off, and on a large store that verb takes minutes.

So: renames are exempt from the done-task suppression, and the count now rides the surfaces an agent
already checks. `yigraf status` carries `⚠ n rename` beside `⚠ n stale` (and `renames` in `--json`),
the Stop-hook notice carries it as its own obligation kind, and SessionStart re-injects it — a
`/clear` being exactly when the agent forgets it renamed anything. In the notice it ranks **above**
stale and drift, on a different axis from the existing ordering argument: not who can resolve it, but
whether it stops being resolvable. Drift and stale wait; this one expires.

### `absent` meant three things, and an upgrade only ever produces the third

After upgrading, `yigraf status` read `absent` where 1.5.1 said `fresh`. The view was present and
11.6 MB; it was being declined on its schema version, which is what an upgrade does and what
`load_or_build` silently repairs on the next read. One token spanned *missing*, *corrupt* and
*stale-schema*, and the diagnosis was mostly spent discovering that "absent" did not mean "missing".

Freshness now distinguishes them: `old-schema (rebuilds on next read)` for a view a previous yigraf
wrote, `absent (rebuilds on next read)` for no view at all, and `yigraf status` at a terminal spells
out the sentence. Both non-fresh states carry their remedy inline, because the surface that names the
state is not the surface that clears it. `status` still deliberately does **not** rebuild: a surface
that materializes the view it is reporting on could only ever report `fresh`.

### A section locator had to be a slug, and the one refusal that could have said so did not

`mdsec-v1` is the newest anchor kind, so a returning user reaches for it first — and reaches for it
with the heading's own capitalisation. `file:docs/design.md#Rules` did not resolve, and the refusal
read as "sections are not indexed yet". The "did you mean" tail that would have fixed it in one retry
was already written: `_symbol_suggestion` serves both locator families, but only when passed `repo`,
and the reanchor refusal was the single call site that omitted it. That is now one argument.

The slug rule itself is enforced in a better place. It exists because a locator *is* a node id, so one
spelling must be canonical — but that was enforced at the *user*, who had to know that `## Turning
Radius` is addressed as `#turning-radius`. It is now enforced on the **input**: a typed heading is
canonicalized onto the addressable slug before it can become an id, so exactly one string is ever
stored. Narrow by construction — only when the typed form does not resolve and the slugified one does,
and only through the same function that mints the slugs. Two headings that slug identically are still
refused by the check that owns that question.

### The cure for prose false-drift did not compose with the batch that clears it

`yigraf reaffirm file:doc.md` reported success and cleared nothing on a belief anchored to
`file:doc.md#a-section`. Since section anchors are the recommended cure for a prose document's false
drift, the cure and the batch-clear were disjoint. A whole-file locus now **covers the section anchors
inside it**, and names each one it touched. This is honest rather than merely convenient: re-verifying
a document is re-verifying the sections it is made of, and the re-stamp is a no-op for every section
that did not change — which is what the section anchor bought. Containment is one-way (naming a
section never reaches the whole file) and excludes line ranges, which are positional.

### `gc` kept the file and lost the id

"Never delete, always reversible, kept for history" was true of the artifact and not of the id. After
archiving, `yigraf show <id>` answered "No node", so any prose outside the graph citing that id
pointed at nothing the CLI could resolve — and nothing warns, because the citations do not live in the
graph. A field audit found 9 of 65 cited ids had gone superseded.

Two changes. The dry run now says the ids are about to stop resolving, while there is still time to
repoint them, and recommends citing the `yigraf context` query rather than the id — the query survives
a supersede, the id does not. And `yigraf show` falls back to the archive: an archived id prints its
claim, its `why`, and its successor, marked `ARCHIVED`, which makes the promise in `--help` literally
true. `gc` also now reports the placeholder symbol nodes a collection releases: a `sym` count that
*drops* after a garbage collection is alarming to read, and the cause (a retired memory's anchor was
the only thing projecting that node) was left to be derived.

### The generated skill could describe a yigraf several releases old

An upgrade replaces the CLI and leaves `.claude/skills/yigraf/SKILL.md` byte-identical, so a 1.5.1
skill happily instructs a 1.7.1 agent — naming none of `close`, `tasks`, `amend`, `gc` or the section
anchor, i.e. telling its reader a task could not be closed at all. The file could not report that,
because it carried no claim about which yigraf wrote it. It now carries a version stamp, and
`yigraf status` says so when the installed skill was written by a different version. An unstamped or
missing skill says nothing: "I cannot tell" is not "you are behind".

Six defects in the skill's own text are fixed with it. `*.sh` was offered as a whole-file `file:`
example while `.sh` is indexed as code, so the example was refused by the rule in the same sentence.
A bare `reaffirm` on grounds-drift was described as "refused" when it succeeds, exits 0, re-stamps
`concerns` and prints that the grounds-drift still stands — a clean exit is not proof. The
`grounded_by` suppression (soft grounds-drift is withheld once the tier is no longer `empirical`) was
undocumented, along with its corollary that an `--evidence` ref on an `inferred` belief can go stale
silently. The "task reconcile" prompt appeared in `context` and at the edit hook and in no skill,
though it is the natural trigger for `close`. And two things a reader would otherwise learn the hard
way now have a line each: a guidance refusal exits **0** on purpose, so `$?` cannot detect a refused
capture, and "edited the body" means *semantically* edited, so a rename plus a comment is still a
rename.

### `yigraf changelog`

Three upgrades running, the release notes had to be fetched out-of-band: the wheel carried METADATA
and the license and nothing else. Worse, 1.5.2 and 1.6.0 never reached PyPI, so a user coming from
1.5.1 received four releases' worth of change with nothing installed that could say so. `CHANGELOG.md`
now ships inside the wheel, and `yigraf changelog --since <version>` prints what changed under you,
naming how many releases arrived at once.

### A guard against reaffirming without reading

`reaffirm` is the one verb whose entire meaning is "I read this and it still holds", and the one verb
that asked for no evidence of the reading. Five ids in a `for` loop took a drift count from 5 to 0
with five success lines and no refusal — and the counter going down *feels* like progress. It cost a
field session an active decision certified as re-verified while carrying a clause that session's own
edit had falsified, caught only because a human asked whether the agent was reaffirming without
looking.

Past three single-id reaffirms inside five minutes with nothing recorded about what was checked, the
next one must carry `--verified "<what you actually re-read>"` — one line, echoed and kept in a
machine-local ledger. It never blocks an honest caller, it exits 0 with guidance like every other
recoverable refusal, and it is scoped to the **id** form: the locus form is already bounded by an act,
and rate-limiting it would punish the honest batch to catch the dishonest loop. `reaffirm_burst: 0`
turns it off. This replaces a prose prohibition in a session preamble, and the argument for the guard
is that the preamble is precisely the artifact a hurrying agent skips.

### A `--why` that only points at an argument nobody ever wrote

Reported first as a `gc` defect — archiving a parent had broken a live node's `Why`-chain — and then
retracted by the reporter, who went and read the parents: every one was a single statement line. The
pointers had always been hollow. `gc` destroyed nothing; it made a years-old gap visible by making the
target unresolvable. The verb was correct on all three of its jobs.

The real defect is upstream of `gc` and had never been named. A `--why` may defer its argument to
another node — *"LOCUS REPAIR ONLY — the belief is unchanged and the argument is in the node this
supersedes"* — and **nothing ever checked the argument was there.** For four beliefs in a real store
the reasoning now exists only in a host's notes, not in yigraf at all: the supersedes trail was
load-bearing and empty at the same time, and `--why` is the field that was supposed to prevent that.

So the pointer is checked at the moment it is created, when checking costs one lookup — rather than
by the archaeology session that is the only other way to find out, years later, when the argument is
gone. A `--why` counts as a *pointer* rather than an argument when it names somewhere else and has
almost nothing left once the name is removed (`--why "mem:abc123"`, `see mem:abc123`, the locus-repair
sentence above). Capture then follows it: if it lands on a node that argues its case, nothing is said
— citing a node is legitimate and silence is a feature. If it lands on a node that does not exist, is
archived, or carries no `--why` of its own, capture exits 0 with guidance and nothing is written.

Three surfaces, one wording, all naming `amend` — the verb that writes the argument down without
filing a mind-change nobody had:

- **Capture** (`remember` / `supersede` / `note-constraint` / `propose` / `amend --why`) refuses the
  pointer, before the build, and names where the chain bottoms out. On a supersede it adds the verb
  the act actually wanted: a supersede whose `--why` says the belief is *unchanged* is a locus repair,
  and `reanchor` moves the anchor without writing a false entry into the trail.
- **`gc`** reads the live `why` *text* for the ids this run archives. `refs_in=0` counts **edges**,
  and an id written in prose is a reference the edge set cannot see — as is a deferral riding the
  supersedes edge `gc` discounts by definition. A `why` that merely *cites* one is a single summary
  line (they stay readable: `show` resolves an archived node), because a dozen ⚠ nobody can act on is
  how a surface teaches its reader to skim. A `why` that **defers its argument** to one gets a line of
  its own and says which case it is: copy a real argument across before the pointer stops resolving,
  or hear that the pointer was hollow all along and archiving destroys nothing.
- **`show`** reports `⚠ Hollow Why` on a node already in the store — the surface where the field found
  their four by hand.

`hollow_why_words: 0` turns the guard off. Run against yigraf's own 214-memory store it flags nothing.

## [1.7.1] — 2026-08-25

**Three questions, three places to look.**

The statusline was one flat `·` list, so `169 dec` sat between `132 task ✓` and `no drift`. An ambient
surface exists to answer two things at a glance — *is anything wrong* and *how big is this* — and
neither was answerable by position: both meant reading the whole line and knowing which token belonged
to which question.

It now renders as three rule-separated groups: brand + this **session** (context gauge, update nudge),
then graph **health** (every warning, freshness last), then graph **scale** (`task/open` first, then
`sym`, `int`, `dec`, `sem`).

```
yigraf ctx 94% 236k/1M · ⬆ 1.8.0 | ⚠ 3 drift · ⚠ 1 conflict · ⚠ 2 stale · fresh | 132 task/4 open · 2037 sym · 32 int · 169 dec · sem 236
yigraf | no drift · fresh | 133 task ✓ · 2039 sym · 32 int · 170 dec · sem 237
```

Two orderings inside the groups are deliberate. Freshness sits at the **end** of the health group: it
is a status fact and belongs there, but it is not a warning, and mid-list it split the run of ⚠
segments in two — the exact scanning cost the grouping removes. And `task/open` **leads** the scale
group, because open work is the one stat there that is actionable; `sym`/`int`/`dec`/`sem` are the
size of the graph, read once and slow to move, so the number that changes now sits at a fixed offset
from the rule.

An empty group is dropped rather than rendered as an empty cell — a host that supplies no context data
is the common case, and `yigraf |  | …` reads as a value that failed to load rather than one that was
never offered. The brand still prefixes the first group with a space rather than joining it as a
segment (it labels the line; it is not a datum), so the plain render still begins `yigraf ` byte for
byte.

Layout only. Every segment keeps its own text, color and suppression rule, `--json` is untouched, and
the three settled decisions on these renderers — the task-state triple, the ASCII brand contract, and
the knee-relative context percent with its physical denominator — were re-verified rather than assumed
out of reach of a cosmetic change.

## [1.7.0] — 2026-08-24

**Two rescues that never reached the file, and a deletion the log never heard.**

A rename is the one signal yigraf resolved perfectly and then forgot. `resolve_renames` matches a
moved symbol or heading by content hash and re-anchors the edge, so nothing drifts — in the **graph**,
which design law #6 makes a derived, recomputable projection. The rescue is therefore re-derived from
the body on every build and lasts exactly as long as that body does. Rename in one session, edit the
same body in the next, and it is hard drift on a locator that will never resolve, with no record
anywhere of where the subject went.

That was called content-hash identity's honest limit. The limit is real; the silence was not. Every
agent-facing reader dropped the item — both `retrieval` paths, `show`, and the drifted set `yigraf
drift` builds its report from — so the only surface that ever named a rename was `yigraf drift`, which
the working loop never runs. The agent had no moment at which it could act, and the one edit that ends
the rescue window is the very edit the `PostToolUse` hook fires on.

An unsettled rename is now an **expiring obligation**: surfaced at the edit hook, in a topic query and
in `yigraf drift`, each naming the verb that writes it down, with a footer stating the cliff rather
than leaving it to be inferred. `yigraf gc --apply` settles every pending one, as a second backfill
beside the superseded-status one — the same sentence, that the graph already knows something a reader
of the files cannot tell. **Only the locator moves**: `anchor`, `anchor_algo` and `stamped_at` are
carried across untouched, because a rename is by definition a content-hash *match*, and re-stamping
would date the anchor to this commit when it was taken at an older one (the wrong-*when* inference
1.5.2 built `stamped_at` to foreclose).

`link` now replaces the entry the subject moved off rather than appending a second one — but only
where the engine has *proved* the move. The standing objection was sound for a blind link (a task may
legitimately implement several symbols, so replacing on a guess deletes a real edge) and dissolves
once `resolve_renames` has matched the old anchor to exactly one symbol in its own scope. The graph is
built only when the cheap pre-test passes — an existing entry with the identical anchor — so an
ordinary `link` pays nothing. None of this happens during `build_graph`: a read command would then
mutate committed files as a side effect of being asked a question, and a task's `implements` anchors
sit inside its revision-id body with a per-HEAD `stamped_at`, so two workspaces noticing one rename at
two HEADs would mint two revisions of one task — the phantom divergence 1.6.0's cache fix removed.

**A task removed from a plan no longer comes back from the replica.** `defer_families` says "the local
file wins", which is complete only where a local node exists to win. Deleting a task asserts nothing —
absence is invisible to an append-only log — so the replica's copy met no local claim, was folded
rather than declined, and returned as a live `state: todo` node contained by nothing. Caught on
yigraf's own graph: `yigraf status` counting five open tasks while `yigraf tasks --open`, which reads
the plan files, said there were none. A plan artifact's `contains` set is this family's statement of
which tasks the plan *has*, and the plan node revises when it changes, so the deletion **is** asserted
one level up. Scoped to plans this workspace holds, so a teammate-only plan arrives whole; and a
teammate's *added* task surfaces as divergence on `plan:<slug>` rather than vanishing.

### Also in this release

- **`yigraf amend`** — repair a botched record (statement, `--why`, `--rejected`) with no `supersedes`
  trail. The two ways out were both wrong: hand-delete the artifact, or file a mind-change nobody had
  and leave the mangled text standing inside the trail that is the most valuable structure in the
  graph. It re-keys the node, because `memory_id` hashes exactly the payload it repairs, and refuses on
  a referrer or a pushed assertion. `--why-file` on every verb that takes `--why`, for the same reason
  a shell rewrote one.
- **`mdsec-v1` hardening** — six defects from an adversarial review of the 1.6.0 diff, two of them
  false *negatives*, the failure that release existed to remove. A deleted `## License` could re-anchor
  onto the identically worded section of an unrelated document, and every body-less heading hashes to
  `sha256("")` so deleting one stub left "exactly one survivor" reading as a rename. Rename matching is
  now scoped per file for `mdsec-v1` and refuses the empty-section hash outright.
- **A divergence count you could not clear** — `⚠ 45 diverged` in the SessionStart injection while
  `yigraf status`, in the same second, said none. Divergence is computed by the fold, which is what a
  cache exists to skip, and the replica was not a fingerprint input — so `whoami`, the advertised
  remedy, could never reach the surface showing the symptom.
- **`plan:divergence-ledger` retired without implementing.** Its premise described 1.3.0 code; the
  classifier has been three-filter since 1.5.1, the six locators it cited are the same six that release
  measured and fixed, and the ledger it proposed was already rejected by name as unbounded
  per-workspace state a fresh clone loses. Its one surviving finding — a divergence test whose
  "competing" revision came from this repo's own unattributed file log — is fixed.

**Not on PyPI: 1.5.2 and 1.6.0.** Both landed as commits and changelog entries but were never tagged
or released, so `pip` goes 1.5.1 → 1.7.0. Everything in them ships here.

## [1.6.0] — 2026-08-23

**A position is not an address. Prose moves.**

`file:<path>#<section>` anchors a belief to one markdown heading and its body, under a new algo
(`mdsec-v1`). The fourth field report asked for heading-level anchors and 1.5.2 deferred it, because a
settled call from 2026-08-12 had already rejected them — doc support stops at file granularity,
revisit only if a concrete workflow needs sub-file precision. Precision turned out to be the smaller
half. Reproduced end to end: insert a paragraph **above** a governed section and its line-range anchor
false-drifts though its text never changed; `reaffirm` — the exit the drift line names — reports
success while re-stamping the hash of the **wrong** region; and rewriting the actual governed claim
then drifts *nothing at all*. A positional address does not merely nag, it slides off its subject and
goes quiet about it. That is a false negative in the moat, and it is what met the revisit condition
(mem:a65f1ccad03b765e supersedes mem:fb0d9658b0d56075).

The three costs the old call named are paid by mechanisms `astnorm-v1` already had, not by new design.
A section's **own heading text is excluded** from its hash — exactly the `exclude` rule that keeps a
symbol rename from drifting, and exactly what lets a renamed heading re-anchor instead of hard-drifting.
A **nested subsection collapses to a `<sec:slug>` marker** and is not descended into, exactly as a
nested symbol becomes `<def:NAME>` — so editing prose under `### Soft drift` never drifts `## Drift`,
while adding, renaming or removing a subsection does. And **each block is hashed as one
whitespace-collapsed token**, the prose analogue of quote canonicalization: a rewrap is to text what a
`black` reflow is to code. Inside a fenced or indented code block every byte is kept, because
indentation is semantic in a sample. Still **no markdown extractor and docs still stay out of the
semantic index** — a node exists only for a section some assertion actually names, so a repo whose docs
nobody governs pays nothing.

Building it surfaced five older defects underneath, none in the model and all in the delivery: the
edit hook reaching almost no `file:` anchor at all, the cache not noticing a governed file change,
two guidance dead ends, and the shipped skill having quietly stopped being the skill this repo
reads. Three of them were only reachable by *composing* features, which is where the tests were
thin — each is now pinned. An adversarial review of the diff then found six more, four of them in the
new code and two of those false *negatives*: a dead section re-anchoring onto a coincidence, and a
commented-out heading truncating the section it sat in. Both are listed below; both are the failure this
release exists to remove, which is the argument for reviewing a drift-detection change by trying to
make it miss something rather than by reading it.

### Added
- **`yigraf amend <mem:id>`** — repair a botched *record* (a `--why` the shell rewrote, a typo in the
  claim) with **no supersedes trail**. `memory._render_body` had been naming this verb inside its own
  refusal for a while, because the two exits were both wrong: delete the artifact by hand, or
  `supersede` — filing a mind-change nobody had and leaving the mangled text standing as the superseded
  belief, in the trail that is the most valuable structure in the graph. `reanchor` is the same argument
  for a moved locus; this is its sibling for the text.
  It **re-keys** the node, because it must: `memory_id` hashes the statement/why/rejected it repairs and
  a test pins the on-disk id to that payload, so the reply names a new id for the same belief, the old
  file is removed, and the earned telemetry moves across (a typo fix must not demote a settled node).
  The refusals are the design. Any *referrer* blocks it, because a referrer's own id hashes what it
  points at — a successor's `supersedes` list, a resolution's reconciled pair — so a re-key would
  cascade transitively, each node losing the history hanging off its old id; `supersede` is the additive
  correction there. `superseded_by` is the one exception, and excluding it is what makes the verb usable
  rather than a nicety: `supersede` takes a `--why` of its own, so the node most likely to need repair
  is the successor just written, and that back-pointer is a stamp rather than an identity (absent from
  the id payload), so it is re-pointed. A **pushed** assertion refuses for a different reason — an
  append-only log has no retraction, and a local re-key would mint a second node while teammates keep
  the one they pulled, arriving as a knowledge conflict rather than a fix. Only a *known* push refuses;
  offline or an unreadable replica proceeds (design law #5). Also on MCP. (mem:fab4f6d457eb41ae)
- **`--why-file <path>`** on every verb that takes a `--why`. A shell is a text transformer: backticks,
  `$` and `!` inside a quoted string silently rewrite the reasoning, and a mangled `--why` is
  unrecoverable prose rather than a syntax error. A file is immune, and it also answers what was left of
  **v4 #15** — the *ordering* half of that ask turned out to be already satisfied (an
  `--grounding empirical` with no `--evidence` is refused in 0.2s, before any build), so the real cost
  was never the refusal but re-transmitting the argument it discarded; that refusal now names the flag.
  Newlines collapse to spaces, because `**Why:**` is one line.
- **`--rejected` is repeatable**, joined with ` || `. It was a single-value option, so a second
  `--rejected` silently won and the first ruled-out design was gone — unwarned, at capture time, on the
  most perishable content in the node. Found while recording two rejected designs for one decision; 12
  memories in this repo had had the separator typed in by hand.
- **`file:<path>#<section>`** on `--concerns`, `--governs`, `--evidence`, the rejection premises,
  `link` and `reanchor` (CLI and MCP). The slug is the heading title, case-folded, with each run of
  other characters collapsed to a single `-` — deliberately not GitHub's rule, which keeps one `-` per
  punctuation character: the audience is an agent typing a locator, not a browser following an anchor
  link. A slug naming two headings is **refused** rather than pinned to whichever came first, and a
  missed guess gets the file's real headings printed back.
- **A renamed heading re-anchors instead of drifting** (int:drift-detection: SHALL NOT flag a pure
  rename). Symbols get this free because the extractor indexes the renamed one; docs are not indexed,
  so `artifacts.mint_locus_node` resolves the move from the *stored* anchor and mints the node under the
  heading's new locator, which `drift.resolve_renames` then finds by the same hash — no doc-wide index.
- **A positional caveat on every drifting line range**, naming the section form when the path is
  markdown. A range's drift line used to offer only `reaffirm`, which is the call that silently
  re-stamps the wrong region.

### Fixed
- **A push packet buried its own reason for speaking** (v4 #13). The edit hook and SessionStart emitted
  the ranked slice *above* the obligation/drift blocks — inverting a packet that exists only because
  something governs the locus or is wrong with it (design law #4 keeps it silent otherwise). The field
  watched that block go unread by the fourth edit of a session and noted a *relevant* obligation would
  have been skipped with the rest. Signals now lead the two push surfaces; a `context "<topic>"` query
  still leads with the slice, because there the slice is the answer and warnings would answer something
  else. Emit order only — the frame accounting, caps and four budgeting passes are untouched. The
  *suppression* half of the ask is deliberately not done: it means ranking an intent's criteria against
  the edited symbol, where a wrong call suppresses a criterion that *did* govern the edit — strictly
  worse than showing one that did not — and the reporters' evidence predates the 1.5.0 digest latch that
  already removed the repetition they identified as the cause. (mem:297e29b61c78ba25)
- **A stale completion said nothing about when it went stale, and the obvious reconstruction was wrong**
  (v4 #14). Not a wrong verb but correct-looking reasoning: the field read `git log`, found earlier
  commits touching the file, and concluded the staleness predated the session — invalid, because `link`
  re-stamps the anchor on every call, so anchor history is a different timeline from commit history and
  their own edits that session were the cause. Nothing in the line contradicted the inference. `link`
  now records the commit `HEAD` the anchor was taken at and the STALE line names it. A sha rather than a
  clock, and that is load-bearing: `filelog._plan_assertions` hashes the task body into its revision id,
  so a per-machine timestamp would make two agents linking the same symbol mint two revisions of one
  task — manufacturing exactly the phantom divergence fixed above. Silent on an anchor stamped before
  the field existed, since an undated stale line is precisely the one whose age is unknown. The **actor**
  half stays deferred, now with a second reason beyond the v3 review's (it is a provenance-model decision
  for the online line): an actor in the assertion body would make identical links diverge by
  construction. (mem:6cc8adbe021beee9)
- **A `commit:` evidence ref was the one grounding citation accepted with no feedback at all** (v4 #16).
  It is opaque by design — immutable, so it never drifts, so nothing downstream ever re-examines it — and
  the field grounded a claim about what a human observed on one date in a record produced the day after,
  accepted silently: "it makes an unrelated artifact look like the basis for a claim." yigraf cannot
  judge that (the observation's date is in the prose, not the graph), so it now resolves the sha and
  echoes its **date and subject** at capture, while the capture is still cheap to redo — a wrong citation
  is usually obvious the moment its subject line is read next to the claim. An unresolvable sha gets a
  sharper line, because nothing else will ever catch it. Both warn, never refuse. (mem:16a30e5faaee8b66)
- **A grounding tier for "observed, but in a conversation" was asked for and is refused** (v4 #17) — the
  ask rested on a cost that does not exist. `memory.py` claimed a low-grounding node "surfaces as a
  re-verify TODO in `context`", which *would* make `inferred` a standing demand no verb can satisfy for
  a belief a human merely stated. Measured: it does not. Nothing reads the tier as a nag; the only
  grounding-driven surfacing is the *demotion* of `empirical` when its named evidence drifts, which needs
  evidence and so cannot fire here. So `inferred` carries no penalty, and `--type preference` plus
  `yigraf attest` (⇒ `attestation: human`) already carry the semantics. The real defect was the
  docstring promising a surface that was never built — fixed there, with the asymmetry stated so the next
  reader doesn't re-derive the ask. (mem:4af3d78cca577b37)
- **The divergence count the agent read came from the cached view, not from the replica.** Third
  instance of the omission class the governed-`file:` fix below is the second of, and the sharpest,
  because the surface it lied to is the agent's. `⚠ 45 diverged` in the SessionStart injection while
  `yigraf status` in the same terminal said none: `_hook_graph` reads through `load_or_build`, so the
  line served whatever the last materialize measured, while `status` always rebuilds. The replica was
  not a fingerprint input, so nothing a *sync* does could invalidate the view — and `whoami`, the one
  fix 1.5.2 advertises for a phantom count (a workspace that has only ever pulled learns its own actor
  and its unpushed edits stop reporting), writes only the replica. The fix could not reach the surface
  that showed the phantom. Two readers of one view disagreed on top of that: `load_or_build` compared
  fingerprints and served the cache while `_freshness` byte-compared the projection and called it
  `behind` — the freshness signal firing with byte-identical nodes and edges and no source change.
  The replica is an input now (one `stat`, and only when `online.project` is set), which also fixes the
  sibling staleness: a pulled belief left the view untouched, so the edit hook kept answering from a
  graph a teammate's assertion had never entered, against `int:team-reconciliation`. `DB_SCHEMA_VERSION`
  goes to 3 per its own contract (one rebuild on upgrade), and the enumeration that justifies the whole
  cache is superseded rather than patched, for the reason its own predecessor gave — a live belief whose
  soundness argument a reader can check and find false does not get to stand on the node that justifies
  the cache (mem:1767afc5e6945e6e supersedes mem:9d39e40507126bf6).
  `graphdb`'s comment had `diverged` filed as a per-run signal "popped at store time" *alongside* the
  guidance flag, and it was neither popped nor per-run: believing it could not be persisted is what made
  it invisible that it was being served. The per-run channel is now one attr with one owner
  (`graph._VOLATILE_GRAPH_ATTRS`, stripped in the serializer so the store and the freshness comparison
  see one projection). `survival_measurable` stays *in* the view on purpose and a test said so within a
  minute of the attempt: stripping `survival` re-derives to the same number, stripping that one loses
  the difference between measured-`False` and never-asked, and a missing key reads as ARMED
  (mem:104fbd53251ad7f8).
- **A dead section was reported as a benign `renamed`, onto a coincidence.** Two false negatives, in the
  one class this feature exists to remove. `mint_locus_node` scoped its rename rescue to one file and
  required a unique hit; `drift.resolve_renames` then did its own lookup in a graph-wide index and
  bypassed both — so a `## License` deleted from one governed doc re-anchored onto the identically
  worded section of an unrelated one, relocating a belief onto prose it never governed in a file it
  never named. And every body-less section hashes to `sha256("")`, so deleting one of two ordinary stub
  headings left "exactly one survivor carrying the stored anchor" and read as a rename. The asymmetry
  with symbols is the point: uniqueness has teeth for symbols because the extractor indexes *every* one,
  so a collision normally yields 2+ matches — sections are deliberately not indexed, so a collision
  looks unique. Matching is now scoped to the section's own file, and an empty section never matches.
- **A heading `mdsec-v1` could not see, or wrongly invented, moved a section boundary.** A section ends
  at the next heading of its depth or shallower, so this was never only about what is addressable.
  Setext headings (`Title` over `===`/`---`) are now parsed: without them an ATX section's extent ran
  past a setext one and drifted on a neighbour's prose, and — the silent half — a setext subsection
  never reached its parent's marker list, so renaming, removing or adding one drifted nothing, against
  a contract stated in three places. HTML comment blocks are now skipped: a commented-out
  `## Old wording` *ended* the governed section, after which the prose below it could be reversed in
  silence. YAML front matter is skipped too, so a `#` comment in it is not a phantom heading and its
  closing `---` is not a setext rule for the line above.
- **The cache fix was one-directional.** A node is minted only for a locus that *resolves*, so watching
  the minted nodes watched every file whose content can change and none whose **arrival** matters — and
  a forward reference is told, in as many words, that it governs once that section is written. Writing
  it did not invalidate the view, so the hook stayed silent on the very edit that fulfilled the
  reference; a `file:` rejection premise ("withdraws this the moment that file appears") likewise kept
  reporting absent on the cached read path. The dangling edges and the `file:` premises are swept too.
- **`reaffirm` hard-guided on a *stored* evidence section**, so a third party making one ambiguous
  dead-ended the verb `drift` had just named — the typed-vs-inherited rule above, missed in
  `_stale_grounds` and `_dead_grounds`.
- **The new line-range caveat named a verb that refuses the caller.** `reanchor` takes a `mem:` id, so
  on a task's `implements` item it was a dead end; and `link` alone does not clear it either, because a
  task's implements edge is *appended*, not replaced, leaving the drifting range beside the new anchor.
  The line now names `link` **then** `unlink` for a task, and `reanchor` for a memory — and a test runs
  each and asserts the ⚠ is gone.
- **A file whose name contains `#` stopped being anchorable.** `C#-notes.txt` was refused as "`C` is not
  markdown", advising a path that does not exist, and any anchor already stored on it stopped resolving.
  A fragment now needs the text before the *last* `#` to look like a filename with an extension — so
  `cfg.txt#top` still gets the helpful "use a line range" guidance.
- **The edit hook reached only a whole-file anchor on an all-lowercase path.** The extractor casefolds
  a path into its node ids, but a `file:` anchor node is minted from the assertion, so it keeps the
  spelling its author typed *and* any `:L<a>-L<b>` or `#<section>` suffix. Two surfaces compared the
  casefolded path against the whole id — `retrieval` looked up `file:<pid>` exactly, and the hook's gate
  open-coded the same test under a comment saying it mirrored that key, so it inherited the blind spot
  faithfully. Measured: a governed `file:Dockerfile` — mixed case, and the example `int:file-anchoring`
  itself names — and **every** line-range anchor seeded nothing, so the one surface whose job is to
  speak at the moment of the edit was silent about the file it had just been called for. There was no
  test because the Dockerfile case only ever asserted `compute_drift`, never the hook.
  `retrieval.locus_nodes` is now the single owner of "which nodes are this path".
- **Editing a governed non-code file did not invalidate the cached view.** A Dockerfile, buildspec or
  doc is neither an extractable source file nor a yigraf artifact, so nothing in the fingerprint moved:
  `context` and the PostToolUse hook served the *old* hash for the very file just changed and reported
  no drift, while `status`, which always rebuilds, reported it — two surfaces disagreeing about one
  file, with the quiet one on the hot path. The governed loci now ride the view as `governed_files` and
  are stat'd with the rest; `DB_SCHEMA_VERSION` goes to 2 per its own contract (one rebuild on upgrade).
  The correctness claim that justified the whole cache said the graph is a pure function of *(source
  files + assertion files + config)*, which was false for exactly the loci `int:file-anchoring` exists
  to govern — so it is superseded, not patched (mem:9d39e40507126bf6).
- **A bare `reaffirm` of a pre-1.5.0 `empirical` node with no `evidence:` was refused** by a message
  about `--grounding empirical`, a flag the caller never passed: the gate read
  `grounding if grounding is not None else node.grounding`, turning a guard on the *upgrade* into a
  guard on every reaffirm of such a node (five in yigraf's own store). Both exits it named miss what was
  asked — `--evidence` wants an observation invented, the downgrade discards a probably-true tier — to
  clear a `concerns` drift on a different axis. So that drift was unreachable by the verb its own drift
  line names. The gate now keys on the flag passed, matching the sibling guard two lines below that
  always had, and the tier-without-evidence gap is stated as a note *after* the re-stamp rather than
  enforced before it.
- **A `sym:` locator's `#` is no longer read as a doc fragment** — without that guard every `sym:`
  guidance surface answered about headings, and a `did you mean` went silent.
- **A dangling-edge warning names what the locator names**: "no such *section*", not "no such symbol",
  and "governs once that section is written", not "once the code lands".
- **An inherited locus that stopped resolving refused the `supersede` reacting to it.** A capture-time
  hard guide is about a locator the caller *typed*; against one carried from the predecessor it punishes
  the wrong person — a third party adding a second `## Drift` to a governed doc made `#drift` ambiguous
  and lost a mind-change to a message about heading titles, for a caller who touched no docs. The same
  shape predates sections: a `--governs` whose file had been deleted blocked the supersede that reacted
  to the deletion, and a `--governs` guard can only ever *block*, since a policy carries no hash either
  way. Guides now apply only to loci named on this call; a stored one that no longer resolves lands as a
  dangling edge and drift says the rest.
- **The guidance `install` writes had silently stopped being the guidance this repo reads.**
  `hooks.SKILL_MD` and `.claude/skills/yigraf/SKILL.md` are two copies of one document and nothing
  asserted they agree — and the divergence runs one way: yigraf self-hosts, so the checked-in file is
  what a contributor edits, while every user who runs `install` receives the constant. The
  section-anchor guidance in this release landed in the file and would have shipped to nobody. Both it
  and `_AGENTS_BLOCK` are now pinned equal, with a failure message that names the fix in either
  direction.

## [1.5.2] — 2026-08-22

**A guidance string that names a verb the state refuses is a dead end wearing a helpful face.**

The fourth field report, from eight days of daily use on `ezgo-isaacsim` (2850 symbols, 366 memory
artifacts, 91 supersedes edges), with every claim re-checked by an independent pass instructed to
refute it. Almost all of it lands in one place: **design law #1 stakes the product on the guidance
being right** — a recoverable condition exits 0 *because* the message teaches the retry — and nothing
tested that the taught retry works. Six surfaces named a verb that is provably refused in that state,
omitted the one that works, described a command the caller had not sent, or reported a success that
had not happened. `tests/test_guidance_is_executable.py` now closes the class: put the tool in a
state, read the verbs its own output names, run them, assert the ⚠ is gone.

### Added
- **`yigraf close task:<plan>/<n>` and `--reopen`** — tasks were the only authored family whose
  mutable state had no verb that writes it. R6 says the *file* is truth; it does not say a verb may
  not write the file, and yigraf already shipped exactly that verb for the sibling authored family
  (`intent <slug> --status`). So an agent that had correctly internalised "never hand-edit an
  artifact" was structurally unable to close a task: the field measured an open count that was **67%
  false** — 8 of 12 already done, some for a day — on the line `yigraf status` makes the pre-done
  authority. Closing refuses a task that implements nothing (unless `--force`), so "done" and
  "anchored" land together: a completion with no anchor can never go STALE.
- **`yigraf tasks [<plan>] [--open|--done|--stale]`** — "what is outstanding" with no dependence on a
  semantic query matching. `context "what is outstanding" --family plan` returned 0 nodes; `status`
  gave a bare count; `show plan:<slug>` listed ids without state.
- **`yigraf plan <slug> --append-task "…"`** — the CLI could not add to a live plan at all. One
  campaign ran 125 cells across four stages and created zero tasks. Numbers continue past the highest
  and are never reused, so an id already on a `link` edge keeps its meaning.
- **`plan`, `close` and `tasks` over MCP** — of 15 tools it exposed `link` and `unlink`, so an
  MCP-only host could anchor tasks it had no way to create, and none to close.
- **`propose --governs`** (CLI and MCP) — the fourth capture verb was the one missed.
- **`gc` backfills `status: superseded` / `superseded_by:`** on a store built before 1.5.0 wrote them.
  Nothing mis-ranked (`superseded_in` is recomputed from the edges every build), but 87 of 89 retired
  beliefs still read `active` to a reader of the *files* — which is how it bit: both twins read
  `active`, so the wrong one got pinned. Dry-run by default, like the rest of `gc`.

### Fixed
- **`reanchor` silently converted a `--governs` policy anchor into a content anchor**, so a locus
  repair reintroduced the recurring never-real ⚠ that `--governs` exists to prevent — while printing
  "The claim and its history are unchanged", true of the claim and false of what the anchor *means*.
  `GOVERNS_ALGO`'s docstring named `reaffirm` as the only re-stamper that must leave it alone and
  overlooked this one. It composed badly too: the hard-drift line for a deleted governed locus
  recommends `reanchor`.
- **No named exit repaired a drifting `grounded_by` anchor.** `--evidence <fresh>` was refused for
  every value except the drifting locator itself; the "honest downgrade" to `inferred` cleared
  nothing and the line then still called the node an "·empirical belief" and re-offered the downgrade
  just performed; `unlink` was refused while the belief was empirical. `reanchor` — which does the
  whole job in one command — was named in none of the four surfaces. All four now carry the same
  four-exit sentence the `concerns` fork got in 1.5.0, the downgrade genuinely clears soft
  grounds-drift (the tier it defends has been withdrawn), and hard drift still surfaces at any tier.
- **"grounds-drift cleared" was printed unconditionally**, so it was false in two reachable cases —
  worst on *deleted* evidence, where the only accepted `--evidence` form reported success, exited 0,
  emitted no warning tail, and left hard drift standing. A success line a following `drift`
  contradicts is the one message an agent is most likely to believe and stop on.
- **The empirical guard explained a command nobody ran.** It refused an invocation that *had*
  `--evidence` by describing what `--grounding empirical` **without** `--evidence` would do, never
  stating the condition it was actually enforcing (every drifting locator must be re-named), and named
  only one of two drifting refs — so following it verbatim refused again on the other.
- **The Stop-hook notice keyed its verb on the relation alone**, so hard and soft drift got an
  identical line and on hard drift both verbs it named are refused while both that clear it were
  absent. It carried a third copy of wording `retrieval.drift_tail` owns; it now calls it.
- **`supersede` inherited a dead anchor and then advised the one verb the drift surface had already
  ruled out**, making repeated supersedes a closed loop that manufactures exactly the
  "LOCUS REPAIR ONLY" nodes `reanchor` was built to stop producing. It now distinguishes a locus that
  *died* (advise `reanchor`) from a genuine forward reference (`reaffirm` stays right), and the
  `<mem-id>` placeholder — printed literally, one line before the id existed — is filled.
- **`supersede` dropped `promotable` and defaulted `--type` to `decision` instead of inheriting**, so
  a bare supersede quietly demoted a constraint — while the flag's three siblings on the same verb
  said "default: inherited", and the verb *advertises* what it carried.
- **A pending supersede surfaced only if it happened to clear the paraphrase gate.** `pending` was a
  label applied to a pair the cosine sweep or a dispute had already found; nothing enumerated the
  edges. A supersede states a *changed* belief, so normally the two sit below the gate — the field
  measured 0.6457 and 0.5583, invisible to `status`, `status --json`, `conflicts`, `show` and the Stop
  notice, while `supersede`'s own promise is that the predecessor stays authoritative *until a human
  resolves the conflict*. The better-written the correction, the less likely the trust floor was
  enforced. `detect_conflicts` now enumerates pending edges directly, index-free, ranked above the
  sweep. `show` on the still-authoritative side marks it too.
- **`--rejected-valid-when` asked the graph while its sibling asked the filesystem**, so a `file:`
  premise that exists but is not indexed warned "typo?" — self-falsifying (it fires on the first
  capture for a path and never again) and false besides, since `show` then reports the premise holding.
- **`reaffirm <locus>` advised capturing a second memory** about a locus a live `grounded_by` anchor
  already reasons about. It now names the node and the call that reaches it.
- **The capture echo reported `--governs` as `concerns`** on all three verbs that accept it — and on a
  supersede printed that one line above "Carried 1 governs", two lines of one run disagreeing.
- **The `SKILL.md` description `install` writes was invalid YAML by spec** — an unquoted plain scalar
  containing `` `yigraf status`: ``, where `: ` terminates the scalar. Claude Code's loader tolerates
  it; a stricter host would drop the skill.
- **`install` now names the host directories a HOME-dir marker is about to create in this repo**, and
  how to narrow. Detection is unchanged — wiring two hosts is right for someone who drives the repo
  from two — but "installed on this machine" is not "used here", and those directories arrive
  untracked in a tree where every yigraf artifact is deliberately git-excluded.

### Not changed, deliberately
- **Auto-detecting every installed host.** Narrowing to repo markers would silently stop serving a
  developer who really does drive one repo from two hosts. The fix is the announcement, not the
  detection.
- **Retracted by the reporters, and confirmed here:** soft drift does *not* fire on docstring-only
  edits. `astnorm` strips comments in every language yigraf ships and docstrings in Python, and the
  `ANCHOR_ALGO` tag has not moved. What they watched drift was a `file:` **line range**, whose
  sensitivity to a non-behavioural edit is genuinely different from a `sym:` anchor's.

## [1.5.1] — 2026-08-20

**A verb that re-stamps one field must not rewrite the rest of the artifact.**

Two fixes from the first day on 1.5.0, both the same failure at different altitudes: a write that
reported success while destroying or burying something the caller meant to keep. No new capability,
no new flag, no node-id or wire change — a rebuild produces an identical graph.

### Fixed
- **A metadata verb deleted whatever the canonical body shape does not model.** `yigraf reaffirm
  mem:<id>` dropped 125 words of hand-written prose — two paragraphs extending a belief, added that
  morning — because it re-read the artifact, rebuilt the body from (statement, why, alternatives), and
  wrote back the difference. Those three are the only things `_parse_body` recognizes, so everything
  else in the file was, to the serializer, not there; nothing in the output said anything had been
  removed, and the entire trace was a diffstat showing 5 deletions where sibling files showed 1. The
  blast radius was every verb that round-trips an artifact to edit one frontmatter field — `reaffirm`,
  `reanchor`, `attest`, `pin`, `unlink`, and `supersede`, which truncates the **predecessor**, the
  artifact whose body is pure history and the one a truncation is least recoverable from. It is also
  the verb whose whole job is to say "still true", re-stamping an anchor by destroying the record it
  vouches for. `artifacts.update_intent_frontmatter` already had this right for intents (mutate the
  parsed frontmatter, write the body back untouched); the memory family was the lone outlier.
  `Memory` now carries the body as read and `render_memory` re-emits it verbatim, composing the
  canonical shape only for a node that has none yet — a fresh capture. Rebuilding and appending the
  leftovers was rejected: it reflows what a human wrote and moves interleaved prose to the end, so a
  re-stamp is still not byte-clean. When the canonical triple has changed under an authored body both
  exits lose something the caller wanted, so rendering raises *before* any write and names the right
  verb — a changed belief is a new node that `supersede`s this one, never an edit, the law
  `artifacts.py` already states for an intent's SHALL contract. The carried body stays outside
  `memory_id`, so a hand extension can never re-identify the node or fork it from a teammate's
  byte-identical capture.
- **Unrecognized frontmatter keys now ride through a re-stamp** instead of being dropped. The memory
  store is committed and shared across machines, so version skew is normal, and an older engine
  re-stamping one anchor must not silently strip a field a newer one wrote. `_MANAGED_META` names the
  keys `render_memory` owns, asserted by containment rather than by trusting two lists to be edited
  together — a renderer field missing from the set would read back as unrecognized, and then a verb
  that *clears* a conditionally-written key (`pinned`, dropped by `pin --off`) would find the stale
  on-disk value riding through and silently un-clear itself.
- **`remember --rejected-invalidated-when <a premise that already holds>` captured a rejection born
  invisible.** The field names the condition that *retires* a rejection, so one that is already true
  withdraws it from the moment of capture: the alternative is recorded and unreachable, because no
  later event can make an already-true condition become true. The mis-fill was a `file:` locator
  naming the file the belief was *about* — reaching for the subject instead of a condition that could
  still change. The sibling `--rejected-valid-when` has had a typo warning all along; this half was
  deliberately left unvalidated on the grounds that it legitimately names something not-yet-present,
  which is true of the field and says nothing about the value. Soft-warn only (D#3): the premise is
  still captured, and the message names the fix rather than the fault. Warning on the locator *kind*
  was rejected — a `file:` premise is not nonsense, it is `int:conditioned-rejections`' own scenario;
  what makes a premise wrong is that it is already true.
- **A capture-time premise check asks the filesystem about a `file:` premise, never the pre-build
  graph.** The first version of the warning above called `retrieval.premise_holds` against the graph
  `_capture_memory` already had, and never fired — including on the exact mis-fill it exists to catch.
  That graph predates the artifact being captured, and a `file:` node outside an extractable language
  (`console.html`, `redis.tf`, a Dockerfile) is projected *only* by the references pointing at it, one
  of which is this very capture, so asking it reports every such premise absent. `file_content_hash`
  is the honest oracle (files are truth, design law #6) and already resolves the `:L<a>-L<b>` region
  form. `int:`/`mem:`/`sym:` are projected independently of who points at them, so the graph still
  answers for those three.

### Upgrading
- Nothing to do. No wire change, no node-id change, no new flag — a rebuild produces an identical
  graph, and an existing memory artifact is read and re-stamped byte-for-byte. Two notes for anything
  that consumes yigraf programmatically: `remember` can emit one additional ⚠ line (soft, still exit
  0, the capture still lands), and `memory.render_memory` now raises `ValueError` on an authored body
  whose statement/why/rejected changed — no verb reaches that path, it is a caller-bug guard.

## [1.5.0] — 2026-08-20

**A warning you cannot act on, and a success that did nothing, are the same bug.**

This release is the third field report (feedback-v3, a week of daily use on 1.4.0) applied. Its two
sharpest findings shaped everything here: a conflict count no command could list — "the only
actionable information was the integer 1, while every resolving verb takes two ids that nothing hands
you" — and a `supersede` that silently dropped the predecessor's anchors, leaving a correction that
would never resurface at the edit hook on the exact symbol it warns about. The report also put the
first measured number on yigraf's cost: 15 of 23 PostToolUse packets in one session were byte-identical
repeats, 3.47M tokens for text the model could already read.

### Added
- **`yigraf conflicts`** — the third re-verify signal finally gets the same listing surface as the
  other two: every open pair with its shared anchor, cosine, provenance-preferred side, and resolving
  verbs (same wording as the Stop-hook notice). Exits non-zero when conflicts stand, so CI can gate on
  it exactly like `drift`. Over MCP too. `yigraf show <mem>` now also reports any open conflict the
  shown node is a side of — the natural second home, since a reader holding an id is the one most able
  to resolve it. And `status --json` now carries the count under **`conflicts`** (was `coherence`,
  a key that matched neither the rendered `⚠ n conflict` nor anything an agent would look for).
- **`yigraf reanchor <mem> <old> <new>`** — the locus-repair verb: moves one `concerns`/`grounded_by`
  anchor with **no supersedes edge**. The field paid for its absence four times, each a node whose
  entire body reads "LOCUS REPAIR ONLY — see the node this supersedes for the argument". One meaning
  per verb: locus moved → `reanchor` · unchanged locus drifted → `reaffirm` · mind changed →
  `supersede` · never belonged → `unlink`. Over MCP too.
- **`--governs`** (on `remember`/`note-constraint`/`supersede`) — a policy anchor for a belief about
  how a locus is *used* rather than what it contains ("status.md holds ONLY status"). Surfaces at the
  edit hook exactly like `--concerns`, carries no content hash, **never drifts** — the field's policy
  memory drifted three times in one session while every flagged edit *obeyed* it, and a ⚠ that is
  usually noise trains the reader to clear it unread. Over MCP too, on all three capture tools: MCP is
  the *only* channel on a hook-less host (the Antigravity IDE, mem:016), so a capture flag that stops
  at the CLI is simply absent for those users.
- **`unlink mem:<id>` now retires a `concerns` ref too** (it reached only `grounded_by`; the fix for a
  mis-anchored capture was hand-editing frontmatter). Refusals on both `unlink` and `reanchor` name
  every anchor the node actually carries, so "no such anchor" can no longer be read where "wrong list"
  is the truth.

### Changed
- **A conflict now leads the Stop-hook obligation notice** (`KIND_ORDER`), because it is the only
  signal that structurally requires the principal — the agent can re-link a stale completion and
  re-verify drift, but two same-tier live beliefs stay open until a human decides. This is the *real*
  mechanism behind the field's "the conflict reached nothing": it was computed all along
  (`detect_conflicts` self-loads the index), then crowded out — a repo carrying 16 stale completions
  and one conflict rendered five stale lines and "… 12 more not shown", dropping the one item only
  that reader could resolve.
- **Hard `concerns` drift leads with `reanchor`** in both drift surfaces (`retrieval.drift_tail`, so
  the hook and the CLI keep one wording): "the locus is gone" usually means the subject *moved*, and
  the old advice — `supersede` as the only exit — is what manufactured the false mind-changes.
- **`supersede` inherits the predecessor's `concerns`/`governs`/`serves` by default** (explicit flags
  re-aim, each overriding its own kind), re-resolving inherited loci fresh and saying what carried. A
  mind-change is about the same subject; a correction that lands with no anchor is inert.
- **An applied `supersede` (and an `attest` that applies a held one) stamps the predecessor's artifact
  `status: superseded` + `superseded_by:`** — mirroring `supersede-intent`. Both twins reading
  `active` in the store is how a retired belief got pinned.
- **The PostToolUse hook injects nothing when the packet is byte-identical to one this session already
  received** — a digest-keyed, session-keyed latch in `.local/emitted.json`, same pattern as the
  obligations announce latch. Anything yigraf would say *differently* re-injects. The single
  highest-value change by measured tokens (~3.5M returned on the field's session shape), at zero
  capability cost.
- **`status` renders index freshness as `behind`, never `stale`** — bare "stale" is reserved for stale
  completions (one word carrying two health dimensions cost a session six commands), and
  `drift --stale` with nothing to show now says "No drift, and no stale completions."
- **`yigraf drift` groups multi-memory loci** — "N memories concern `sym:X` — once re-verified,
  `reaffirm sym:X` clears …" — the flat per-id list read as one command per memory, and the field ran
  fourteen where four locus calls sufficed.

### Fixed
- **`reaffirm --grounding empirical` with standing grounds-drift and no `--evidence` is refused**
  instead of exiting clean over the ⚠ (the empirical gate only checked that *stored* evidence existed,
  so the skill's own recipe silently failed to clear grounds-drift). A bare `reaffirm` that leaves
  grounds-drift standing now says so and names the two verbs that reach it. The skill's §4
  `grounded_by` bullet carries the full working form.
- **The locus form `reaffirm <sym|file>` skips superseded memories** — it re-stamped them, counted
  them in its total, and credited them maturity upholds (re-stamping a node the caller had superseded
  minutes earlier).
- **`pin` refuses a superseded memory, naming the successor** — it answered "SessionStart now injects
  it in full" and injected nothing, correctly but silently, forever.
- **A bare `sym:<path>` (no `#name`) is refused at capture** with the candidate symbols in that file —
  it is never valid, could only land as permanent hard drift, and the field filed it three times in
  one session because the capture "succeeded" and the warning scrolled past.
- The installed skill's frontmatter `description` shrank 709 → 296 chars (it is resident in every
  session's prompt whether or not the skill loads), keeping the closing `status` check.

### Documentation
The release-readiness pass found the docs teaching the exact error this release removes, so they are
part of it rather than a follow-up.
- **`docs/guide.md`'s drift-verb table said a decision whose code "just moved" is a `reaffirm`.** That
  is the `reanchor` case, and the row was the false-mind-change trap in print — the one surface a
  reader consults *because* they don't yet know which verb applies. The table now carries all four
  exits (`link` · `reaffirm` · `reanchor` · `supersede` · `unlink`) with the distinction spelled out.
- **`docs/statusline.md` described the freshness segment as `○ stale` over "committed `graph.json`"** —
  wrong on both halves: `graph.json` was retired in 1.4.0 (mem:059; it is the gitignored SQLite view),
  and `stale` is the word this release moved off that dimension. A doc still calling it `stale` rebuilt
  the very collision the rename fixed. The legend also gained the three `⚠` segments it never
  documented (`conflict`, `stale`, `diverged`) and a note that they are silent at zero, so their
  absence reads as an all-clear rather than a missing field.
- **`docs/mcp.md` documented 6 of 15 MCP tools** and told Antigravity users "yigraf adds 2". Nine tools
  were unreachable-in-practice on the hosts where MCP is the *only* channel. The table is now complete,
  grouped by what the agent is doing (orient · seam · capture · re-verify), and a test asserts every
  registered tool appears in it — the table stays hand-written because it carries *when to reach for*
  each verb, which no generator knows, but it can no longer silently fall behind the surface.

## [1.4.0] — 2026-08-16

**A store's value is bounded by what the agent can be made aware of without already knowing it.**

That sentence is the whole release, and it comes from a second field report — four sessions on the
same repo, the author's agent driving. The report's sharpest moment is a two-line exchange. The agent
had just carefully established that prose-shaped knowledge *is* retrievable, so the only gap was that
it couldn't be pushed. Its principal replied: *"yes, but you will not query memories that you can't
recall because you don't know are there."* That dismantles it. **Retrievable** means "if I ask the
right question, it comes back" — verified working. **Reachable** means "something causes me to ask" —
and that was only ever true for knowledge anchored to a symbol the agent happened to edit. Everything
else was *invisible-but-present*: it counts as coverage in `status` (129 decisions!) while
contributing nothing, and the failure is unfalsifiable from inside the session, because you cannot
notice the absence of something you never knew about.

Per-edit symbol matching answers *"what is relevant to this line?"*. The unanswered and more important
question is *"what would this agent regret not knowing before it starts?"* — which cannot be derived
from a symbol, because no symbol has been touched yet. So session start grows three channels that
deliberately **do not rank**, and every obligation the graph is carrying now reaches it.

The same report also documented the honest half: an agent that read yigraf all session and never
wrote to it, ignoring ~15 consecutive drift warnings — not because the warnings were unclear, but
because they arrived as tool-result context labelled "Context for", which reads as *reference about
the code*, while the competing memory system lived in the system prompt and read as *a rule I am
operating under*. The rules now arrive in the position CLAUDE.md occupies, and for the same three
reasons it works: **once**, **before any action is chosen**, and **as instruction**.

### Added — the three unranked session-start channels
- **House rules, verbatim, before anything ranked** (`session_start.preamble`). yigraf ships a default
  — read the skill before driving the CLI, capture as the work lands, `status` before claiming done,
  one verb per signal — and it is **yours to rewrite** in the committed `yigraf/config.yaml`, so a
  team's conventions ride the repo instead of each agent's private memory. Ranking structurally cannot
  reach this content and no amount of better ranking will: a rule about *using yigraf* has no lexical
  or semantic affinity with a domain intent, which the field verified from the other side — `attest`
  does not promote a node into injection (attested two, re-ran the hook, byte-identical payload), and
  `settled` is earned at read time, not settable. There was simply no channel for it. `""` silences it.
  A user had already built this as a second, git-excluded SessionStart hook; this is that idea adopted.
- **`append_status`** ends the head with the one-line `yigraf status`, so the rules arrive with the
  live counts attached rather than as abstract advice — the detail that made the hand-rolled version
  earn its place on first run. Computed *before* the telemetry overlay, deliberately: the maturity
  verdict rewrites a non-volatile attr, so reading it afterwards would report a spuriously stale view.
- **A pin tier** — `yigraf pin mem:<id>` (`--off` to retire), `remember --pin`, `note-constraint
  --pin`, both over MCP. Pinned beliefs inject **in full**, every session, whatever the session is
  about. Pinning is *routing, not a claim*, so it stays outside the content-addressed memory id
  (mem:063): it changes nothing about what the belief says and must never fork the node from a
  teammate's identical capture. It rides the assertion log, so a teammate's pin is everyone's.
  `session_start.pinned_budget` **binds** and drops the lowest-standing pins loudly — a pin tier where
  everything fits is the next thing to become wallpaper.
- **A titles manifest** (`session_start.manifest_titles`, default 15). Ids and truncated statements
  for the live memories the packet did not otherwise show, ~30 tokens each — the cheapest thing in
  yigraf per token of value, and the direct answer to the exchange above. It converts the store from
  invisible-but-present into a set of known-unknowns, which is the entire precondition for the agent
  choosing to spend a `context` call. Measured on this repo: 686 tokens buys awareness of 129
  decisions. The ids are live handles, which is what the next entry is for.
- **`yigraf show <id>`** — read one node in full, unbudgeted, over MCP too. Every warning yigraf prints
  hands the agent an id, and until now no verb took one: `context "mem:1678ce10…"` tokenizes the hex,
  searches by meaning, and returns whichever nodes sit nearest under a low-confidence banner — an
  answer-shaped non-answer, worse than a refusal. 1.3.1 made this *more* acute by pre-filling ids in
  every drift line. Nothing here is ranked or truncated: a 2500-character `--why` prints whole,
  because that reasoning is what the node exists to survive `/clear` with. `context` handed a bare
  locator now redirects to it (exit 0, with the command) instead of searching.
- **`yigraf drift --stale`** lists the completions `status`'s `⚠ n stale` counts. A count no command
  could print was a dead end — the field had to call `drift.compute_drift` from Python to find out
  what the number meant. Plain `yigraf drift` now also owns up to what it is withholding, so "No
  drift." beside `⚠ 2 stale` stops reading as a contradiction.

### Fixed
- **Every obligation now reaches SessionStart, not just the ones the traversal happened to touch.**
  Drift and stale lines were gated on `in_view` — the hop set reached from the seeds — and a plan drops
  out of that seed set the moment its last box is checked (`_plan_has_open_work`, correctly: a
  finished milestone should not re-cost context forever). Compose the two and a repo that has just
  closed a milestone has **no path** by which a stale completion or a drifted belief reaches the
  agent: it reads as a clean dashboard precisely when a forgotten obligation goes unnoticed longest.
  Measured on yigraf's own graph, which carries 10 surfaced drift and 12 stale completions: **1 drift
  and 1 stale were reachable at session start; 9 and 11 were invisible.** They are now global, like
  the `_capture_gaps` call sitting immediately beside them — which had always been right, for exactly
  this stated reason ("SessionStart is the orientation dashboard for graph health"). Going global
  means going bounded: stale gets `retrieval.max_stale_lines` (default 4) and the same
  count-plus-a-verb tail drift got in 1.3.1. `yigraf context` stays scoped to its topic — that split
  is the point.
  - A second copy of the same hole, one level down: the ranked slice was emitted only `if seeds`, so a
    repo with **no intents at all** and every box checked computed its obligations correctly and then
    threw them away with the empty frame that held them. The slice now renders for anything it has to
    say — nodes *or* a warning.
- **The two drift surfaces stopped disagreeing about the same event.** The hook line was relation- and
  kind-aware; `yigraf drift` printed a bare `soft drift: mem:X → sym:Y (body changed since anchored)`
  that named neither the relation nor a verb. So the surface an agent reaches for *once it knows the
  verbs* — which is the steady state after session one — was the one with no advice on it. Both now
  render from one `retrieval.drift_tail`. The CLI report is unbudgeted, so it also prints **the claim
  itself**: "something moved" never answers whether the belief still holds, which is exactly what
  choosing between `reaffirm` and `supersede` requires, and that forced a read step the tool had no
  verb for.
- **`show` reads a memory's anchors from its artifact, because the graph cannot hold both.**
  Discovered building it: `nx.DiGraph` keeps one edge per node pair, so a memory carrying the *same*
  symbol under `concerns` and under `evidence` projects the second over the first — one of the two
  anchors is invisible to every edge-derived surface. That is the mechanism behind the field's
  "reaffirm cleared it and it still drifts" session: each `reaffirm` form updated a different list,
  both reported success, and the memory looked permanently drifted. Files are truth (design law #6),
  so `show` compares each stored anchor against its target directly and prints both lists with their
  own drift state. (The locus form of `reaffirm` still searches only `concerns` — see below.)
- **The `context` footer carries the obligation counts.** `[~3996 tokens · 31/37 nodes shown · ⚠ 8
  drift · 11 stale]` — because the footer is the one line a truncating caller keeps. An agent piping
  `context` through `| head -35` (a reasonable thing to do with a long packet) cut off the ⚠ Stale
  block, which renders near the end, and missed real obligations for a whole session.
- **A dangling `contains` no longer kills a fold** (from the yigraf-server line, where it 500s a
  project overview). `denormalize_danglings` indexed `_TYPED_DANGLING[relation]` directly and had no
  `contains` entry, because `project_into` never produces one — a plan and its tasks come out of the
  same file, so locally the target is always there. The *fold* can: a plan assertion arriving without
  the task assertions it names (a partial replica, or a `since=` pull that starts after them). One
  unresolved edge became "this project has no view at all", the exact opposite of what stashing an
  unresolved edge is for. `contains` is now in the map, and an unknown relation falls back to
  `dangling_<relation>` rather than raising — every reader looks a key up by name, so an unclaimed one
  is inert.

### Changed
- **SessionStart is no longer silent on a graph with nothing in it.** Silence was right while every
  channel ranked — nothing to rank, nothing to say — but the preamble does not rank, and an empty
  graph is the limit case of the problem it exists for: the agent that most needs "capture as the work
  lands" is the one whose repo has captured nothing. The ranked frame stays absent, so the packet
  costs only what the rules cost. Design law #4 survives as an **opt-out**: silence the unranked
  channels in config and an empty graph is mute again.
- **All three new channels are charged to the budget, never added to it.** The 1.3.1 lesson was that a
  block outside the budget does not merely overrun, it *starves the render*; three appended blocks
  would have re-entered that failure three times. A bloated preamble must visibly cost the ranked
  content it displaces. The manifest is built **last** and trimmed to what the render actually left,
  rather than reserved for at a guessed worst case, so a wrong guess costs a few tokens of slice and
  can never overrun. Measured on this repo: 3946 tokens against the 4000 budget, of which 375 is the
  rules + status line and 686 the 15 manifest titles.

### Documentation
- **The skill's `description` now carries the closing check** — in Claude Code that string is injected
  into the skill listing every session while the *body* is read only on invocation, which makes it the
  only always-on surface, and it stopped at "context / link / remember". So §4's drift/stale/conflict
  guidance never reached an agent that had learned those three verbs and was driving the CLI directly
  — the steady state after session one, and the documented cause of a session that missed 1 drift and
  2 stale entirely. It now also says *read this skill before driving the CLI* and *up to date means no
  drift AND no stale*.
- **§4's "You never poll for these" is corrected.** It was the wrong steer for a closing check, and
  the agent followed it: the hooks are scoped to the file, `context` to the topic, and **`yigraf
  status` is the authority** — the only surface reporting every count unconditionally. New §0b says so.
- **`attest` is documented as a capability, not only as a dead end.** It appeared twice, both inside
  the pending-conflict bullet as something the agent *cannot* do, so there was no way to learn that
  capturing an elicited preference-fork is a supported move.
- **The division of labour with a host's own memory is stated.** A yigraf memory is retrieved by
  relevance and anchored to code (durable, topical, and the only one that can tell you your own edit
  invalidated it); a host's project memory is loaded verbatim every session (small, always-on).
  Anchored-and-topical → yigraf; small-and-universal → host memory, or `--pin`.
- **Region anchors are motivated for a file that *grows*.** The skill sold them as "so an unrelated
  edit elsewhere doesn't drift it", which doesn't obviously cover an append-only log — where a
  whole-file anchor drifts on every append and costs five reaffirms of a claim nothing falsified.

### For anything that consumes the fold
- **`pinned` is now a reserved node attribute on the memory family**, and it rides the assertion log —
  so it reaches every client that folds it, not just this CLI. Worth stating because `pinned` is a
  plausible name for a *local* flag: a viewer that spreads fold attrs onto its own per-node objects can
  shadow it, or be shadowed by it. (Caught in exactly that way downstream — a force-directed graph
  console had used `node.pinned` for "don't integrate this node during layout" since well before this
  release, so a pinned memory would arrive pre-frozen and sit at its seed position looking like a
  layout bug.) It never affects identity: pinning is deliberately outside the content-addressed memory
  id, so a node's id is unchanged by being pinned and a server that stores assertion bodies verbatim
  passes it through untouched.
- **Inside yigraf, the word now means only that.** `_render`'s per-packet "place this first because a
  warning names it" set was also called `pinned`; it is `must_show` now. A field report had already had
  to disambiguate the two by hand once, back when only the local existed.

### Still open from the report, deliberately
`reaffirm <locus>` matches only `concerns`, never `grounded_by` (`show` now at least makes the split
visible); nothing reports a dangling `grounded_by` ref on a live belief, so `unlink` still has no
trigger; the `Stop` hook counts new obligations rather than omissions ("0 memories captured across 11
commits"); an unresolved `file:` anchor still says "typo?" without checking whether the path exists on
disk; `--evidence` is not sanity-checked against a dated observation it postdates; and `remember`
still echoes a bare id.

---

## Also in 1.4.0 — three unrelated lines of work

Landed since 1.3.1 and unreleased until now. A workspace yigraf cannot write to is now a condition it
survives and explains rather than one it crashes on — both caches under `yigraf/` are *derived*
(design law #6), so losing either write can never cost an answer, yet either one ended the command in
a raw storage traceback. Three more hosts reach Tier A, two of them through a shared context file
yigraf may only fence a section of. And the eval harness can finally produce an honest number, which
it could not do before — including one about yigraf that is unflattering.

No behaviour changes on a writable workspace, and none at all for a host already wired.

### Added — Kiro, Gemini CLI, and GitHub Copilot (Tier A)
- **`install-kiro`, `install-gemini`, `install-copilot`** — three more ambient-rule hosts, each still a
  thin wrapper over the host's own seam, each at the tier that seam allows (`int:host-push-adapters`).
  Kiro has a rules dir (`.kiro/steering/`) and takes the existing shape unchanged.
- **A shared context file is fenced, never clobbered.** Gemini CLI and Copilot have no rules dir: their
  always-on context is a single document the user also writes in (`GEMINI.md`,
  `.github/copilot-instructions.md`). Overwriting one the way a dedicated rule file is overwritten
  would eat the user's own instructions, so `AmbientRuleHost.shared` routes them through the same
  `yigraf:start`/`yigraf:end` non-clobbering writer `AGENTS.md` has always used. Re-installing refreshes
  the block in place; everything outside the fence survives.
- **Copilot is explicit-only.** `.github/` exists in nearly every repository and Copilot's extension dir
  is version-globbed, so no marker exists that would not false-positive almost everywhere. It is never
  auto-detected — reach it with `install-copilot` or `--host copilot`.

### Fixed
- **An unwritable `yigraf/.local/` no longer takes down `build` — or, worse, `context`.** A read-only
  `.local/` (a restrictive umask, a full disk, a `graph.db` left root-owned by a `sudo yigraf` run)
  raised `sqlite3.OperationalError` straight through Typer: `yigraf build` **and** `yigraf context`
  both exited 1 on a ~40-line traceback. The read path was the sharper break — a `context` query whose
  answer was already computed failed because its *cache* could not be refreshed, which is exactly the
  fail-open guarantee design law #5 makes to hooks. `graphdb.materialize` now raises a typed
  `ViewUnwritable` carrying the fix, and both seams degrade to an uncached rebuild: reads answer
  normally and silently, `build` prints its real index counts and then the guidance at exit 0, and a
  capture (`remember`, `link`, …) warns but still reports the artifact it already wrote to disk. The
  guidance leads with *nothing was lost* — `graph.db` is a projection of the markdown, and an agent
  that doesn't know that reads any write failure as data loss. The catch stays narrow (`OSError` +
  `sqlite3.OperationalError`), so a genuine bug still surfaces as itself.
- **An unwritable `yigraf/cache/structure.json` no longer takes down the same two commands.**
  `StructureCache.load` had always started empty on an `OSError`; `save` had no such guard, so one
  read-only parse cache raised `PermissionError` from `cache.py` during `build_graph` — before the
  materialized view was ever reached. It now fails open to a re-parse, silently: any condition that
  refuses this write refuses the view in the same workspace, and that surface already names the path
  and the fix, so the operator hears about it once (design law #4). A fully read-only `yigraf/` now
  builds and queries cleanly, emitting exactly one line of guidance.
- **`yigraf install` gave every Gemini CLI user an `.agents/rules/` dir their host never reads.**
  Antigravity claimed the broad `~/.gemini` as a home marker, but Antigravity ships *under* that
  directory — its MCP config lives at `~/.gemini/antigravity/` — so the marker matched every Gemini CLI
  install and wired the wrong host's rule file. Antigravity's home marker narrows to
  `.gemini/antigravity` (or its own `~/.antigravity`), and the broad `~/.gemini` now belongs to Gemini
  CLI. The reverse overlap stands and is deliberate: an Antigravity user *does* have `~/.gemini`, so
  both get wired — which is exactly the documented wire-all-detected behaviour.

### Changed
- **The eval harness reports what an agent actually spent.** Tokens were summed per assistant turn
  "for robustness across Claude Code versions"; measured against a live run, that is wrong in *both*
  directions. A streaming turn carries a **partial** `output_tokens` (observed `3, 3, 3, 1` → "10" for
  an answer whose real total was **814**, ~80× under), and every turn repeats the same
  `cache_read_input_tokens`, so the prompt prefix is counted once per turn (162,973 reported against
  64,354 actual, ~2.5× over). The count now comes from the final `result.usage`, with the per-turn sum
  kept only as a fallback for a transcript that has no result object. A robust reading of the wrong
  quantity is still the wrong quantity.
- **The harness runs three arms, on a repo that is not yigraf's own.** yigraf's `CLAUDE.md` and
  `AGENTS.md` instruct any agent to run `yigraf context`, so even a hookless arm reached for the tool
  and the delta collapsed to ~0 by construction — the benchmark could not produce an honest number
  about its own subject. Cases now run against an external repo (`encode/httpx` @ 0.28.1, rebuilt from
  scratch by `scripts/eval/external/setup-httpx.sh`), and the two arms become three: full install,
  docs-only, and no yigraf at all. The middle arm is what makes the result falsifiable.

### Documentation
- **README states what was measured, including the part that did not work.** Over 10 popular
  open-source repos, 960 runs on the floor model: asking why code is shaped the way it is costs 0 tool
  calls / 38k tokens / 11s with yigraf, against 12.5 / 266k / 63s without. But a single line in
  `CLAUDE.md` — "run `yigraf context` before changing code" — scored the *same* 6/8 on edit-time
  re-verification as the hook did, so yigraf's most distinctive mechanism bought nothing measurable
  over simply telling the agent to ask. One case, one model, n = 8: an open question now, not a claim.

### Upgrading to 1.4.0
- **Nothing to do, and no graph changes.** No wire change, no node-id change (pinning is deliberately
  outside the content-addressed payload), no change to any graph a rebuild produces. A host already
  wired keeps its existing rule file untouched; the antigravity marker fix only affects what a *future*
  `yigraf install` auto-detects, and an `.agents/rules/` dir a previous run left in a Gemini CLI repo
  is inert and safe to delete.
- **Re-run `yigraf install`** (or `install-claude-hooks`) to refresh `SKILL.md` and the `AGENTS.md`
  block with the new guidance. Idempotent and non-clobbering, as before.
- **Your session-start packet will look different**, and that is the release. Expect the house rules
  at the top, the live `status` line under them, every outstanding obligation (not just the ones the
  traversal reached), and a titles manifest at the bottom. It stays inside the same
  `retrieval.query_token_budget`, so the ranked slice shrinks by roughly what the new channels cost —
  measured on this repo, 375 tokens for the head and 686 for 15 titles, out of 4000.
- **To tune it**, `yigraf/config.yaml` gains a `session_start:` block (`preamble`, `append_status`,
  `pinned_budget`, `manifest_titles`) and `retrieval.max_stale_lines`. Existing config files keep
  working untouched — anything absent falls back to the defaults. Rewrite `preamble` to encode your
  own conventions; set it to `""` to silence the channel.
- **If you were running a hand-rolled second SessionStart hook** to tell your agent to read the skill,
  you can retire it: that is what `session_start.preamble` + `append_status` now do.

## [1.3.1] — 2026-08-13

Six fixes from the first field report on the 1.3.0 shared-log line (one developer, one repo, a day of
heavy use) — every one a case where a surface reached the agent unbidden and made its next action
worse. No new capability; local, unlinked workspaces are unaffected.

### Fixed
- **`status`'s `⚠ n diverged` count no longer ratchets upward on ordinary solo work.** Divergence's
  test was "declined, and its id is not in the current files" — but for a revisioned family
  (`int:`/`task:`) the id *is* the revision, so every edit to an already-pushed plan or intent left
  its previous revision in the log matching that test exactly: a disagreement with nobody. Re-linking
  8 stale completions on yigraf's own single-actor log produced 8 phantom, unclearable divergences.
  `OnlineLog.superseded_revisions` now triages the declined set: an id the same actor has since
  replaced with the live revision is that actor's own history, not a second principal's copy — keyed
  on `(locator, actor)` and strictly-earlier arrival, so a genuine disagreement from another principal
  is never filtered.
- **The ✔ proof-obligation block was emitted in full, outside the render budget.** `_render` counted
  it into `used` but never bounded it, so on a heavily-governed locus `used` began past `char_budget`
  and every node's fit-test failed before a single symbol was placed — measured before: `cli.py`
  injected 3833 tokens against an 800 budget, 0 of 86 nodes rendered. Obligations now take a share of
  what the ⚠ warnings leave, admitting whole governing intents in governance-density order; the drift
  block caps the same way (hard drift first, tailing to the uncapped `yigraf drift`); the render frame
  itself is now charged. Repo-wide after: every packet ≤ 796/800, nodes rendering everywhere.
- **`reaffirm --evidence` could upsert a `grounded_by` ref but never retire one.** A ref whose target
  was deleted had no verb that could clear it, so an `·empirical` belief went on citing evidence that
  no longer existed. `unlink mem:<id> <ref>` retires it — refusing to strand the belief by declining
  to retire its last remaining ref.
- **A `file:` anchor was write-only at the moment of action.** `remember --concerns file:docs/x.md`
  was accepted, stored, and answered by `yigraf context` — but the PostToolUse hook discarded the
  answer before asking, because `.md` isn't an extracted language. The gate now admits a file with a
  hand-placed `file:` anchor node even when its suffix isn't indexed; an un-anchored `.md` still stays
  silent.
- **`status`'s context percent traveled without its denominator**, so `ctx 94%` on a 1M-token host
  read as "nearly out of room" while the host's own readout said 24%, 764k free. Both renders now
  trail the percent with the physical pair (`ctx 94% 236k/1M`); the TTY status line adds a
  self-silencing note spelling out what the percent is of.
- **A moved symbol's stale `implements` entry had no verb that could clear it.** `link` keys by exact
  locator, so re-linking after a move appended a new entry and left the old one as hard drift
  `reaffirm`/`supersede` couldn't touch. `unlink` now retires it — exposed over MCP too, so a
  pull-only host can clear a stale link.

### Changed
- Drift/reconcile lines now carry the resolving verb with ids pre-filled and are kind-aware
  (`reaffirm` is never offered for hard drift, which it cannot re-anchor) — the one surface that
  reaches the agent unbidden had been suggesting "re-`remember` or `supersede`", which `SKILL.md`
  forbids and the write-time dedup guard refuses.
- `.gitignore` now covers the root-level twins of yigraf's own runtime caches (`/.local/`, `/cache/`),
  which appear when a command resolves its workspace root one level off.

### Upgrading
- Nothing to do. No wire change, no node-id change — a rebuild produces an identical graph. A
  workspace already showing phantom `diverged` entries from its own re-links will show 0 after its
  next `status`/`sync`.

## [1.3.0] — 2026-08-06

1.2.0 made a shared log *possible*; this release makes the three seams it exposed actually hold. Two
of them were silent — the failure mode was a workspace that believed it had synced, or had cleared
drift, and had not. Binding is no longer three hand-edited settings that nothing checked against each
other. Local, unlinked workspaces are unaffected by all of it: node ids, the fold's verdict, and every
graph a solo repo builds are identical to 1.2.0.

Minor, not major: **2.0 stays reserved for the hosted line.**

### Added — `yigraf online` (workspace binding)
- **`yigraf online <link-url>`** — redeem a single-use link code, generated in the web console, for a
  per-machine token; then bind. It replaces hand-writing `online.project`, `online.remote` and a
  `YIGRAF_TOKEN` export, which was three chances to bind to the wrong project with no check that any
  of them agreed. Humans do all identity work in the browser: there is no OIDC client here, no
  callback port, no refresh, and a self-hoster runs the identical flow against their own server.
- **The code is a redemption code, not the credential.** If the pasted string were itself the bearer
  token, every assertion authored through it would carry the same `actor` and the audit trail would
  say nothing. The machine token it returns goes to `~/.config/yigraf/credentials.json` at mode 0600,
  keyed by host — never `config.yaml`, which is committed. `$YIGRAF_TOKEN` still takes precedence,
  which is what keeps CI working with no interactive link step (a link code is single-use and lasts
  ~15 minutes, so it is the wrong shape for a pipeline; reveal a token in the console instead).
- **Three checks, on a side-effect-free preflight** so a failure never burns the user's single-use
  code. *Repo identity* compares root-commit SHAs — a remote URL changes on rename, re-host or org
  move and the root commit survives all three — because the shared graph is full of
  `implements`/`concerns` edges anchored to code symbols, and binding to a project about a different
  codebase leaves every one of them dangling: the graph still folds, still renders, and is quietly
  meaningless. *Wire version* refuses a bind that could not round-trip, rather than risking it (no
  `--force` there, deliberately: a repo mismatch is a judgement call, an unsupported wire is not).
  *Replica state* moves a mirror already carrying another project's cursor aside under `--force` —
  renamed, never deleted.
- **`yigraf online` with no argument, and `yigraf whoami`** — am I connected, and as whom. One call to
  the server, so the answer never requires reading a graph, and it is the fastest way to tell "my
  token is wrong" from "my project name is wrong", which otherwise look identical.
- Every way the server can refuse — unknown, expired, spent, revoked code; a human invitation pasted
  in place of a machine link code; a non-member — is translated into a specific correction at exit 0
  (design law #1), never a status code.
- **`sync.WIRE_VERSION`** (= 1) — the version of the four wire shapes, advertised by the server and
  compared at bind time. A new *optional* field old clients ignore is not a bump; a renamed, removed
  or re-meant one is.
- Config: `online.repo_fingerprint` — written by `yigraf online`, safe to commit (it is a public git
  SHA), and re-derived by `yigraf sync` before every push. That catches the one case bind-time cannot:
  a `config.yaml` copied into a different repository.

### Fixed — edits stopped propagating once a locator had been pushed
- **Intents and tasks now carry a revisioned assertion id** (`int:<slug>@<hash>`,
  `task:<plan>/<n>@<hash>`) with the locator in the body. mem:063 defines an id as the content-hash of
  its body — two writers who say the same thing collapse to one event — and these two families broke
  it, keying on a slug or a positional locator while their *mutable* state (a task's `[ ]`/`[x]` and
  its `implements` anchors, an intent's `status`) lived in the body. Consequence: `yigraf sync`'s push
  set is `a.id not in known_ids`, so once a locator had been pushed, **every later edit was skipped as
  already-known** — `link` re-anchors, completions and `--status satisfied` silently never propagated,
  and where a revision did reach a replica, `merge_assertion`, `causal_order` and the fold each picked
  a different winner. The fold materializes the node under `body.locator`, so `task:plan/1` is still
  the node every cross-family edge targets and nothing downstream changes.
- **Causal parents are rewritten from locators to the revision ids they name.** A parent must name an
  *assertion*; without the rewrite the online log's prefix-closed ingest check would reject every
  dependent assertion, and `causal_order` would silently drop the ordering constraint that makes edges
  resolve in one pass.
- **A replica may no longer revert what the working tree says.** All four authored families are
  git-committed files (design law #6), so a replica assertion naming a node this workspace already
  materialized is declined — `fold_assertions` gains `defer_families`, and the *caller* states the
  policy because the fold is family-agnostic. Without it, `_fold_replica` running after the local fold
  let a teammate's older snapshot undo local completions; and because `memory.memory_id` hashes what a
  memory *claims* and deliberately not its drift anchors, the replica's pushed copy overwrote an
  anchor `reaffirm` had just re-stamped — so `yigraf drift` re-reported drift the principal had just
  cleared, and no amount of reaffirming could clear it. The test is per-**node**, not per-family: a
  teammate's belief you do not hold folds in exactly as before.
- **`yigraf install` no longer promises a download that later happens at the worst moment.** fastembed
  caches into `$TMPDIR`, and macOS reaps `/var/folders/…/T` by access time: the ~130 MB ONNX blob is
  evicted while the kilobyte metadata files survive, leaving a *dangling snapshot symlink*, so every
  later load silently re-fetched it through `hf_xet` with no wall-clock bound — a `remember` hung 10+
  minutes at 0% CPU. Two guards, because either alone is insufficient. `embeddings.model_cache_dir`
  pins the artifacts to `~/.cache/yigraf/models`, somewhere the OS does not reap, so "downloaded once"
  means once. And every *implicit* path — `get_embedder`, therefore every `context`, `remember` and
  hook — now opens the model `local_files_only`, so a cache miss costs a lexical fallback rather than
  an unbounded download on the agent's critical path (design law #5). Fetching becomes an explicit
  verb, `fetch_model`, run by `yigraf install` where the caller is already waiting on setup and the
  wait can be reported.
- **The drift report's "also affected" ripple re-surfaced what the direct path deliberately withheld.**
  Every ripple line ends in "re-verify it still holds", so a node with no honest re-verification must
  not appear there — and three did. `is_surfaced` withholds a done task's `implements` drift precisely
  so the agent is never asked to rubber-stamp a closed task (`int:drift-done-suppression`), and
  reverse reachability handed it straight back one call later, re-framed as a reconcile prompt and
  double-counting what `stale` already reports. New `drift.is_reverifiable` is the node-shaped
  counterpart, stated per-node so it also covers a done task reached by a *derived* relation
  (`depends_on` over `implements ∘ calls`), which the edge-shaped test never sees; superseded memories
  and archived intents are the same shape. Measured on yigraf's own graph when this landed: 10 of 11
  ripple lines were unactionable — the section was ~9% signal.

### Added — divergence, the case design law #6 assumed git would clean up
- **`⚠ n diverged` in `status`, and a named list at the end of `sync`.** "The local file wins" is a
  complete answer only while the losing copy survives somewhere. In a repo that *commits* its
  `yigraf/` artifacts it does — two machines editing one plan is an ordinary git merge on the
  markdown. In a repo that gitignores them (yigraf's own does, and any repo may) there is no merge
  point, so declining the replica's revision discards the only other copy permanently, with each
  machine convinced it is current. The declined set is therefore inspected rather than dropped: an
  assertion whose id this workspace also authored is a harmless echo, one whose id is unknown is a
  locator two workspaces genuinely disagree about. The fold's verdict is unchanged either way — what
  changes is that the discarded locator is named instead of vanishing, and the guidance forks on
  whether git actually holds the other side. Silent when there is none (design law #4).

### Changed
- Config gains `embeddings.cache_dir` (empty ⇒ `~/.cache/yigraf/models`; `$FASTEMBED_CACHE_PATH` is
  honoured as an explicit choice) and `online.repo_fingerprint`. Both default to the prior behaviour.
- `embeddings.status()` reports `cache_dir`; new `embeddings.model_cached()` is the honest form of "is
  semantic recall on" — `backend_available` only says the *library* imports, and the gap between the
  two is exactly the silent-lexical state this release closes.

### Upgrading
- **Local-only workspaces: nothing to do.** Node ids are unchanged (the locator), so a rebuild
  produces an identical graph.
- **A workspace that already pushed under 1.2.0** will re-push every intent and task under its new
  `@<rev>` id, so a shared log ends up holding both the old fixed-id copies and the new revisioned
  ones. Merging is a commutative set-union and nothing is lost or overwritten, but the older copies
  remain as inert history. No public server exists yet, so this is expected to affect no one; it is
  recorded because a shared log's contents should never be a surprise.

## [1.2.0] — 2026-08-04

The first release in which yigraf is **usable by more than one person at a time** — and still, by
default, entirely local. Nothing here opens a socket unless you configure it to: `online.project` and
`online.remote` ship empty, `yigraf sync` says so and exits 0, and a workspace that never links behaves
exactly as 1.1.1 did. The **2.0** number stays reserved for the hosted line; this is the client half,
and it is additive.

### Added — resolution across a team (`int:team-reconciliation`)
- **`resolution.py` — verdicts are first-class appends.** `reconcile` / `supersede` / `dispute` are now
  authorable by a principal who owns *neither* belief. The verdict names both operands by id and
  projects the resolving edge between them, so it needs write access to no one's files. This is what a
  conflict only its own authors may close costs you: it deadlocks the moment one of them leaves.
- **`fold._apply_projection`** — the one place an assertion may emit an edge between two *other* nodes,
  with shadow-protection when two verdicts compete for an ordered pair. Verdicts are read back off
  resolution *nodes*, never the projected edge, so a dispute and a later reconcile both count in either
  operand order.
- **`yigraf dispute`** — nominate two beliefs as contradictory: the durable "open a PR" step. A
  nomination is an assertion, so it rides the log and every client sees it. `contradiction` unions
  these with the cosine sweep, which matters because the sweep is index-derived and fails open to
  silence — right for one developer, wrong for a team, where the same merged log must yield the same
  open set everywhere.
- **`extract._fold_replica`** — a teammate's belief folds onto your **local** structure base, so their
  intent anchored to `sym:foo` drifts when *you* edit `foo`. Only assertions cross the wire; structure
  stays locally derived, so the shared log never needs a copy of anyone's code.
- **`responsibility.py`** — whoever pushes second merges. Of two conflicting beliefs the higher `seq`
  was written into a world that already contained the other, so its author owes the reconcile. Derived
  from the log's existing order, never a stored assignment; identity comes from the server-stamped
  actor, never a client's claim.

### Added — the principal's notice channel (`int:obligation-notice`)
- **A `Stop` hook that names newly-unresolved obligations to the human, once, with the command that
  clears each one.** The statusline already counted conflicts, stale completions, and drift, and that
  count reliably produced no action: a warning present on every refresh reads as furniture within a
  day, and it carries neither a locator nor a verb. `obligations.py` re-shapes what `stale_completions`,
  `detect_conflicts`, and `compute_drift` already return — no new detection, no new thresholds — and
  diffs them against a session-keyed latch in gitignored `.local/`.
- It returns **only** the universal `systemMessage` field. Never `decision: "block"` (design law #5 is
  unconditional, and the sharpest obligation here — a pending supersede of a human-attested node — is
  one the agent structurally *cannot* clear, so a gate would deadlock); never `additionalContext`
  (mem:012 keeps human-facing graph health off the agent's budget). Edge-triggered, so `/clear`
  correctly re-announces what is still open and resolution stays silent.
- Config: `status.obligation_notice` (`true`) and `status.obligation_notice_max` (`5`).

### Added — the online client
- **`yigraf sync`** — pull the team's delta, push what the log hasn't seen. The pulled delta's Merkle
  links are re-derived client-side before anything is folded in, so a server that dropped, reordered,
  or forged an event is caught here. Push is idempotent by `event_key`, and needs no queue: the push
  set is re-derived every run as the git-committed file log minus the replica's known ids, so an
  assertion that never landed simply goes out next time. (A queue in `.local/` wouldn't survive a
  clone, and would be a second source of truth to reconcile.)
- Config: an `online:` block (`project`, `remote`, `replica`) — all empty by default. The bearer token
  comes from `YIGRAF_TOKEN` and never from `config.yaml`, which is committed, and a token in git is a
  leaked token.
- `maturity_survival_floor` — an optional git-durability gate on promotion to `settled`.

### Changed
- **`reconcile` now always authors a resolution append**, rather than writing `equivalent_to`
  frontmatter onto the left belief when it happened to be local. That silently broke the `memid-v1`
  invariant: `memory.memory_id` does not cover `equivalent_to`, so the edit changed an assertion's
  *body* while leaving its *id* fixed — two different bodies sharing one id, which `yigraf sync`
  (identifying by id) could never see, so the reconciliation stayed local forever. Legacy frontmatter
  is still **read** for compatibility, and deliberately does not block re-authoring, so a pre-sync
  workspace can promote its old local reconciliations to real appends.
- **`maturity_survival_floor` abstains where survival cannot be measured.** `survival` scores 0 both
  for "landed in the tip commit" and for "git has never seen this file". Read as a quantity that
  conflation is conservative and correct; read as a *gate* the same 0 inverts, so in any workspace
  whose artifacts are untracked an armed floor meant nothing could ever settle, silently and forever.
  A gate that cannot be evaluated must not be the thing that denies. `build` now warns when a floor is
  armed but unmeasurable.

### Fixed
- **A failed push was an unhandled traceback.** `HttpRemote._request` let raw urllib errors escape and
  the sync loop caught only `IngestRejected`, so being offline crashed rather than reported. New
  `RemoteUnavailable` is kept distinct from the other two because all three want opposite handling: a
  chain break is an integrity stop (exit 1, replica untouched), a rejection is permanent (reported
  per-assertion, the run continues), and this one is weather — say so and let the next run carry it.
- **A refused credential reached the operator as a 114-line Typer traceback.** `HttpRemote` re-raises a
  non-429 4xx as itself on purpose — a bad token fails identically on every retry, so it must not read
  as "try again later" — but that is a *transport* contract, and `cli.sync` never caught it. A 401,
  403, or 404 is now `_guidance` at exit 0, the same contract the missing-token and unset-config gaps
  already had: all three are one misconfiguration the caller can fix and re-run. The 404 message
  deliberately does not guess between "no such project" and "you are not a member", because the server
  answers both identically so that membership is not an existence oracle.

### Documentation
- **The guide gains a "Working with a team" section** — linking a workspace, what crosses the wire and
  what doesn't, resolving a conflict you didn't author, and whose turn it is.
- **`SKILL.md` §4 taught drift only.** `reconcile` and `attest` are live verbs the skill never named,
  so an agent told to resolve a conflict had to guess. It now covers all three re-verify signals and,
  for a pending conflict, says plainly that the agent cannot clear it.
- Retired the pre-mem:033 "maturity is git-derived / settled after K commits" claim from the four
  places still carrying it (`counters.py`'s module header, `extract`, `cli`, `graph`). Promotion has
  been a read-time verdict over sidecar upholds since mem:047; the header described the model mem:033
  replaced, which made it actively misleading next to the code it headed.

## [1.1.1] — 2026-08-01

Follow-ups to the 1.1.0 typed edge algebra from a review of that release, plus a
documentation pass. No new capability — every change here makes yigraf match what
it already claimed.

### Changed
- **`serves` now rejects a task target.** Its signature was the bare `plan`
  *family*, which also admits `plan/task` — so `remember --serves task:x/1`
  landed silently while the command's own guidance said only `int:<slug>` or
  `plan:<slug>` were valid. The signature is now `plan/plan`, matching what the
  guidance always claimed. A task is a unit of work, not a goal; pin a decision
  to a task's code with `--concerns`.
- **The `yigraf drift` blast-radius section reads `also affected (verify these
  too)`**, not `transitively affected`. The section was never all-transitive: a
  depth-1 hit is a *direct* edge onto the drifted locus that `compute_drift`
  didn't report (it reports an edge only when that edge's own anchor stopped
  matching). Each line now states its composed relation as an arrow plus a hop
  count — `mem:abc —concerns→ sym:a.py#f (extracted, direct)` versus
  `task:m/1 —depends_on→ sym:a.py#f (inferred, 2 hops)` — so an agent can tell
  an asserted anchor from a derived entailment without decoding the heading.

### Fixed
- Removed a dead `contextlib` import left in `onlinelog.py` when
  `PostgresAssertionStore` moved out, and corrected two docstrings that still
  described it as shipping here.
- `relations.Reach` documented `path[0]` as reaching `target`, which is false for
  a reverse walk — there `target` *is* `path[0]`. The docstring now states both
  directions.

### Added
- `reach()`'s dominance pruning is now pinned against a brute-force oracle over
  both walk directions, including dense cycle-rich graphs. The prune is only
  sound because bottleneck confidence is non-increasing while depth is
  non-decreasing, and its failure mode is silent — a wrong prune drops a
  blast-radius hit rather than raising.

### Documentation
- **Code comments no longer describe `graph.json` as the live committed
  projection.** mem:059 retired it for the gitignored SQLite materialized view,
  but the comments never followed. `counters.py` was the worst: its module
  docstring opened on *"v0 keeps `graph.json` fully recomputable"*, explained
  that branches reconcile through a union-merge driver no longer registered, and
  pointed the shared-counter model at *"v1 / Enterprise"* work that is now 2.0
  (`int:yigraf-online-v1`). `graph.py` asserted outright that `graph.json` is
  committed. Corrected across `counters.py`, `graph.py`, `cli.py`, `memory.py`,
  `extract.py`, `update.py`, and `status.py`. Anything describing the retirement
  *accurately* was left alone — `graphdb.py`, the ignore entry for a stale pre-1.0
  file, and the hidden `graph-merge` command; `merge_node_link` keeps its wording
  but is now labelled LEGACY, since that command is its only caller.
- **The guide documents the drift blast radius**, which shipped in 1.1.0
  undocumented: how to read `node —relation→ target (confidence, hops)`, why an
  `extracted, direct` hit appears there rather than in the drift lines above it,
  and that only soft drift ripples.
- The 1.0.0 entry below listed two extras, `[embeddings]` and `[mcp]`, **neither
  of which has ever existed** — both are core dependencies. Corrected in place.
- `docs/guide.md` no longer hardcodes a test count, and the landing page reads
  `v1.x` rather than a pinned version, so neither can drift again.

## [1.1.0] — 2026-08-01

Still the **local** engine (`int:yigraf-local-v1`). The hosted, multi-user line
remains **2.0** — see the 1.0 **Roadmap** below; nothing here moves toward it.

### Added — the typed edge algebra (`relations.py`)
- yigraf's arrows always carried an *implicit* signature (`implements` goes
  task→sym, `serves` goes memory→intent, `calls` goes function→function), but
  nothing named the type. That grammar is now explicit, and it buys two things a
  hand-rolled traversal can't:
  - **Composition** — a partial `compose(r1, r2)` says which relation you get by
    following one edge then another. `implements ∘ calls ⇒ depends_on` means the
    graph *entails* facts nobody wrote down, and a path that stops composing is
    pruned rather than walked.
  - **A confidence semiring** over `EXTRACTED > INFERRED > AMBIGUOUS` — weakest
    link along a path, best across alternative paths. A derived multi-hop edge is
    capped at `INFERRED`, so a query can always tell "someone linked this" from
    "the graph inferred this."
  Everything in the module is read-time and pure: a derived relation is never
  persisted, because persisting it would make an entailment look like a claim.
- **`yigraf drift` now reports blast radius.** Past the directly-anchored drift,
  it names the governed nodes that only *transitively* depend on a drifted symbol
  — a task whose implementing code merely *calls* it, a memory concerning its
  container — under a new `transitively affected (verify these too)` heading.
  Additive and gated: with no cross-family edges to ripple, it prints nothing
  (silence is a feature).
- **The edge grammar is enforced at the write boundary.** An ill-typed plan edge
  now raises before it reaches disk instead of landing and being flagged later by
  the read-time audit; `remember --serves` rejects a wrong-typed target (a
  `sym:`, a memory id) with guidance and exit 0, where it previously only
  warned about a non-existent one.

### Fixed
- `intent`, `supersede`, `plan`, and `remember` no longer fail on a workspace
  whose subdirectory hasn't been scaffolded yet — the destination directory is
  created on write.

### Removed
- **`PostgresAssertionStore` and the `[postgres]` extra.** The MIT engine now
  ships only the `AssertionStore` *port* plus the stdlib `SqliteAssertionStore`
  reference adapter; a hosted deployment supplies its own concrete adapter and
  pulls its own driver. Keeping the substrate out of the public package is
  deliberate — the engine has no server-only dependencies, and storage is the
  deployment's concern. The single-sourced contract still holds because the port
  stays here, and adapters are checked against it.

  This is the one behavior change that can break an existing install, and it
  breaks *quietly*: `pip install yigraf[postgres]` still succeeds under 1.1.0 —
  pip and uv treat an unknown extra as a warning, not an error — but it now
  installs no driver, so the failure surfaces later as an ImportError rather
  than at install time. If you were pulling psycopg that way, depend on it
  directly. It is versioned as a minor rather than a major because the adapter
  was scaffolding for the unreleased 2.0 hosted line — never wired into any
  local command, and reachable only by a deployment that would now supply its
  own.

## [1.0.0] — 2026-07-16

First stable release.

**yigraf 1.0 is the _local_ engine**: the complete AGM+JTMS belief-revision graph
over code, intent, plan, and memory, running self-contained inside a single
repo/folder with **no network**. The source of truth is an append-only,
content-addressed set of assertion files committed to git (git-union-merges for
free); the queryable graph is a gitignored, recomputable SQLite materialized view.
Multi-user / hosted operation is the 2.0 line — see **Roadmap** below.

This release promotes the project's design contracts to `satisfied`
(26 intents), verified by a fully green offline suite (546 tests) and a
fresh-repo end-to-end run of the working loop.

### The graph — four node families + cross-family edges
- **structure** — files, modules, symbols, and calls from tree-sitter, with a
  reformatting-stable, AST-normalized content hash (`structure-index`).
- **intent** — the SHALL/MUST contracts and goals code serves, evolvable in the
  graph: retire/reactivate via a status change, or reverse via a traversable
  int→int `supersedes` edge — no hand-editing (`intent-evolution`).
- **plan** — tasks in a DAG with state; a task declares the symbols that
  implement it, anchored to their current content (`enforceable-link`).
- **memory** — the durable *why* behind a change, re-surfaced when the code it
  concerns changes (`memory-family`).

### Retrieval — legible and token-cheap
- `context` is the one read command: governing intent, plan, implementing
  signatures, prior decisions, and drift return through a single token-budgeted
  slice rendered as **locators + signatures, not source** (`token-cheap-context`).
- The packet reserves per-family budget shares so no family is starved by a flood
  in another; every code node carries the justification by which it entered the
  slice, and a surfaced signal's explanation is never dropped by budget reduction
  (`packet-legibility`).
- Optional local semantic recall (`bge-small`) improves seeding; absent, retrieval
  degrades gracefully to the lexical seeder — never a hard dependency
  (`semantic-recall`).

### Enforceable links & drift
- A linked symbol whose body changed since anchoring is flagged as drift; a pure
  rename is not (`drift-detection`).
- Whole-file and line-range anchoring — `file:<path>` and `file:<path>:L<a>-L<b>`,
  hashing raw bytes — so infra/glue files (Dockerfile, buildspec, shell) are
  governable (`file-anchoring`).
- Drift is treated as **evidence-invalidation**: a drifted anchor marks its
  dependent belief STALE (re-verify), never automatically false — so a body change
  never silently retracts a decision or poisons maturity (`drift-as-stale`).
- Drift on a task its plan marks **done** is withheld from the surfaced signal
  (relinking a closed task is rubber-stamping) while still computed internally so
  the satisfied-but-unverified-intent check keeps firing (`drift-done-suppression`).
- Proof obligations: the invariants an edit must preserve — derived from the
  governing MUST/SHALL contracts and active acceptance criteria — are injected at
  the moment of action (`proof-obligations`).

### Memory — one coherent certainty model
Three orthogonal axes on a memory node, all overlaid at read time (never stored):
- **maturity** — earned behaviorally: promoted `working` → `settled` after it
  survives K review-encounters un-superseded; demoted only on a recorded
  contradiction, never by the passage of commits (`memory-maturity`).
- **attestation** — agent vs human; human attestation sets a sticky trust floor,
  and an agent supersede of a human-attested node is held pending and surfaced as
  a conflict, never applied silently (`memory-attestation`).
- **grounding** — `inferred | docs | empirical`; low-grounding beliefs surface as
  re-verify TODOs and can be upgraded when evidence arrives; `grounded_by` names
  the evidence that earns the `empirical` tier (`memory-grounding`).
- **Knowledge mining** lands mined/reviewed reasoning as `proposed` candidates
  with near-zero retrieval weight that expire unless a real encounter confirms
  them (`knowledge-mining`); **review-compound** turns a confirmed review finding
  into a durable node anchored to the reviewed locus (`review-compound`).
- **Conditioned rejections**: a rejected alternative can carry `valid_when` /
  `invalidated_when` premises and is surfaced only while they hold — so a
  rejection whose reason lapsed stops steering the agent away (`conditioned-rejections`).
- **Intent elicitation**: the agent queries the principal only on an unavoidable
  preference-fork, capturing the answer as a human-attested intent — never on
  ambiguity it can resolve by competence (`intent-elicitation`).

### Belief revision & concurrent writes (local)
- Multi-writer coordination is modeled as an append-only, content-addressed,
  causally-stamped log of assertions folded into a materialized (never lockable,
  never committed) graph — resolving writes by log-append, not locks/leases
  (`concurrent-write-model`). Conflicting live beliefs about the same anchor
  surface as an explicit knowledge conflict (belief revision), never
  last-writer-wins. Integrity via a Merkle hash chain; a provenance-typed partial
  order informs — never decides — which side of a conflict dominates.

### Hosts & delivery
- yigraf speaks into the agent's context at the moment of action. Push is
  delivered per host at the highest fidelity that host's own extension points
  allow: event-scoped hooks (Claude Code, Codex), an always-on ambient rule
  (Antigravity and the VS Code family), and pull-only via MCP everywhere else
  (`multi-host`, `host-push-adapters`, `hook-surfacing`).
- The MCP server exposes the full loop — read tools (`context`, `status`) and
  write tools (`link`, `remember`, `note_constraint`, `supersede`) —
  host-agnostically (`mcp-server`).
- A host-agnostic `status` line summarizes scale, drift, freshness, and semantic
  index for a thin per-host ambient surface, without spending the agent's context
  budget (`status-surface`).

### Packaging
- Requires **Python 3.11+**. 16 tree-sitter grammars bundled (Python, Go, JS/TS,
  Rust, Java, C/C++, Ruby, C#, Kotlin, Scala, PHP, Swift, Bash, SQL).
- Semantic recall (fastembed/ONNX) and the MCP server are **core** dependencies —
  full power out of the box, no extra to install. Optional extras: `[embeddings-torch]`
  (the opt-in torch backend for semantic recall) and `[postgres]` (the hosted-line
  Postgres adapter; removed in 1.1.0).
- MIT licensed. Published to PyPI as `yigraf`.

### Roadmap — not in 1.0
- **yigraf 2.0 — online / hosted** (`int:yigraf-online-v1`, *proposed*): the same
  belief-revision model behind a hosted service so multiple users and their agents
  work concurrently against one project graph — a durable, ordered, replayable
  ingest log with synchronous structural/causal validation and asynchronous
  semantic-coherence checking. The log/Merkle/provenance/ingest-validation engine
  is scaffolded (`onlinelog.py`); the hosted store, service process, and
  end-to-end client sync are 2.0 work.
- Deferred residuals now homed under 2.0: the per-conflict belief-revision
  resolution UI (consuming the derived `accepted`/`dominant` fields), and a native
  TaskList host-adapter (blocked until a host exposes a writable task API).

[1.5.1]: https://github.com/mansilla/yigraf/releases/tag/v1.5.1
[1.5.0]: https://github.com/mansilla/yigraf/releases/tag/v1.5.0
[1.4.0]: https://github.com/mansilla/yigraf/releases/tag/v1.4.0
[1.3.1]: https://github.com/mansilla/yigraf/releases/tag/v1.3.1
[1.3.0]: https://github.com/mansilla/yigraf/releases/tag/v1.3.0
[1.2.0]: https://github.com/mansilla/yigraf/releases/tag/v1.2.0
[1.1.1]: https://github.com/mansilla/yigraf/releases/tag/v1.1.1
[1.1.0]: https://github.com/mansilla/yigraf/releases/tag/v1.1.0
[1.0.0]: https://github.com/mansilla/yigraf/releases/tag/v1.0.0
