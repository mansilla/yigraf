"""Scoped semantic retrieval: a lightweight embedding index over memory + intent text (M8).

Per ``docs/retrieval-design.md`` §10, we embed **only** the memory + intent node families
(decisions, requirements — tens to thousands of short statements, *not* the codebase), so the index
is tiny and a query is a single numpy matmul (exact, sub-millisecond). Two layers, kept separate:

- the **model** (text → vector): a pluggable backend, default **local ``bge-small-en-v1.5``** (CPU,
  no API key, version-pinned, downloaded on first use);
- the **index** (vectors + nearest-neighbour): a plain numpy matrix + id map under the gitignored
  ``yigraf/index/``, brute-force cosine — no FAISS/vector-DB at this scale (§10).

**Everything degrades gracefully.** If numpy or the model backend is unavailable, the embedder is
``None``, the index stays empty, and retrieval falls back to the lexical/IDF seeder (= v0). Semantic
recall is an enhancement, never a hard dependency — so this module is import-safe with the
``[embeddings]`` extra uninstalled, and every public function returns an empty/None result instead of
raising when a backend is missing.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

try:  # numpy is part of the optional [embeddings] extra; absence ⇒ lexical-only fallback.
    import numpy as np
except ImportError:  # pragma: no cover - exercised only in a lexical-only environment
    np = None  # type: ignore

#: Embedded families (retrieval-design §10 — we never embed code; Graphify's IDF already nails that).
_EMBED_FAMILIES = frozenset({"memory", "intent"})

#: bge models expect this instruction prefixed to the *query* (not the documents) for retrieval.
_BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


# --------------------------------------------------------------------------------------------------
# Node → embedding text
# --------------------------------------------------------------------------------------------------


def node_text(attrs: dict) -> str | None:
    """The text embedded for a node, or ``None`` if its family isn't embedded.

    Memory: ``<type>: <statement>`` + the ``why`` + any rejected alternative (the words an agent
    queries for). Intent: ``<type>: <statement>`` + scenarios + design. Short, one vector per node.
    """
    family = attrs.get("family")
    if family not in _EMBED_FAMILIES:
        return None
    kind = attrs.get("kind", family)
    if family == "memory":
        parts = [f"{kind}: {attrs.get('statement') or attrs.get('label', '')}"]
        if attrs.get("why"):
            parts.append(str(attrs["why"]))
        if attrs.get("alternatives"):
            parts.append(str(attrs["alternatives"]))
        return "\n".join(parts)
    # intent
    parts = [f"{kind}: {attrs.get('statement') or attrs.get('label', '')}"]
    parts.extend(attrs.get("scenarios") or [])
    if attrs.get("design"):
        parts.append(str(attrs["design"]))
    return "\n".join(parts)


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------------------
# Model layer (pluggable; local sentence-transformers default)
# --------------------------------------------------------------------------------------------------


class _LocalEmbedder:
    """A local ``sentence-transformers`` backend (default ``bge-small-en-v1.5``)."""

    def __init__(self, model: Any, name: str) -> None:
        self._model = model
        self.name = name

    def encode(self, texts: list[str]) -> "np.ndarray":
        # normalize_embeddings=True ⇒ cosine similarity is a plain dot product downstream.
        return self._model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)


def _emb_config(config: dict) -> dict:
    return config.get("embeddings", {}) if isinstance(config, dict) else {}


def model_name(config: dict) -> str:
    return _emb_config(config).get("model", "BAAI/bge-small-en-v1.5")


def get_embedder(config: dict):
    """Load the configured embedding backend, or ``None`` if unavailable (⇒ lexical fallback).

    Never raises: a missing extra, an offline first-run download failure, or an unknown backend all
    resolve to ``None`` so the caller silently degrades to the v0 lexical seeder.
    """
    if np is None:
        return None
    backend = _emb_config(config).get("backend", "local")
    if backend in (None, "none"):
        return None
    if backend != "local":
        return None  # ollama/openai/voyage backends are post-M8 (retrieval-design §10) — degrade.
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    try:
        name = model_name(config)
        return _LocalEmbedder(SentenceTransformer(name), name)
    except Exception:  # pragma: no cover - network/model-load failure ⇒ degrade, never crash
        return None


def backend_available(config: dict) -> bool:
    """Whether the semantic backend's deps are importable — a cheap probe that never loads the model.

    Distinct from ``get_embedder``, which instantiates (and may download) the model. ``yigraf install``
    uses this to decide whether to nudge the user toward the ``[embeddings]`` extra without paying a
    model load: a missing extra ⇒ ``False`` ⇒ the install prints the one-line turn-on command.
    """
    if np is None:
        return False
    backend = _emb_config(config).get("backend", "local")
    if backend in (None, "none") or backend != "local":
        return False
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False
    return True


def _embed_query_text(query: str, name: str) -> str:
    return (_BGE_QUERY_INSTRUCTION + query) if "bge" in name.lower() else query


# --------------------------------------------------------------------------------------------------
# Index layer (numpy matrix + id map, gitignored + rebuildable)
# --------------------------------------------------------------------------------------------------


def index_dir(root: Path) -> Path:
    return Path(root) / "yigraf" / "index"


@dataclass
class EmbeddingIndex:
    """A loaded embedding index: aligned ``ids`` ↔ rows of the (N, dim) ``matrix`` (L2-normalized)."""

    model: str
    ids: list[str]
    matrix: Any  # np.ndarray (N, dim); rows align with `ids`
    text_hash: dict[str, str] = field(default_factory=dict)

    def query(self, qvec: "np.ndarray") -> dict[str, float]:
        """Cosine of ``qvec`` against every indexed node → ``{id: score}`` (matrix is normalized)."""
        if np is None or self.matrix is None or len(self.ids) == 0:
            return {}
        scores = self.matrix @ qvec  # both normalized ⇒ dot == cosine
        return {nid: float(s) for nid, s in zip(self.ids, scores)}

    def vector(self, node_id: str) -> "np.ndarray | None":
        try:
            return self.matrix[self.ids.index(node_id)]
        except (ValueError, TypeError):
            return None


def load_index(root: Path, config: dict) -> EmbeddingIndex | None:
    """Load the on-disk index, or ``None`` if absent/unreadable/built for a different model."""
    if np is None:
        return None
    d = index_dir(root)
    meta_path, vec_path = d / "meta.json", d / "vectors.npy"
    if not (meta_path.exists() and vec_path.exists()):
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("model") != model_name(config):
            return None  # model changed ⇒ stale index, force a reindex
        matrix = np.load(vec_path)
        entries = meta.get("entries", [])
        ids = [e["id"] for e in entries]
        text_hash = {e["id"]: e.get("hash", "") for e in entries}
        if matrix.shape[0] != len(ids):
            return None
        return EmbeddingIndex(model=meta["model"], ids=ids, matrix=matrix, text_hash=text_hash)
    except Exception:  # pragma: no cover - a corrupt index ⇒ rebuild, never crash a query
        return None


def _save_index(root: Path, model: str, ids: list[str], matrix: "np.ndarray",
                text_hash: dict[str, str]) -> None:
    d = index_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    meta = {"model": model, "dim": int(matrix.shape[1]) if matrix.size else 0,
            "entries": [{"id": nid, "hash": text_hash.get(nid, "")} for nid in ids]}
    np.save(d / "vectors.npy", matrix)
    (d / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def refresh_index(root: Path, graph: nx.DiGraph, config: dict) -> bool:
    """Re-embed only the memory/intent nodes whose text changed; persist the index. Returns changed?

    Loads the model **only when there is work to do** (a new/changed node), so a steady-state build
    with no spec/memory edits costs nothing — safe to call from the capture verbs and ``yigraf build``
    without paying a model load on every invocation. A missing backend ⇒ no-op (lexical fallback).
    """
    if np is None:
        return False

    desired: dict[str, str] = {}
    for node_id, attrs in graph.nodes(data=True):
        text = node_text(attrs)
        if text is not None:
            desired[node_id] = text
    desired_ids = sorted(desired)

    existing = load_index(root, config)
    old_vec = {nid: existing.vector(nid) for nid in existing.ids} if existing else {}
    old_hash = existing.text_hash if existing else {}

    to_embed = [nid for nid in desired_ids
                if _text_hash(desired[nid]) != old_hash.get(nid) or old_vec.get(nid) is None]
    dropped = bool(existing) and set(existing.ids) - set(desired_ids)

    if not to_embed and not dropped and existing is not None:
        return False  # nothing changed → don't even load the model

    embedder = get_embedder(config)
    if embedder is None:
        return False  # no backend → leave any existing index in place, degrade to lexical

    new_vecs = {}
    if to_embed:
        encoded = embedder.encode([desired[nid] for nid in to_embed])
        new_vecs = {nid: encoded[i] for i, nid in enumerate(to_embed)}

    rows, text_hash = [], {}
    for nid in desired_ids:
        vec = new_vecs.get(nid)
        if vec is None:
            vec = old_vec.get(nid)
        rows.append(vec)
        text_hash[nid] = _text_hash(desired[nid])
    matrix = np.vstack(rows) if rows else np.zeros((0, 0), dtype="float32")
    _save_index(root, model_name(config), desired_ids, matrix, text_hash)
    return True


# --------------------------------------------------------------------------------------------------
# Query-time semantic scoring + write-time dedup
# --------------------------------------------------------------------------------------------------


def semantic_scores(root: Path, graph: nx.DiGraph, config: dict, query: str) -> dict[str, float]:
    """``{node_id: cosine}`` for the query against the indexed memory/intent nodes still in ``graph``.

    Returns ``{}`` (⇒ pure lexical seeding) when there's no index or no backend.
    """
    index = load_index(root, config)
    if index is None:
        return {}
    embedder = get_embedder(config)
    if embedder is None:
        return {}
    qvec = embedder.encode([_embed_query_text(query, index.model)])[0]
    return {nid: s for nid, s in index.query(qvec).items() if nid in graph}


def most_similar_memory(root: Path, graph: nx.DiGraph, config: dict, text: str,
                        scope: set[str]) -> tuple[str, float] | None:
    """The most semantically similar *active* memory node to ``text`` for the write-time dedup guard.

    Restricts to active (non-superseded) memory nodes; when ``scope`` (the new node's serves/concerns
    targets) is non-empty, only considers nodes that share at least one of those targets — a decision
    about unrelated code isn't a duplicate. Returns ``(id, cosine)`` or ``None`` (no backend/candidate).
    """
    index = load_index(root, config)
    if index is None:
        return None
    embedder = get_embedder(config)
    if embedder is None:
        return None
    vec = embedder.encode([text])[0]

    best: tuple[str, float] | None = None
    for node_id in index.ids:
        attrs = graph.nodes.get(node_id, {})
        if attrs.get("family") != "memory" or attrs.get("status") != "active":
            continue
        if attrs.get("superseded_in", 0):
            continue
        if scope and not (_memory_targets(graph, node_id) & scope):
            continue
        nv = index.vector(node_id)
        if nv is None:
            continue
        cos = float(nv @ vec)
        if best is None or cos > best[1]:
            best = (node_id, cos)
    return best


def _memory_targets(graph: nx.DiGraph, mem_id: str) -> set[str]:
    return {d for _, d, a in graph.out_edges(mem_id, data=True)
            if a.get("relation") in ("serves", "concerns")}
