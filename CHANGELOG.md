# Changelog

All notable changes to yigraf are recorded here. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/); yigraf uses
[semantic versioning](https://semver.org/).

## [Unreleased]

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
  usually noise trains the reader to clear it unread.
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

[1.3.1]: https://github.com/mansilla/yigraf/releases/tag/v1.3.1
[1.3.0]: https://github.com/mansilla/yigraf/releases/tag/v1.3.0
[1.2.0]: https://github.com/mansilla/yigraf/releases/tag/v1.2.0
[1.1.1]: https://github.com/mansilla/yigraf/releases/tag/v1.1.1
[1.1.0]: https://github.com/mansilla/yigraf/releases/tag/v1.1.0
[1.0.0]: https://github.com/mansilla/yigraf/releases/tag/v1.0.0
