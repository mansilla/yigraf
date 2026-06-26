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
                  "ruby", "php", "c_sharp", "kotlin", "scala", "swift"],
    "ignore": [".git/", "__pycache__/", ".venv/", "node_modules/", "origins/"],
    # Maturity (R2): a memory node settles after K commits on the default branch un-superseded.
    "maturity_k": 3,
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
    },
    # Relevance prior weights (graph-design §3). Tuned empirically later.
    #   w1·log(1+refs_in) + w2·recency(last_seen) + w3·maturity − w4·[superseded_in>0]
    "relevance": {"w1": 1.0, "w2": 1.0, "w3": 1.0, "w4": 1.0, "half_life_days": 14},
    # Embeddings (M8) — scoped semantic recall over memory+intent only (retrieval-design §10).
    # Optional: install the `[embeddings]` extra. Absent backend ⇒ graceful lexical-only fallback.
    "embeddings": {
        "backend": "local",  # local | ollama | openai | none
        "model": "BAAI/bge-small-en-v1.5",
        "dup_cosine": 0.9,  # write-time near-duplicate threshold for `remember` (capture-flow §4)
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
# (rust, java, c, cpp, ruby, php); yigraf-vendored tags-query extractors (c_sharp, kotlin, scala, swift).
languages: [python, go, javascript, typescript, rust, java, c, cpp, ruby, php,
            c_sharp, kotlin, scala, swift]
ignore:                        # path prefixes skipped when indexing the repo
  - .git/
  - __pycache__/
  - .venv/
  - node_modules/
  - origins/

# --- Maturity (R2) ---
maturity_k: 3                  # commits on the default branch un-superseded before a memory "settles"

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

# --- Relevance prior (docs/graph-design.md §3) ---
relevance:                     # w1·log(1+refs_in) + w2·recency + w3·maturity − w4·[superseded_in>0]
  w1: 1.0
  w2: 1.0
  w3: 1.0
  w4: 1.0
  half_life_days: 14           # recency exp-decay half-life on last_seen (M9 runtime counter)

# --- Embeddings (M8) — scoped semantic recall over memory+intent (docs/retrieval-design.md §10) ---
# Optional: requires the `[embeddings]` extra (numpy + sentence-transformers). With no backend,
# retrieval degrades gracefully to the lexical/IDF seeder (= v0) — semantic recall is never required.
embeddings:
  backend: local                # local | ollama | openai | none
  model: BAAI/bge-small-en-v1.5  # local CPU model, version-pinned, downloaded on first use
  dup_cosine: 0.9               # write-time near-duplicate threshold for `remember` (capture-flow §4)
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
