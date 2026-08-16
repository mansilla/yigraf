"""yigraf configuration: defaults + loader for ``yigraf/config.yaml``.

The config file is committed (it governs extraction, drift, and retrieval). Only a subset matters in
M0 — the retrieval/relevance tunables are written now so later milestones read them from one place.
What each knob does is documented for users in ``docs/guide.md``; the code here is the authority.
"""
from __future__ import annotations

import copy
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
- Before you report done, run `yigraf status`. "Up to date" means no drift AND no stale — open tasks
  are a third, separate thing, and a quiet context packet is evidence of neither.
- One verb per signal, and the wrong one costs you: code a decision governs changed → `reaffirm`
  (the belief is unchanged) or `supersede` (your mind changed), never re-`remember`. A done task's
  symbol changed → re-`link`, or reopen it. Two live beliefs collide → `reconcile`, `supersede`, or
  `dispute`.
"""

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
        # End the packet's head with the one-line `yigraf status` summary, so the rules arrive with
        # the live counts attached instead of as abstract advice.
        "append_status": True,
        # Token budget for `pinned` memories, rendered IN FULL. Whole nodes in or out, in relevance
        # order, with the elision stated — a pin tier only works if the budget BINDS (if everything
        # is pinned, session start is the new wallpaper). Most repos pin nothing and pay nothing.
        "pinned_budget": 800,
        # Titles-only manifest of memories the packet did not otherwise show — the cheapest possible
        # conversion of unknown-unknowns into known-unknowns, which is the whole precondition for the
        # agent choosing to run `context` at all. 0 ⇒ off.
        "manifest_titles": 15,
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
  # position CLAUDE.md occupies. Yours to rewrite: this file is committed, so a team's yigraf
  # conventions live with the repo instead of in each agent's private memory. Set to "" to silence.
  # It is charged to the same budget as the slice, so each line here costs a line of real context.
  preamble: |
__PREAMBLE__
  append_status: true   # end the head with the one-line `yigraf status` summary (rules + live counts)
  pinned_budget: 800    # tokens for `pinned` memories, rendered IN FULL, whole nodes only
  manifest_titles: 15   # titles-only of that many memories the packet didn't show (0 = off)

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

#: The written file, with the preamble spliced in as a YAML block scalar (4-space body indent, so it
#: nests under ``session_start.preamble:``). One source for the prose; the template only frames it.
DEFAULT_CONFIG_YAML = _CONFIG_YAML_TEMPLATE.replace(
    "__PREAMBLE__",
    "\n".join(f"    {line}".rstrip() for line in DEFAULT_SESSION_PREAMBLE.rstrip("\n").splitlines()),
)


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
