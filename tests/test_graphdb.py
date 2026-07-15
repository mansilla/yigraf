"""The gitignored SQLite materialized view (task concurrent-write-v1/5, int:yigraf-local-v1).

Truth is the content-addressed markdown; ``graphdb`` is the derived, gitignored projection that
replaces the committed ``graph.json`` (mem:059). These tests pin its contract: a materialize→load
round-trip is byte-canonical with the in-memory graph, the fingerprint is a faithful cache key over
the graph's inputs, ``load_or_build`` skips the rebuild only while inputs are unchanged, and any
corruption falls open to ``None`` (⇒ a caller rebuilds) rather than raising.
"""
import json
import sqlite3
from pathlib import Path

from yigraf import graphdb
from yigraf.config import default_config
from yigraf.extract import build_graph
from yigraf.graph import to_node_link


def _canon(g) -> str:
    return json.dumps(to_node_link(g), sort_keys=True)


def _repo(tmp_path: Path) -> Path:
    """An initialized repo with one source file (no build yet)."""
    from yigraf.scaffold import init_workspace

    init_workspace(tmp_path)
    (tmp_path / "m.py").write_text("def f(x):\n    return x + 1\n")
    return tmp_path


def test_materialize_load_round_trip_is_canonical(tmp_path: Path):
    root = _repo(tmp_path)
    cfg = default_config()
    graph, _ = build_graph(root, cfg)
    graphdb.materialize(graph, graphdb.db_path(root), "fp-abc")
    loaded = graphdb.load(graphdb.db_path(root))
    assert loaded is not None
    assert _canon(loaded) == _canon(graph)  # nodes, edges, attrs, and g.graph all round-trip
    assert loaded.graph.get("anchor_algo") == graph.graph.get("anchor_algo")


def test_db_lives_under_gitignored_local(tmp_path: Path):
    root = _repo(tmp_path)
    assert graphdb.db_path(root) == root / "yigraf" / ".local" / "graph.db"


def test_stored_fingerprint_reads_back_what_was_written(tmp_path: Path):
    root = _repo(tmp_path)
    graph, _ = build_graph(root, default_config())
    graphdb.materialize(graph, graphdb.db_path(root), "fp-xyz")
    assert graphdb.stored_fingerprint(graphdb.db_path(root)) == "fp-xyz"


def test_load_and_fingerprint_are_none_when_absent_or_corrupt(tmp_path: Path):
    root = _repo(tmp_path)
    db = graphdb.db_path(root)
    assert graphdb.load(db) is None                # absent
    assert graphdb.stored_fingerprint(db) is None
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"not a sqlite database at all")  # corrupt
    assert graphdb.load(db) is None
    assert graphdb.stored_fingerprint(db) is None


def test_schema_bump_invalidates_the_view(tmp_path: Path):
    root = _repo(tmp_path)
    graph, _ = build_graph(root, default_config())
    db = graphdb.db_path(root)
    graphdb.materialize(graph, db, "fp")
    # A view written under a different schema version reads as absent (⇒ rebuild), never mis-parsed.
    conn = sqlite3.connect(db)
    conn.execute("UPDATE meta SET value = ? WHERE key = 'db_schema_version'", ("999",))
    conn.commit()
    conn.close()
    assert graphdb.load(db) is None
    assert graphdb.stored_fingerprint(db) is None


def test_source_fingerprint_stable_then_changes_on_source_edit(tmp_path: Path):
    root = _repo(tmp_path)
    cfg = default_config()
    fp1 = graphdb.source_fingerprint(root, cfg)
    assert fp1 == graphdb.source_fingerprint(root, cfg)  # deterministic, no side effects
    (root / "m.py").write_text("def f(x):\n    return x + 2\n")  # body changed
    assert graphdb.source_fingerprint(root, cfg) != fp1


def test_source_fingerprint_changes_on_assertion_edit(tmp_path: Path):
    """An authored artifact is an input to the fold, so touching one must invalidate the view."""
    root = _repo(tmp_path)
    cfg = default_config()
    fp1 = graphdb.source_fingerprint(root, cfg)
    (root / "yigraf" / "intents" / "x.md").write_text("---\nid: int:x\nfamily: intent\n---\n# X\n")
    assert graphdb.source_fingerprint(root, cfg) != fp1


def test_load_or_build_caches_then_rebuilds_on_change(tmp_path: Path):
    root = _repo(tmp_path)
    cfg = default_config()

    g1, cached1 = graphdb.load_or_build(root, cfg)
    assert cached1 is False and graphdb.db_path(root).is_file()  # first call built + materialized

    g2, cached2 = graphdb.load_or_build(root, cfg)
    assert cached2 is True                        # second call served from the view (inputs unchanged)
    assert _canon(g1) == _canon(g2)               # and it is the same graph

    (root / "m.py").write_text("def f(x):\n    return x + 99\n")
    g3, cached3 = graphdb.load_or_build(root, cfg)
    assert cached3 is False                        # source changed ⇒ rebuild
    assert _canon(g3) != _canon(g1)


def test_persisted_view_strips_volatile_attrs(tmp_path: Path):
    """R1/mem:034 #10: the same volatile/git-HEAD overlays stripped from graph.json are stripped here —
    they are re-applied on the in-memory graph after a load, not persisted."""
    root = _repo(tmp_path)
    graph, _ = build_graph(root, default_config())
    for _, attrs in graph.nodes(data=True):       # simulate read-time overlays on the in-memory graph
        attrs["survival"] = 7
        attrs["usage"] = 3
    graphdb.materialize(graph, graphdb.db_path(root), "fp")
    loaded = graphdb.load(graphdb.db_path(root))
    assert all("survival" not in a and "usage" not in a for _, a in loaded.nodes(data=True))


def test_load_or_build_matches_a_fresh_build(tmp_path: Path):
    """The cached read path is query-equivalent to a from-scratch build (the migration proof, scaled down)."""
    root = _repo(tmp_path)
    cfg = default_config()
    graphdb.load_or_build(root, cfg)              # populate the view
    cached, was_cached = graphdb.load_or_build(root, cfg)
    fresh, _ = build_graph(root, cfg)
    assert was_cached is True
    assert _canon(cached) == _canon(fresh)
