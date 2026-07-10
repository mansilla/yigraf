"""yigraf configuration: defaults + loader for ``yigraf/config.yaml``.

The config file is committed (it governs extraction, drift, and retrieval). Only a subset matters in
M0 — the retrieval/relevance tunables are written now so later milestones read them from one place.
Values trace to ``docs/retrieval-design.md`` §9 and ``docs/graph-design.md`` §3.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 0,
    # Structure extraction (M1). Languages with a shipped extractor; grammars for the rest of the
    # core set are bundled and light up as their extractors land.
    "languages": ["python", "go", "javascript", "typescript", "rust", "java", "c", "cpp",
                  "ruby", "php", "c_sharp", "kotlin", "scala", "swift", "bash", "sql"],
    "ignore": [".git/", "__pycache__/", ".venv/", "node_modules/", "origins/"],
    # Maturity (mem:033): a memory settles once its accumulated survived-encounter *upholds* reach
    # `maturity_k` and it isn't superseded. Upholds are read-time, sidecar-derived — a reaffirm books
    # `maturity_uphold_review`, a silent edit-hook survival books `maturity_uphold_edit`. Git-survival
    # is an optional durability floor (0 = off): settled also requires `survival >= maturity_survival_floor`.
    "maturity_k": 3,
    "maturity_confirm": 1.0,
    "maturity_uphold_review": 1.0,
    "maturity_uphold_edit": 0.25,
    "maturity_survival_floor": 0,
    # GC expiry (task #7): a `proposed` candidate never confirmed by an encounter is archived once it
    # has aged this many commits un-referenced. Only the quarantine tier expires by silence — a genuine
    # working/settled decision never does (mem:033). 0 would expire same-commit; keep a real grace window.
    "proposed_ttl": 30,
    # Retrieval (M4) — tunables from retrieval-design §9.
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
    },
    # Relevance prior weights (graph-design §3). Tuned empirically later.
    #   w1·log(1+refs_in) + w2·recency(last_seen) + w3·maturity − w4·[superseded_in>0] − w5·[proposed]
    "relevance": {"w1": 1.0, "w2": 1.0, "w3": 1.0, "w4": 1.0, "w5": 3.0, "half_life_days": 14},
    # Embeddings (M8) — scoped semantic recall over memory+intent only (retrieval-design §10).
    # On by default: fastembed (ONNX) is a core dep, so no extra install. Set backend: none to disable
    # (⇒ graceful lexical-only fallback), or sentence-transformers to use the opt-in torch backend.
    "embeddings": {
        "backend": "fastembed",  # fastembed | sentence-transformers | none
        "model": "BAAI/bge-small-en-v1.5",
        "dup_cosine": 0.9,  # write-time near-duplicate threshold for `remember` (capture-flow §4)
        # `context` cosine floor below which it prints a low-confidence banner (C#8). Calibrated for
        # bge-small, whose cosines compress into a high, narrow band: on this corpus off-topic/gibberish
        # queries top out ≈0.62 and real topical queries bottom at ≈0.68, so 0.65 sits in the gap. A
        # different model needs re-calibration (a naive 0.4 never fires).
        "relevance_floor": 0.65,
    },
    # Status surface (int:status-surface). The ctx gauge scales to a *usable budget*, not the raw
    # window: quality and token cost track *absolute* occupancy, so a 1M window reads ~"full" long
    # before 100%. The gauge denominator is min(host window, ctx_soft_limit) — a 1M window clamps to
    # the knee, a genuine ~200k window is unaffected (the min is the window itself). 0 opts out (gauge
    # against the raw window). ~200k is where Opus-class quality degrades and per-turn cost climbs.
    "status": {
        "ctx_soft_limit": 200_000,
    },
}

# Commented YAML written by ``yigraf init``. A test asserts this parses to DEFAULT_CONFIG, so the
# friendly file and the in-code defaults can never silently drift apart.
DEFAULT_CONFIG_YAML = """\
# yigraf config — committed. Governs structure extraction, drift, and retrieval.
# Written by `yigraf init`; safe to edit. See docs/DESIGN.md for the authority on each knob.
schema_version: 0

# --- Structure extraction (M1) ---
# bespoke extractors (python, go, javascript, typescript); grammar tags-query extractors
# (rust, java, c, cpp, ruby, php); yigraf-vendored tags-query extractors (c_sharp, kotlin, scala,
# swift, bash, sql).
languages: [python, go, javascript, typescript, rust, java, c, cpp, ruby, php,
            c_sharp, kotlin, scala, swift, bash, sql]
ignore:                        # path prefixes skipped when indexing the repo
  - .git/
  - __pycache__/
  - .venv/
  - node_modules/
  - origins/

# --- Maturity (mem:033) — settled = survived review-encounters, read-time from the sidecar ---
maturity_k: 3                  # accumulated uphold weight (un-superseded) before a memory "settles"
maturity_confirm: 1.0          # uphold weight that confirms a `proposed` candidate up to `working`
maturity_uphold_review: 1.0    # uphold booked by a `reaffirm` (an explicit re-verification)
maturity_uphold_edit: 0.25     # uphold booked by a silent edit-hook survival (no drift on the locus)
maturity_survival_floor: 0     # optional git-durability gate (commits since intro); 0 = off
proposed_ttl: 30               # GC archives a never-confirmed `proposed` candidate after this many commits (task #7)

# --- Retrieval (M4) — tunables from docs/retrieval-design.md §9 ---
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

# --- Relevance prior (docs/graph-design.md §3) ---
relevance:                     # w1·log(1+refs_in) + w2·recency + w3·maturity − w4·[superseded] − w5·[proposed]
  w1: 1.0
  w2: 1.0
  w3: 1.0
  w4: 1.0
  w5: 3.0                       # dock for a `proposed` mined/review candidate (near-zero weight until confirmed)
  half_life_days: 14           # recency exp-decay half-life on last_seen (M9 runtime counter)

# --- Embeddings (M8) — scoped semantic recall over memory+intent (docs/retrieval-design.md §10) ---
# On by default: fastembed (ONNX, ~no torch) is bundled in core, so semantic recall works out of the
# box. Set backend: none to disable (retrieval degrades gracefully to the lexical/IDF seeder = v0), or
# sentence-transformers to use the opt-in torch backend (`pip install 'yigraf[embeddings-torch]'`).
embeddings:
  backend: fastembed            # fastembed | sentence-transformers | none
  model: BAAI/bge-small-en-v1.5  # local CPU model, version-pinned, downloaded on first use
  dup_cosine: 0.9               # write-time near-duplicate threshold for `remember` (capture-flow §4)
  relevance_floor: 0.65         # `context` cosine floor below which a low-confidence banner shows (C#8).
                                # Calibrated for bge-small (off-topic ≈0.62, on-topic ≈0.68); retune per model.

# --- Status surface (int:status-surface) — the human ambient statusline ---
# The context gauge scales to a *usable budget*, not the raw window: quality and per-turn cost track
# *absolute* occupancy, so a 1M window reads ~"full" long before 100%. Denominator is
# min(host window, ctx_soft_limit): a 1M window clamps to the knee, a genuine ~200k window is
# unaffected. ~200k is where Opus-class quality degrades and cost climbs. Set 0 to use the raw window.
status:
  ctx_soft_limit: 200000        # tokens of usable budget the ctx gauge scales to (0 = raw window)
"""


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
