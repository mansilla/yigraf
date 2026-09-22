"""yigraf configuration: defaults + loader for ``yigraf/config.yaml``.

The config file is committed (it governs extraction, drift, and retrieval). Only a subset matters in
M0 — the retrieval/relevance tunables are written now so later milestones read them from one place.
What each knob does is documented for users in ``docs/guide.md``; the code here is the authority.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import yaml

#: The house rules injected verbatim at SessionStart, ahead of the relevance-ranked slice
#: (``session_start.preamble``). This is the one channel in yigraf that does **not** rank, and it
#: exists because ranking structurally cannot reach this content: a rule about *using yigraf* has no
#: lexical or semantic affinity with a domain intent, so it never survives the cut no matter how it
#: is worded or how mature it gets (measured in the field — `attest` doesn't promote into injection
#: and `settled` is earned, not settable). It is modelled on CLAUDE.md, which works because it is
#: (a) once, (b) before any action is chosen, and (c) delivered as instruction rather than as
#: reference about a file. Per-edit injection is none of those three, which is why the same words
#: there became wallpaper within three edits.
#:
#: Kept short on purpose: it is charged to the same budget as the ranked slice, so every line here
#: costs the agent a line of its actual context. Override it in ``yigraf/config.yaml`` (committed, so
#: a team's conventions live with the repo instead of in each agent's private memory); set it empty
#: to silence the channel entirely.
DEFAULT_SESSION_PREAMBLE = """\
[yigraf] Standing rules for this session — instructions, not reference:
- Read yigraf's own guidance before driving the CLI: the `yigraf` skill if your host loads skills,
  otherwise the yigraf block in AGENTS.md. `yigraf cheatsheet` lists every verb and flag. Knowing
  the verbs is not the same as knowing which one resolves which signal.
- Capture as the work lands, not as a closing ritual. `--why` and `--rejected` are worth most at the
  moment of the decision; by the end of a session the reasoning that made the choice is gone.
- Before you report done, run `yigraf status`. "Up to date" means no drift, no stale AND no unsettled
  rename — settle the rename first, it is the only one that expires. Open tasks are a fourth, separate
  thing, and a quiet context packet is evidence of none of them.
- One verb per signal, and the wrong one costs you: code a decision governs changed → `reaffirm`
  (the belief is unchanged) or `supersede` (your mind changed), never re-`remember`. A done task's
  symbol changed → re-`link`, or reopen it. Two live beliefs collide → `reconcile`, `supersede`, or
  `dispute`.
"""

#: Every session preamble yigraf has shipped BEFORE the current one, newest last.
#:
#: Through 1.10.0 ``yigraf init`` spliced the preamble into the repo's *committed* ``yigraf/config.yaml``
#: as a live key, and the file value wins at read time — so amending :data:`DEFAULT_SESSION_PREAMBLE`
#: reached no already-initialized repo. That is the same two-copy hazard ``skill_behind`` exists for,
#: one file over (feedback-v6 F#1), and it is worse here: the preamble is *the* channel on a host with
#: no skill. 1.11.0 stopped minting the copy (:func:`commented_preamble_block`) and gave the nudge a
#: one-command remedy (:func:`refresh_preamble`), so this tuple now serves a finite, shrinking
#: population: repos initialized by an older CLI that have not run ``yigraf install`` since.
#:
#: **Amending the default is a two-line change.** Append the outgoing text here in the same commit, or
#: every repo still carrying it goes silently unreported — the nudge can only fire on something we can
#: prove we shipped. ``test_the_current_default_is_not_also_listed_as_superseded`` guards the other
#: direction (a stale entry would nag everyone forever); nothing but this note guards the omission.
#:
#: Detection is a byte-for-byte match against what we shipped — never "differs from the current
#: default". The file says the preamble is yours to rewrite, so a rewritten one must stay silent; a
#: match is proof of an untouched copy of ours rather than a guess about one, the same discipline
#: :func:`yigraf.hooks.installed_skill_version` applies to an unstamped skill. One entry covers every
#: release that had a preamble: the text was introduced at 1.4.0 and was unchanged through 1.8.0.
#:
#: :func:`preamble_behind` matches this tuple PLUS the current default, because a live key holding
#: today's text is a 1.9.0-1.10.0 mint that has simply not gone stale yet (feedback-v9 H#1) — so this
#: tuple is no longer the whole detected set, and the invariant that the current text must never be
#: listed *here* still holds for the reason it always did: a stale entry would nag everyone forever.
SUPERSEDED_SESSION_PREAMBLES = ("""\
[yigraf] Standing rules for this session — instructions, not reference:
- Read yigraf's own guidance before driving the CLI: the `yigraf` skill if your host loads skills,
  otherwise the yigraf block in AGENTS.md. `yigraf cheatsheet` lists every verb and flag. Knowing
  the verbs is not the same as knowing which one resolves which signal.
- Capture as the work lands, not as a closing ritual. `--why` and `--rejected` are worth most at the
  moment of the decision; by the end of a session the reasoning that made the choice is gone.
- Before you report done, run `yigraf status`. "Up to date" means no drift AND no stale — open tasks
  are a third, separate thing, and a quiet context packet is evidence of neither.
- One verb per signal, and the wrong one costs you: code a decision governs changed → `reaffirm`
  (the belief is unchanged) or `supersede` (your mind changed), never re-`remember`. A done task's
  symbol changed → re-`link`, or reopen it. Two live beliefs collide → `reconcile`, `supersede`, or
  `dispute`.
