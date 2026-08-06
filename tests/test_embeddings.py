"""The M8 embedding layer: scoped semantic index + seeder fusion + write-time dedup.

Architecture tests run with no model (they inject vectors / a ``semantic_match`` dict, exercising the
fusion + index plumbing deterministically). The real-recall and dedup tests are marked ``embeddings``
(deselected by default; run with ``pytest -m embeddings``) and use whichever model backend is present
— fastembed (the core default) or sentence-transformers — so the suite stays backend-independent.
"""
import importlib.util
from pathlib import Path

import pytest
from typer.testing import CliRunner

from yigraf import embeddings, retrieval
from yigraf.cli import app
from yigraf.config import default_config
from yigraf.graph import empty_graph

np = pytest.importorskip("numpy")  # numpy ships with the fastembed core dep

runner = CliRunner()
_HAVE_MODEL = (importlib.util.find_spec("fastembed") is not None
               or importlib.util.find_spec("sentence_transformers") is not None)
needs_model = pytest.mark.skipif(not _HAVE_MODEL, reason="needs a model backend (fastembed or sentence-transformers)")


# --------------------------------------------------------------------------------------------------
# Model-free: node text scoping + index plumbing + fusion
# --------------------------------------------------------------------------------------------------


def test_node_text_scopes_to_memory_and_intent():
    assert embeddings.node_text({"family": "structure", "label": "foo"}) is None
    mem = embeddings.node_text({"family": "memory", "kind": "decision", "statement": "use locking",
                                "why": "it is hot", "alternatives": "no lock"})
    assert "use locking" in mem and "it is hot" in mem and "no lock" in mem
    intent = embeddings.node_text({"family": "intent", "kind": "requirement",
                                   "statement": "SHALL expire", "scenarios": ["g/w/t"], "design": "ttl"})
    assert "SHALL expire" in intent and "ttl" in intent


def test_index_save_load_and_query_round_trip(tmp_path: Path):
    runner.invoke(app, ["init", str(tmp_path)])
    ids = ["mem:001", "int:x"]
    mat = np.array([[1.0, 0.0], [0.0, 1.0]], dtype="float32")
    embeddings._save_index(tmp_path, "test-model", ids, mat, {"mem:001": "h1", "int:x": "h2"})
    cfg = default_config()
    cfg["embeddings"]["model"] = "test-model"
    idx = embeddings.load_index(tmp_path, cfg)
    assert idx is not None and idx.ids == ids
    scores = idx.query(np.array([1.0, 0.0], dtype="float32"))
    assert scores["mem:001"] > scores["int:x"]  # query aligns with mem:001's row


def test_load_index_rejects_a_model_mismatch(tmp_path: Path):
    runner.invoke(app, ["init", str(tmp_path)])
    embeddings._save_index(tmp_path, "model-a", ["mem:001"],
                           np.array([[1.0, 0.0]], dtype="float32"), {"mem:001": "h"})
    cfg = default_config()
    cfg["embeddings"]["model"] = "model-b"
    assert embeddings.load_index(tmp_path, cfg) is None  # different model ⇒ stale ⇒ reindex


def test_semantic_match_seeds_a_node_lexical_would_miss():
    g = empty_graph()
    g.add_node("int:sessions", family="intent", kind="requirement",
               statement="The system expires idle sessions", label="The system expires idle sessions")
    g.add_node("sym:a.py#f", family="structure", kind="function", label="a.py#f", signature="def f():")
    g.add_edge("int:sessions", "sym:a.py#f", relation="implements")
    cfg = default_config()
    # A query with zero lexical overlap; only the injected semantic signal points at the intent.
    lexical_only = retrieval.context(g, "wibble wobble", cfg)
    fused = retrieval.context(g, "wibble wobble", cfg, semantic_match={"int:sessions": 0.8})
    assert "int:sessions" not in lexical_only.text
    assert "int:sessions" in fused.text  # semantic seeder pulled it in (and its implementing symbol)


def test_no_backend_means_pure_lexical(tmp_path: Path):
    # With the embedder disabled (autouse fixture), the semantic path yields no scores → v0 behavior.
    runner.invoke(app, ["init", str(tmp_path)])
    assert embeddings.get_embedder(default_config()) is None
    g = empty_graph()
    assert embeddings.semantic_scores(tmp_path, g, default_config(), "anything") == {}


# --------------------------------------------------------------------------------------------------
# Model-gated: real recall + write-time dedup
# --------------------------------------------------------------------------------------------------


def _repo_with_symbol(tmp_path: Path) -> Path:
    runner.invoke(app, ["init", str(tmp_path)])
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    runner.invoke(app, ["build", str(tmp_path)])
    return tmp_path


@pytest.mark.embeddings
@needs_model
def test_real_semantic_recall_ranks_a_paraphrase(tmp_path: Path):
    root = _repo_with_symbol(tmp_path)
    runner.invoke(app, ["intent", "session-expiry", "--repo", str(root), "--status", "active",
                        "-s", "The system SHALL expire a session after 30 minutes of inactivity.",
                        "--scenario", "Given idle 30m, When a request arrives, Then 401."])
    from yigraf.extract import build_graph
    from yigraf.config import load_config
    cfg = load_config(root / "yigraf" / "config.yaml")
    graph, _ = build_graph(root, cfg)
    # A paraphrase with little lexical overlap ("log out", "stale", "untouched" vs "expire/inactivity").
    scores = embeddings.semantic_scores(root, graph, cfg, "log a user out when their login sits untouched")
    assert scores, "expected a populated index"
    assert max(scores, key=scores.get) == "int:session-expiry"