""",)


def committed_config(path: Path) -> dict[str, Any]:
    """The repo's ``config.yaml`` exactly as written — no defaults merged, ``{}`` when absent/unreadable.

    :func:`load_config` answers "what is in effect"; this answers "what did the team COMMIT", and the
    preamble questions are all the second kind. Fail-soft on a malformed file on purpose: this feeds a
    nudge and a statusline, and neither may raise (design law #5).
    """
    path = Path(path)
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def preamble_behind(config_path: Path) -> bool:
    """Whether this repo carries a committed *live* copy of a preamble yigraf itself shipped.

    False for a rewritten preamble, for ``preamble: ""``, for an absent key, and — the part that is a
    declaration rather than a deduction — for any file carrying ``preamble_pinned: true``.

    Reads ``config_path`` AS COMMITTED rather than taking a merged config, and that is load-bearing
    now that the current default is matched too: :func:`load_config` fills an absent ``preamble:`` key
    from :data:`DEFAULT_SESSION_PREAMBLE`, so in a merged mapping the healthy 1.11+ file (no key, falls
    through) is byte-identical to the very state this reports. The file is the only place the
    difference exists. One small read, like :func:`yigraf.hooks.installed_skill_version` beside it.

    **Byte-identity proves where text came from; it cannot prove how the copy got into the file**
    (feedback-v9 H#1). ``init`` minting the key and a human running the documented "uncomment the block
    below to pin your own" produce identical bytes, and nothing else in the file separates them. That
    one predicate had two victims on opposite clocks: a deliberate pin is deleted by the first release
    that amends the default (the pin becomes byte-identical to a superseded one), while *until* that
    release every repo initialized at 1.9.0–1.10.0 — a live key matching the still-CURRENT default,
    because the text last changed at 1.9.0 and minting stopped at 1.11.0 — was invisible to the remedy
    and kept the exact two-copy hazard 1.11.0 exists to remove. No ordering of
    :data:`SUPERSEDED_SESSION_PREAMBLES` separates them, because they are the same bytes.

    So the match is widened to every default we have ever shipped, the current one included, and
    provenance moves to where the human's own action already is: :func:`commented_preamble_block` ships
    ``preamble_pinned: true`` *inside* the commented block, so the one-command uncomment declares
    itself. Nothing written by 1.10.0 or earlier can carry that line, which is what keeps the stranded
    population reachable. It is the discipline :func:`yigraf.hooks.installed_skill_version` already
    applies to an unstamped skill; the gap was only that the preamble had no stamp to read.

    **The cost, taken deliberately:** a pin made by hand *before* the marker shipped carries no marker
    and is indistinguishable from a mint, so it is retired like one. That is a real loss of a real
    choice, and it is bounded — one transition, for pins made between 1.9.0 and the release that adds
    this line — where leaving the tuple alone strands the 1.9.0–1.10.0 repos permanently instead. A
    repo left carrying a live copy that silently stops tracking the CLI is the failure this whole
    mechanism exists to end, so the finite loss is preferred to the unbounded one.
    """
    return preamble_copy_class(config_path) is not None


#: A live copy matching a preamble we no longer ship. Provably abandoned: only an ``init`` through
#: 1.8.0 could have written it, and the team never touched it since.
PREAMBLE_COPY_SUPERSEDED = "superseded"

#: A live copy matching the preamble we ship TODAY, and the file cannot say which history produced it:
#: an ``init`` at 1.9.0-1.10.0 (the common case, and the population :func:`refresh_preamble` exists to
#: reach), or a deliberate pin made before ``preamble_pinned:`` existed to declare itself. Retired
#: either way — see :func:`preamble_behind` for why the bounded loss was preferred — but never
#: silently: the caller must say so, because for one of those two histories this is a choice being
#: overridden and the remedy is one uncomment the reader has to know about (feedback-v9 H#1).
PREAMBLE_COPY_CURRENT = "current"


def preamble_copy_class(config_path: Path) -> str | None:
    """Which class of committed live copy this file carries, or ``None`` for nothing to retire.

    :data:`PREAMBLE_COPY_SUPERSEDED` and :data:`PREAMBLE_COPY_CURRENT` are retired identically and
    reported differently, which is the whole reason this is not a bool: the first is provably ours and
    worth one line, the second is ambiguous and worth a warning.
    """
    session = (committed_config(config_path).get("session_start") or {})
    if session.get("preamble_pinned"):  # the team said so, in the file, on purpose — believe them
        return None
    text = session.get("preamble")
    if text in SUPERSEDED_SESSION_PREAMBLES:
        return PREAMBLE_COPY_SUPERSEDED
    if text is not None and text == DEFAULT_SESSION_PREAMBLE:
        return PREAMBLE_COPY_CURRENT
    return None


DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 0,
    # Structure extraction (M1). Languages with a shipped extractor; grammars for the rest of the
    # core set are bundled and light up as their extractors land.
    "languages": ["python", "go", "javascript", "typescript", "rust", "java", "c", "cpp",
                  "ruby", "php", "c_sharp", "kotlin", "scala", "swift", "bash", "sql"],
    # Extraction skips these paths. When the repo is a git work tree, `.gitignore` is honored FIRST
    # (build/cache trees like `.next/` never get enumerated — see extract._iter_source_files), so this
    # list is (a) the non-git fallback floor and (b) a way to exclude a git-TRACKED dir. It stays a
    # cross-language build/cache floor so a non-git checkout can't blow up RAM indexing `.next/`.
    "ignore": [".git/", "__pycache__/", ".venv/", "node_modules/", "origins/",
               ".next/", ".nuxt/", ".svelte-kit/", ".turbo/", "dist/", "build/", "out/", "target/",
               "vendor/", "coverage/", ".gradle/", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/"],
    # Maturity (mem:033): a memory settles once its accumulated survived-encounter *upholds* reach
    # `maturity_k` and it isn't superseded. Upholds are read-time, sidecar-derived — a reaffirm books
    # `maturity_uphold_review`, a silent edit-hook survival books `maturity_uphold_edit`. Git-survival
    # is an optional durability floor (0 = off): settled also requires `survival >= maturity_survival_floor`,
    # except where no survival clock can measure at all — there the floor abstains rather than denying
    # every promotion forever (counters.apply_maturity_verdict).
    "maturity_k": 3,
    "maturity_confirm": 1.0,
    "maturity_uphold_review": 1.0,
    "maturity_uphold_edit": 0.25,
    "maturity_survival_floor": 0,
    # GC expiry (task #7): a `proposed` candidate never confirmed by an encounter is archived once it
    # has aged this many commits un-referenced. Only the quarantine tier expires by silence — a genuine
    # working/settled decision never does (mem:033). 0 would expire same-commit; keep a real grace window.
    "proposed_ttl": 30,
    # The reaffirm burst guard (feedback-v5, still-open #1). `reaffirm` accepts an id with no evidence
    # the claim was read, so a per-id `for` loop takes a drift count to zero with a success line each
    # and no refusal — which *feels* like progress and is the exact dishonesty the reaffirm/supersede
    # split exists to prevent. Past `reaffirm_burst` single-id reaffirms inside
    # `reaffirm_burst_window` seconds, the next one must carry `--verified "<what you checked>"`. Not a
    # rate limit: an honest caller is never blocked, only asked to say what they read — one line a loop
    # cannot meaningfully fill. Set reaffirm_burst: 0 to switch the guard off entirely.
    "reaffirm_burst": 3,
    "reaffirm_burst_window": 300,
    # The hollow-`--why` guard (feedback-v5 amendment). A `--why` whose whole content is a pointer at
    # another node ("the argument is in the node this supersedes") defers an argument nobody ever
    # checked was written — and four such pointers in a real store resolved to nodes with no argument
    # at all. Capture refuses when the pointer bottoms out in nothing. This is the longest residue —
    # the --why with the ids it names removed — that still counts as *only* a pointer; above it, a
    # --why that cites a node is read as an argument that happens to cite one. 0 switches it off.
    "hollow_why_words": 25,
    # The whole-file section OFFER (feedback-v6 §7). A whole-file markdown anchor is often a claim
    # about one section, and the field measured its own store for a rule that separates the two: a
    # null — every size-shaped signal overlaps, and nothing beats warning unconditionally, which is
    # right two times in three (i.e. a mark worth ignoring). So yigraf offers instead of warning, and
    # this is how far ahead of the runner-up the best-fitting section must score to be named. Set for
    # legibility, not recall: a near-tie means the document says the claim's words in two places, and
    # naming one arbitrarily teaches the reader the suggestion is noise. 0 switches the offer off.
    # The knob is live everywhere the offer can fire since 1.10.0: on a document with only ONE
    # offerable section there was no runner-up, so the comparison never ran and 1e9 offered as
    # readily as 2.0 — that shape is now structurally silent (feedback-v7 G#2). The default stays 2.0
    # pending an accept rate rather than a recall curve: the field measured 2 of 12 firing at 2.0 and
    # 12 of 12 at 1.0 in one store, but which of those offers would have been RIGHT is the number that
    # sets this, and `.local/section-offers.json` is what now collects it.
    "section_offer_margin": 2.0,
    # Retrieval (M4) — seeding, bounded traversal, and ranking of the token-budgeted context slice.
    "retrieval": {
        "seeds": 5,
        "seed_cap": 6,
        "max_hops": 2,
        "node_budget": 60,
        "hub_percentile": 99,
        "hub_floor": 50,
        "ranking": {"alpha": 0.5, "beta": 0.3, "gamma": 0.2},  # match · proximity · relevance
        "hook_token_budget": 800,
        "query_token_budget": 4000,
        # Structure render mode (A3 — source-vs-signature; see scripts/eval). signature_only =
        # locator+signature (token-thrift); source_for_seeds = verbatim line-numbered source for the
        # top `source_max_symbols` symbols (sufficiency — the agent treats it as already Read).
        "render": "signature_only",   # signature_only | source_for_seeds
        "source_max_symbols": 3,
        "source_max_lines": 40,
        # Reserved per-family budget floors (epistemic-control-plane task 4): the render splits the
        # packet so a flood of code symbols can't starve the "why" families (intent/memory). Floors,
        # not partitions — a family that doesn't use its share yields it to the others (design law #2).
        "family_shares": {"intent": 0.25, "plan": 0.15, "structure": 0.30, "memory": 0.30},
        # Share of the budget the ✔ proof-obligation block may take (of what the ⚠ warnings leave).
        # The block scales with how *governed* a locus is, so without a bound it lands unbounded ahead
        # of every node: measured 3833 tokens against an 800 budget, 0 of 86 nodes, on yigraf's own
        # cli.py. Whole governing intents are admitted in density order until the share is spent.
        "obligation_share": 0.35,
        # Max ⚠ drift lines in an injected packet (hard drift first; the rest become a count + the
        # verb to see them). `yigraf drift` renders from its own path and is never capped.
        "max_drift_lines": 4,
        # Same bound for ⚠ STALE completion lines. Stale went global at SessionStart (it is the
        # orientation dashboard, not a topical query), so a repo carrying many closed-then-edited
        # tasks would flood the packet exactly as drift did; the tail names `yigraf drift --stale`.
        "max_stale_lines": 4,
    },
    # Relevance prior weights (a node's standing weight, scored at read time).
    #   w1·log(1+refs_in) + w2·recency(last_seen) + w3·maturity − w4·[superseded_in>0] − w5·[proposed]
    "relevance": {"w1": 1.0, "w2": 1.0, "w3": 1.0, "w4": 1.0, "w5": 3.0, "half_life_days": 14},
    # Embeddings (M8) — scoped semantic recall over the memory + intent families only.
    # On by default: fastembed (ONNX) is a core dep, so no extra install. Set backend: none to disable
    # (⇒ graceful lexical-only fallback), or sentence-transformers to use the opt-in torch backend.
    "embeddings": {
        "backend": "fastembed",  # fastembed | sentence-transformers | none
        "model": "BAAI/bge-small-en-v1.5",
        # Where the model artifacts live. None ⇒ ~/.cache/yigraf/models (XDG-aware). Deliberately NOT
        # fastembed's default of $TMPDIR/fastembed_cache: macOS reaps /var/folders/…/T by access time,
        # which evicts the big ONNX blob, leaves a dangling snapshot symlink, and turns every later
        # load into a silent re-download. Nothing downloads implicitly anyway (embeddings.get_embedder
        # is local-only; `yigraf install` fetches) — but the model should be fetched *once*.
        "cache_dir": None,
        "dup_cosine": 0.9,  # write-time near-duplicate threshold for `remember` (capture-flow §4)
        # `context` cosine floor below which it prints a low-confidence banner (C#8). Calibrated for
        # bge-small, whose cosines compress into a high, narrow band: on this corpus off-topic/gibberish
        # queries top out ≈0.62 and real topical queries bottom at ≈0.68, so 0.65 sits in the gap. A
        # different model needs re-calibration (a naive 0.4 never fires).
        "relevance_floor": 0.65,
        # Batch coherence sweep threshold (contradiction.py, task #4): two live co-anchored beliefs
        # this close read as the same topic and surface as a knowledge-conflict candidate for a
        # principal (mem:062). Below the 0.9 refuse-at-write line (a cross-log near-dup the per-write
        # guard never saw) yet above the complementary-decision noise band — calibrated on the
        # self-hosted corpus (5 candidates at 0.85, 0 at 0.9). Re-calibrate per model like the others.
        "conflict_cosine": 0.85,
    },
    # Status surface (int:status-surface). The ctx gauge scales to a *usable budget*, not the raw
    # window: quality and token cost track *absolute* occupancy, so a 1M window reads ~"full" long
    # before 100%. The gauge denominator is min(host window, ctx_soft_limit) — a 1M window clamps to
    # the knee, a genuine ~200k window is unaffected (the min is the window itself). 0 opts out (gauge
    # against the raw window). ~200k is where Opus-class quality degrades and per-turn cost climbs.
    # The percent is therefore knee-relative and by design disagrees with the host's own readout, so
    # the render always carries the physical pair beside it (StatusSummary.ctx_fill) and `yigraf status`
    # explains the gap (ctx_note) — a bare knee-relative percent has been misread as "nearly out".
    "status": {
        "ctx_soft_limit": 250_000,
        # The principal's turn-boundary notice (int:obligation-notice). Edge-triggered: it announces an
        # obligation once, on first appearance, on the host's user-facing channel — never the agent's
        # context (mem:012) and never as a block (design law #5). Off ⇒ the statusline counts remain the
        # only human surface.
        "obligation_notice": True,
        "obligation_notice_max": 5,
    },
    # SessionStart (int:session-orientation) — the three UNRANKED channels of the orientation packet.
    # Everything else yigraf injects is relevance-ranked against a topic, which is the right default
    # and the reason these three have to exist: a rule about *using* the tool, a constraint that is
    # load-bearing on every task, and the mere existence of a belief the agent has not thought to ask
    # about are all content no ranker will ever surface, because nothing in the query resembles them.
    # A store's value is bounded by what the agent can be made aware of WITHOUT already knowing it.
    "session_start": {
        # Verbatim house rules, before the ranked slice. "" / null ⇒ the channel is silent.
        "preamble": DEFAULT_SESSION_PREAMBLE,
        # Set true in a committed config.yaml to declare "the preamble above is OURS": it is the one
        # fact byte-identity cannot carry, and it stops every install verb retiring the key
        # (feedback-v9 H#1). False here is a default, never a claim — a repo that never uncommented
        # the block has no preamble of its own to protect.
        "preamble_pinned": False,
        # End the packet's head with the one-line `yigraf status` summary, so the rules arrive with
        # the live counts attached instead of as abstract advice.
        "append_status": True,
        # Token budget for the whole SessionStart packet — the ranked slice and the titles manifest are
        # sized to what the preamble and the pin block leave of it. Its own key (feedback-v10 C.1): it
        # used to borrow `retrieval.query_token_budget`, the knob for a `context` answer, so one number
        # sized two things that are tuned for different reasons.
        #
        # DELIBERATELY ABSENT from these defaults, which is what makes the documented fallback reachable:
        # `session_context` reads `scfg.get("token_budget") or retrieval.query_token_budget`, so a default
        # here is never falsy and the second term is dead for every config a *file* can express. A store
        # written before this key existed would then be sized 4000 whatever its query budget said — a
        # silent packet resize on upgrade, in either direction. The template omits it too, on the same
        # ground as `preamble`: an omission inherits, so it cannot drift and an upgrade can reach it. A
        # fresh store therefore inherits `query_token_budget` (4000 there), i.e. renders exactly as before.
        # State the key only to size the packet independently of a `context` answer.
        # Token budget for `pinned` memories, rendered IN FULL. Whole nodes in or out, in relevance
        # order, with the elision stated — a pin tier only works if the budget BINDS (if everything
        # is pinned, session start is the new wallpaper). Most repos pin nothing and pay nothing.
        "pinned_budget": 800,
        # Titles-only manifest of memories the packet did not otherwise show — the cheapest possible
        # conversion of unknown-unknowns into known-unknowns, which is the whole precondition for the
        # agent choosing to run `context` at all. 0 ⇒ off.
        "manifest_titles": 15,
    },
    # Hook execution budget (feedback-v11 K#4). yigraf's installer writes `"timeout": 15` into the
    # host's hook definition, and the field measured that bound being REACHED — 24 cancellations
    # across 58 transcripts, every recorded duration just past 15 000 ms — with each one failing
    # silently and differently. yigraf therefore keeps a deadline of its OWN, under the host's, so a
    # slow run degrades to something honest instead of being killed having emitted nothing.
    "hooks": {
        # Wall-clock seconds before the hook stops and serves its degraded answer. Deliberately under
        # the installer's 15: the margin is what lets a fallback be rendered AND read. Raising the
        # host's number instead was the field's ask and is refused — a hook that blocks an agent for
        # fifteen seconds already violates design law #5, and a later deadline buys a slower failure
        # rather than a rarer one. `0` disarms the budget and restores the pre-1.15 behaviour.
        "deadline_seconds": 10,
        # A run at or past this many ms appends its phase breakdown to the gitignored ring buffer that
        # `yigraf doctor` reads. Under it, nothing is written — the ordinary sub-second run costs one
        # comparison and no I/O. This exists because there was no timing instrumentation anywhere, so
        # "what was slow?" had no answer on either side of the report.
        "slow_run_ms": 2000,
        # Ring-buffer depth. Small on purpose: the question is "what was slow last time", not a series.
        "timings_kept": 50,
    },
    # Online (int:yigraf-online-v1) — the shared log this workspace participates in. `project` is the
    # key the hosted log is scoped by; `replica` is the local SQLite mirror `yigraf sync` maintains,
    # relative to the workspace dir. With either unset, or the replica absent, the build is purely
    # local — the offline default, and what every workspace does until it opts in.
    "online": {
        "project": None,
        "remote": None,
        "replica": "cache/replica.db",
        # The root-commit SHA the hosted project is about, written by `yigraf online` when it binds.
        # Safe to commit (it is a public git SHA) and worth committing: it makes the binding auditable,
        # and `yigraf sync` re-derives the local root commit and compares before pushing — which
        # catches the one case the bind-time check cannot, a config.yaml copied into another repo.
        "repo_fingerprint": None,
    },
}

#: Environment variable holding the bearer token for the hosted log. Deliberately NOT a config key —
#: config.yaml is committed, and a token in git is a leaked token. It takes precedence over the
#: credentials file `yigraf online` writes (see yigraf.online.resolve_token), which is what makes CI
#: and containers work without an interactive link step.
TOKEN_ENV = "YIGRAF_TOKEN"

# Commented YAML written by ``yigraf init``. A test asserts this parses to DEFAULT_CONFIG, so the
# friendly file and the in-code defaults can never silently drift apart. The session-start preamble is
# spliced in from the one constant above rather than retyped — it is prose a user edits, so a second
# copy here would be the one that goes stale.
_CONFIG_YAML_TEMPLATE = """\
# yigraf config — committed. Governs structure extraction, drift, and retrieval.
# Written by `yigraf init`; safe to edit. What each knob does: https://github.com/mansilla/yigraf/blob/main/docs/guide.md
schema_version: 0

# --- Structure extraction (M1) ---
# bespoke extractors (python, go, javascript, typescript); grammar tags-query extractors
# (rust, java, c, cpp, ruby, php); yigraf-vendored tags-query extractors (c_sharp, kotlin, scala,
# swift, bash, sql).
languages: [python, go, javascript, typescript, rust, java, c, cpp, ruby, php,
            c_sharp, kotlin, scala, swift, bash, sql]
# Paths skipped when indexing. In a git repo, `.gitignore` is honored FIRST (build/cache trees like
# `.next/` are never enumerated), so this is the non-git fallback floor + a way to skip a git-TRACKED
# dir. Keep the build/cache floor so a non-git checkout can't exhaust RAM indexing generated source.
ignore:
  - .git/
  - __pycache__/
  - .venv/
  - node_modules/
  - origins/
  - .next/
  - .nuxt/
  - .svelte-kit/
  - .turbo/
  - dist/
  - build/
  - out/
  - target/
  - vendor/
  - coverage/
  - .gradle/
  - .pytest_cache/
  - .mypy_cache/
  - .ruff_cache/

# --- Maturity (mem:033) — settled = survived review-encounters, read-time from the sidecar ---
maturity_k: 3                  # accumulated uphold weight (un-superseded) before a memory "settles"
maturity_confirm: 1.0          # uphold weight that confirms a `proposed` candidate up to `working`
maturity_uphold_review: 1.0    # uphold booked by a `reaffirm` (an explicit re-verification)
maturity_uphold_edit: 0.25     # uphold booked by a silent edit-hook survival (no drift on the locus)
maturity_survival_floor: 0     # optional git-durability gate (commits since intro); 0 = off.
                               # Ignored (not enforced) where neither survival clock can measure —
                               # e.g. a gitignored workspace with no shared log; `build` warns.
proposed_ttl: 30               # GC archives a never-confirmed `proposed` candidate after this many commits (task #7)
reaffirm_burst: 3              # after this many single-id reaffirms in the window, the next needs --verified "<what you checked>" (0 = off)
reaffirm_burst_window: 300     # seconds the burst counter looks back over
hollow_why_words: 25           # a --why this short that only POINTS at another node is refused when
                               # the node it points at carries no argument either (0 = off)
section_offer_margin: 2.0      # capture-time OFFER (never a warning): when a whole-file markdown
                               # anchor's document has one section that scores this many times the
                               # runner-up on the claim's distinctive terms, name it and the `reanchor`
                               # that narrows to it. Nothing to clear either way. 0 = off.
                               # A document with fewer than two OFFERABLE sections is silent whatever
                               # this says — one candidate is not a choice. Every anchor considered is
                               # logged with both scores to .local/section-offers.json, so this can be
                               # re-fitted from your own store instead of guessed.

# --- Retrieval (M4) — how the token-budgeted context slice is seeded, traversed, and ranked ---
retrieval:
  seeds: 5                     # seed matches kept from the lexical/IDF seeder
  seed_cap: 6                  # hard cap on seeds
  max_hops: 2                  # bounded traversal depth from seeds
  node_budget: 60              # max nodes gathered before ranking
  hub_percentile: 99           # degree percentile above which a node is treated as a hub
  hub_floor: 50                # minimum degree to count as a hub
  ranking:                     # fusion weights: match · proximity · relevance
    alpha: 0.5
    beta: 0.3
    gamma: 0.2
  hook_token_budget: 800       # token budget for hook-injected context
  query_token_budget: 4000     # token budget for `yigraf context` output
  # Structure render mode (A3 — source-vs-signature, see scripts/eval). `signature_only` (default)
  # prints locator+signature; `source_for_seeds` prints verbatim, line-numbered source for the top
  # `source_max_symbols` ranked symbols (sufficiency over token-thrift — the agent stops re-Reading).
  render: signature_only       # signature_only | source_for_seeds
  source_max_symbols: 3        # source_for_seeds: top-ranked symbols rendered as source
  source_max_lines: 40         # per-symbol source line cap (longer bodies truncated)
  # Reserved per-family budget floors (epistemic-control-plane task 4) — a code-symbol flood can't
  # starve the "why" families; floors, not partitions (unused share flows to the others).
  family_shares:
    intent: 0.25
    plan: 0.15
    structure: 0.30
    memory: 0.30
  # Share of the budget (after ⚠ warnings) the ✔ proof-obligation block may take. It grows with how
  # governed a locus is, not with anything being wrong, so it is the block that floods — whole
  # governing intents are admitted in density order until this is spent, then the rest is counted.
  obligation_share: 0.35
  # Max ⚠ drift lines in an injected packet — drift scales with how much anchored belief a locus
  # carries, so it floods the same way. Hard drift (symbol gone) sorts ahead of soft (body changed),
  # and the rest become a count. `yigraf drift` is the full report and is never capped.
  max_drift_lines: 4
  # Same bound for ⚠ STALE completion lines (a done task whose implementing symbol drifted). These
  # are global at SessionStart — a repo between milestones is exactly when a forgotten stale item
  # goes unnoticed longest — so they need the same cap. The tail names `yigraf drift --stale`.
  max_stale_lines: 4

# --- SessionStart (int:session-orientation) — the three UNRANKED channels ---
# Everything else yigraf injects is ranked against a topic. These three exist because ranking cannot
# reach their content: a rule about *using* yigraf has no affinity with a domain intent, a constraint
# that is load-bearing on every task matches no particular one, and a belief the agent has never
# heard of is a query it cannot formulate. Retrievable and reachable are different properties, and
# only the second one has value.
session_start:
  # Verbatim house rules, injected before the ranked slice — once per session, as instruction, in the
  # position CLAUDE.md occupies. It is charged to the same budget as the slice, so each line here
  # costs a line of real context.
  #
  # This file deliberately carries NO `preamble:` key, so the rules you get are the ones the yigraf
  # you are running ships — upgrade the CLI and the text moves with it. Uncomment the block below to
  # pin your own (this file is committed, so a team's yigraf conventions live with the repo instead
  # of in each agent's private memory); from that point the rules are yours and yigraf never touches
  # them again. Uncomment `preamble_pinned: true` WITH it — that line is what says the text is yours,
  # and without it a copy that still matches something yigraf ships is read as ours and retired on the
  # next `yigraf install`. Rewrite the text and the marker is optional: a preamble that no longer
  # matches anything we shipped is self-evidently yours.
  # `yigraf cheatsheet --preamble` prints the current shipped text. `preamble: ""` silences the
  # channel entirely.
__PREAMBLE__
  append_status: true   # end the head with the one-line `yigraf status` summary (rules + live counts)
  # token_budget: 4000  # tokens for the whole packet; preamble + pins spend it first, then slice +
  #                     # titles. DELIBERATELY OMITTED, like `preamble` above: an omission inherits
  #                     # the fallback (`retrieval.query_token_budget`), which is what the notes
  #                     # promise and what a store written before this key existed relies on.
  #                     # State it only to size the packet independently of a `context` answer.
  pinned_budget: 800    # tokens for `pinned` memories, rendered IN FULL, whole nodes only
  manifest_titles: 15   # titles-only of that many memories the packet didn't show (0 = off)

# --- Hook execution budget (yigraf's own deadline, UNDER the host's) ---
# `install` writes `"timeout": 15` into the host's hook definition, and that bound gets reached in the
# field — with each cancellation failing silently: a lost SessionStart packet leaves the session acting
# as though the store did not exist, which is indistinguishable from yigraf having nothing to say. So
# yigraf stops itself first and serves a degraded answer that says so.
hooks:
  deadline_seconds: 10  # stop and degrade at this; under the host's 15 so the fallback can be read
                        # (0 disarms: be killed by the host instead). Raising the HOST's number is
                        # deliberately not the knob — a 15s hook already blocks the agent too long.
  slow_run_ms: 2000     # at/past this, append the phase breakdown to .local/hook-timings.json
  timings_kept: 50      # ring-buffer depth for `yigraf doctor`

# --- Relevance prior (how a node's standing weight is scored at read time) ---
relevance:                     # w1·log(1+refs_in) + w2·recency + w3·maturity − w4·[superseded] − w5·[proposed]
  w1: 1.0
  w2: 1.0
  w3: 1.0
  w4: 1.0
  w5: 3.0                       # dock for a `proposed` mined/review candidate (near-zero weight until confirmed)
  half_life_days: 14           # recency exp-decay half-life on last_seen (M9 runtime counter)

# --- Embeddings (M8) — scoped semantic recall over the memory + intent families ---
# On by default: fastembed (ONNX, ~no torch) is bundled in core, so semantic recall works out of the
# box. Set backend: none to disable (retrieval degrades gracefully to the lexical/IDF seeder = v0), or
# sentence-transformers to use the opt-in torch backend (`pip install 'yigraf[embeddings-torch]'`).
embeddings:
  backend: fastembed            # fastembed | sentence-transformers | none
  model: BAAI/bge-small-en-v1.5  # local CPU model, version-pinned, fetched once by `yigraf install`
  cache_dir:                    # empty ⇒ ~/.cache/yigraf/models. Never $TMPDIR: macOS reaps it, and an
                                # evicted model is a silent re-download. Nothing fetches implicitly —
                                # a missing model degrades to lexical, it never blocks a command.
  dup_cosine: 0.9               # write-time near-duplicate threshold for `remember` (capture-flow §4)
  relevance_floor: 0.65         # `context` cosine floor below which a low-confidence banner shows (C#8).
                                # Calibrated for bge-small (off-topic ≈0.62, on-topic ≈0.68); retune per model.
  conflict_cosine: 0.85         # batch coherence sweep: two live co-anchored beliefs this close surface as
                                # a knowledge-conflict candidate for a principal (task #4; below dup_cosine).

# --- Status surface (int:status-surface) — the human ambient statusline ---
# The context gauge scales to a *usable budget*, not the raw window: quality and per-turn cost track
# *absolute* occupancy, so a 1M window reads ~"full" long before 100%. Denominator is
# min(host window, ctx_soft_limit): a 1M window clamps to the knee, a genuine ~200k window is
# unaffected. ~200k is where Opus-class quality degrades and cost climbs. Set 0 to use the raw window.
# Because that percent is knee-relative it will NOT match your host's own context readout — so the
# line always names the physical occupancy next to it (`ctx 94% 236k/1M`), and `yigraf status` at a
# terminal spells the difference out. Read the percent as "of the usable budget", not "of the window".
status:
  ctx_soft_limit: 250000        # tokens of usable budget the ctx gauge scales to (0 = raw window)
  # The turn-boundary obligation notice: tells YOU (not the agent) when a conflict, stale completion,
  # or drift first appears, so you can direct the agent at it. Edge-triggered — announced once, never
  # repeated while it stays open — and it never blocks the agent's workflow.
  obligation_notice: true       # false ⇒ the statusline counts stay the only human surface
  obligation_notice_max: 5      # max obligations listed per notice (overflow is stated, not hidden)

# --- Online (int:yigraf-online-v1) — the shared log this workspace participates in ---
# Set `project` to the key the hosted log is scoped by, and the build folds the synced replica on top
# of your authored artifacts: a teammate's intent starts drifting against YOUR local code, and their
# beliefs enter `context`/`status` exactly like your own. Leave `project` empty (or let the replica be
# absent) and the build is purely local — the offline default. Structure is never synced; only
# assertions cross the wire, so reasoning stays on your machine.
# `yigraf sync` pulls the delta, verifies it chains, then pushes anything you authored that the log
# hasn't seen. You don't normally write these by hand: `yigraf online <link-url>` fills them in when it
# binds this workspace to a hosted project. The token is never here — it goes to
# ~/.config/yigraf/credentials.json (or $YIGRAF_TOKEN), because config.yaml is committed and a token in
# git is a leaked token.
online:
  project:                      # e.g. yigraf-server — empty means offline
  remote:                       # e.g. https://yigraf.online — empty means offline
  replica: cache/replica.db     # local SQLite mirror, relative to the yigraf/ workspace dir
  repo_fingerprint:             # root-commit SHA this binding is for; checked before every push
"""

def commented_preamble_block(indent: str = "  ") -> str:
    """The shipped preamble as a **commented-out** ``preamble:`` block, ready to splice into the file.

    Written commented rather than live so the key stays *absent*: an absent key falls through to
    :data:`DEFAULT_SESSION_PREAMBLE` at load time, so the rules an agent gets are always the ones the
    installed CLI ships and no upgrade can leave a repo behind. A live copy is the two-copy hazard
    itself — every release that amends the default strands every repo initialized before it, which is
    what ``preamble_behind`` had to be invented to *report* (mem:91fe59a8463b851d). The text is still
    written here, in full, because the knob has to be discoverable to be usable: reading the file is
    how a team learns the channel exists and what it currently says.

    Uncommenting is exact-reversible — strip ``"# "`` from each line and the result is the block scalar
    the file used to carry (2-space key, 4-space body), plus the pin marker. That is deliberate: the
    act of owning the preamble should be one editor command, not a retype.

    ``preamble_pinned: true`` rides directly above the key, inside the same block, so the single
    uncomment that takes ownership also *declares* it. That declaration is the whole point:
    :func:`preamble_behind` cannot tell a hand-pinned copy of today's text from an init-minted one by
    its bytes, and guessing wrong in either direction costs a team something (feedback-v9 H#1). The
    marker is the one fact the bytes do not carry, put where the human already has the file open.
    """
    body = "\n".join(f"{indent}#   {line}".rstrip()
                     for line in DEFAULT_SESSION_PREAMBLE.rstrip("\n").splitlines())
    return (f"{indent}# preamble_pinned: true   # keep this line when you uncomment the block below:\n"
            f"{indent}#                         # it is what tells yigraf the text is yours, not ours.\n"
            f"{indent}# preamble: |\n{body}")


#: The written file. The preamble rides along commented out — see :func:`commented_preamble_block` for
#: why the key is absent rather than spliced. One source for the prose; the template only frames it.
DEFAULT_CONFIG_YAML = _CONFIG_YAML_TEMPLATE.replace("__PREAMBLE__", commented_preamble_block())


#: A live ``preamble:`` key line, at any indent. A commented one is not a key and must not match —
#: the file we WRITE carries exactly that, so matching it would make every migrated file ambiguous.
_PREAMBLE_KEY = re.compile(r"^(?P<indent>[ \t]*)preamble:")


def refresh_preamble(config_path: Path) -> str | None:
    """Retire a committed live copy of a preamble yigraf ships.

    Returns WHICH class was retired (:data:`PREAMBLE_COPY_SUPERSEDED` / :data:`PREAMBLE_COPY_CURRENT`)
    or ``None`` when nothing was written — because the two deserve different words from the caller,
    and a bool cannot carry that. Retiring the current text is the ambiguous case: it is usually the
    1.9.0-1.10.0 mint this exists to reach, and it is sometimes a pin made before the marker existed,
    and the file cannot say which. Doing that quietly is what made the loss a surprise.

    The remedy half of :func:`preamble_behind`, and it inherits that predicate's evidence standard
    verbatim: it acts **only** on a byte-exact match against a preamble yigraf itself shipped — which
    is proof of where the text came from, though never of how the copy got into the file, which is why
    the team's own ``preamble_pinned: true`` outranks it. A rewritten preamble, ``preamble: ""``, an
    already-absent key and any declared pin are all no-ops. That is what makes writing to a committed,
    user-owned file defensible here — this does not edit anyone's content, it removes an undeclared
    copy of *ours* — and it is why the call sites are the ``install`` verbs (an explicit request to
    bring yigraf's own surfaces current) and never a read path or a hook.

    Nothing is destroyed that one editor command cannot restore: the key is replaced by
    :func:`commented_preamble_block`, so the full text stays in the file, one uncomment from being
    re-pinned — with its declaration, this time.

    The file is edited as *text*, not round-tripped through the YAML parser, because the parser would
    discard every comment in it — and this file is mostly comments, which are the only documentation
    of what each knob does. An unambiguous single ``preamble:`` key is required; anything else returns
    False and leaves the nudge standing — a notice that persists one more release costs far less than
    a wrong splice into a committed file.
    """
    retiring = preamble_copy_class(config_path)
    if retiring is None:
        return None
    lines = config_path.read_text(encoding="utf-8").splitlines(keepends=True)
    hits = [i for i, line in enumerate(lines) if _PREAMBLE_KEY.match(line)]
    if len(hits) != 1:  # ambiguous or gone — say nothing rather than guess at a committed file
        return None
    start = hits[0]
    indent = _PREAMBLE_KEY.match(lines[start]).group("indent")
    # The block scalar's body is every following line that is blank or indented deeper than the key.
    end = start + 1
    while end < len(lines) and (not lines[end].strip()
                                or lines[end].startswith((indent + " ", indent + "\t"))):
        end += 1
    while end - 1 > start and not lines[end - 1].strip():
        end -= 1  # give back trailing blank lines: they separate the next key, they aren't the body
    lines[start:end] = [commented_preamble_block(indent) + "\n"]
    config_path.write_text("".join(lines), encoding="utf-8")
    return retiring


def default_config() -> dict[str, Any]:
    """A deep copy of the built-in defaults."""
    return copy.deepcopy(DEFAULT_CONFIG)


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_config(path: Path) -> dict[str, Any]:
    """Load config from ``path``, merging present values over the defaults.

    A missing file yields the defaults unchanged, so the tool works before ``yigraf init`` runs.
    """
    cfg = default_config()
    path = Path(path)
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{path}: expected a YAML mapping at the top level")
        cfg = _deep_merge(cfg, loaded)
    return cfg


def replica_path(root: Path, config: dict[str, Any]) -> Path | None:
    """The synced replica this workspace reads, or ``None`` when it is offline (no ``online.project``).

    One seam because three readers must agree on it *exactly*: the fold that folds it onto the local
    graph (:func:`yigraf.extract._fold_replica`), the shared-log survival clock
    (:func:`yigraf.counters.log_survival`), and the view's cache key
    (:func:`yigraf.graphdb.source_fingerprint`). The last one is why a duplicated literal was a real
    hazard rather than a style problem: a fingerprint that stats a *different* path than the fold reads
    is a cache key that misses its own input, and the view then serves a divergence verdict computed
    against a replica that has since moved.

    The path may not exist yet — a bound workspace that has never synced has no replica file — and
    callers handle that themselves: the readers fail open to "nothing folded", and the fingerprint wants
    the ARRIVAL of the file in its digest, so it must be named whether or not it is there.
    """
    online = config.get("online") or {}
    if not online.get("project"):
        return None
    return Path(root) / "yigraf" / (online.get("replica") or "cache/replica.db")