@pytest.mark.embeddings
@needs_model
def test_dedup_guard_blocks_a_near_duplicate_then_new_forces(tmp_path: Path):
    root = _repo_with_symbol(tmp_path)
    sym = "sym:auth/session.py#refresh"
    assert runner.invoke(app, ["remember", "session refresh uses optimistic locking",
                               "--why", "the path is hot", "--concerns", sym, "--repo", str(root)]).exit_code == 0
    # A near-paraphrase concerning the same symbol → the guard refuses and points at the original.
    dup = runner.invoke(app, ["remember", "refreshing a session relies on optimistic locks",
                              "--why", "hot path", "--concerns", sym, "--repo", str(root)])
    # Advisory refusal returns exit 0 + guidance (errors teach abandonment) — it declined, didn't fail.
    assert dup.exit_code == 0 and "near-duplicate" in dup.output
    # --new bypasses the advisory guard.
    forced = runner.invoke(app, ["remember", "refreshing a session relies on optimistic locks",
                                 "--why", "hot path", "--concerns", sym, "--new", "--repo", str(root)])
    assert forced.exit_code == 0


# --------------------------------------------------------------------------------------------------
# The local-only guard: no command may reach the network to load a model (design law #5)
# --------------------------------------------------------------------------------------------------
#
# The failure this pins was measured, not imagined: fastembed caches into $TMPDIR, macOS reaps
# /var/folders/…/T by access time, and the evicted ~130MB ONNX blob left a dangling snapshot symlink.
# Every later load re-fetched it through hf_xet with no wall-clock bound — a `remember` hung 10+
# minutes at 0% CPU. Two independent guards, so each is pinned separately.


#: Bound at import time — i.e. before conftest's autouse fixture stubs the module attribute out to
#: keep the suite offline. This is the only test that wants the real, network-capable function.
_REAL_FETCH_MODEL = embeddings.fetch_model


class _SpyTextEmbedding:
    """Stands in for ``fastembed.TextEmbedding`` to record how yigraf asks for a model."""

    calls: list[dict] = []

    def __init__(self, **kwargs):
        type(self).calls.append(kwargs)

    def embed(self, texts):  # pragma: no cover - never reached; we only inspect construction
        return iter([])


@pytest.fixture
def spy_fastembed(monkeypatch):
    fastembed = pytest.importorskip("fastembed")
    _SpyTextEmbedding.calls = []
    monkeypatch.setattr(fastembed, "TextEmbedding", _SpyTextEmbedding)
    return _SpyTextEmbedding


def test_implicit_model_load_is_local_only(spy_fastembed):
    """Every implicit path goes through ``_load(allow_download=False)`` — so it can never download.

    Calls ``_load`` rather than ``get_embedder`` because conftest stubs the latter out; the point here
    is precisely what the *real* function asks fastembed for.
    """
    assert embeddings._load(default_config(), allow_download=False) is not None
    assert spy_fastembed.calls[-1]["local_files_only"] is True


def test_fetch_model_probes_locally_before_it_ever_downloads(spy_fastembed):
    # Model already on disk (the spy always constructs) ⇒ the local probe settles it and no download
    # is attempted. This is the original round-trip: a cached model must cost zero network.
    assert _REAL_FETCH_MODEL(default_config()) is True
    assert [c["local_files_only"] for c in spy_fastembed.calls] == [True]


def test_fetch_model_is_the_only_path_that_may_download(monkeypatch, spy_fastembed):
    fastembed = pytest.importorskip("fastembed")

    def _only_downloadable(**kwargs):  # a genuine cache miss: local-only fails, a fetch succeeds
        if kwargs.get("local_files_only"):
            raise ValueError("not cached")
        return _SpyTextEmbedding(**kwargs)

    monkeypatch.setattr(fastembed, "TextEmbedding", _only_downloadable)
    assert _REAL_FETCH_MODEL(default_config()) is True
    assert [c["local_files_only"] for c in spy_fastembed.calls] == [False]

    # …and the implicit path, on that same miss, stays local and simply degrades.
    spy_fastembed.calls = []
    assert embeddings._load(default_config(), allow_download=False) is None
    assert spy_fastembed.calls == []


def test_model_cache_dir_is_never_a_reapable_temp_dir(monkeypatch, tmp_path: Path):
    import tempfile

    monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    default = embeddings.model_cache_dir(default_config())
    assert tempfile.gettempdir() not in str(default)
    assert default == Path.home() / ".cache" / "yigraf" / "models"

    # An explicit choice — config first, then fastembed's own env knob — is never overridden.
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path / "env"))
    assert embeddings.model_cache_dir(default_config()) == tmp_path / "env"
    cfg = dict(default_config())
    cfg["embeddings"] = {**cfg["embeddings"], "cache_dir": str(tmp_path / "cfg")}
    assert embeddings.model_cache_dir(cfg) == tmp_path / "cfg"


def test_a_missing_model_degrades_to_lexical_rather_than_raising(monkeypatch):
    """int:semantic-recall's fallback scenario, for the cache-miss case specifically."""
    import fastembed

    def _always_missing(**kwargs):
        raise ValueError("model not found locally")

    monkeypatch.setattr(fastembed, "TextEmbedding", _always_missing)
    assert embeddings._load(default_config(), allow_download=False) is None
    assert embeddings.model_cached(default_config()) is False
