"""The gitignored SQLite materialized view (task concurrent-write-v1/5, int:yigraf-local-v1).

Truth is the content-addressed markdown; ``graphdb`` is the derived, gitignored projection that
replaces the committed ``graph.json`` (mem:059). These tests pin its contract: a materialize→load
round-trip is byte-canonical with the in-memory graph, the fingerprint is a faithful cache key over
the graph's inputs, ``load_or_build`` skips the rebuild only while inputs are unchanged, and any
corruption falls open to ``None`` (⇒ a caller rebuilds) rather than raising.
"""
import errno
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

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


# -- an unwritable view: guidance, never a traceback (design law #1), and never a failed command (#5) --


def _unwritable_repo(tmp_path: Path) -> Path:
    """A repo whose ``.local/`` is a regular FILE, so every write to the view fails.

    Chosen over ``chmod`` deliberately: it reproduces the same condition on any platform and under any
    uid (a root-run CI would sail straight through a 0o555 directory), and it fails at the same seam a
    read-only mount does.
    """
    root = _repo(tmp_path)
    local = root / "yigraf" / ".local"
    shutil.rmtree(local, ignore_errors=True)
    local.write_text("not a directory")
    return root


def test_an_unwritable_view_raises_guidance_not_a_storage_error(tmp_path: Path):
    """Design law #1: the caller gets the fix, not a ``sqlite3``/``OSError`` to interpret."""
    root = _unwritable_repo(tmp_path)
    graph, _ = build_graph(root, default_config())
    with pytest.raises(graphdb.ViewUnwritable) as caught:
        graphdb.materialize(graph, graphdb.db_path(root), "fp")
    guidance = caught.value.guidance
    assert "graph.db" in guidance and "Nothing was lost" in guidance   # names the file + what it costs
    assert "yigraf/" in guidance                                        # and where the truth still lives
    assert isinstance(caught.value.cause, OSError)                      # the real error is kept, not lost


def test_unwritable_guidance_names_the_fix_for_each_cause():
    """Each branch hands back the ONE correction that clears it — not a description of the failure."""
    path = Path("/repo/yigraf/.local/graph.db")
    denied = graphdb._unwritable_guidance(path, PermissionError(errno.EACCES, "Permission denied"))
    assert "permissions" in denied and "root" in denied      # incl. the sudo-left-it-root-owned case
    full = graphdb._unwritable_guidance(path, OSError(errno.ENOSPC, "No space left on device"))
    assert "full" in full and "free some space" in full


def test_a_read_never_fails_because_the_cache_cannot_be_written(tmp_path: Path):
    """Design law #5: `context`/hooks answer from the build when the view can't be refreshed."""
    root = _unwritable_repo(tmp_path)
    cfg = default_config()
    graph, was_cached = graphdb.load_or_build(root, cfg)     # must not raise
    fresh, _ = build_graph(root, cfg)
    assert was_cached is False
    assert graph.graph.pop("view_unwritable")                # the only difference is the parked guidance
    assert _canon(graph) == _canon(fresh)                    # the answer is the full, correct graph
    assert graphdb.load_or_build(root, cfg)[1] is False      # and every later read rebuilds, uncached


def test_rebuild_hands_the_caller_the_guidance_to_surface(tmp_path: Path):
    """The write seam keeps building — the CLI reads the flag and speaks (`build`, `_rebuild`)."""
    root = _unwritable_repo(tmp_path)
    graph, stats = graphdb.rebuild(root, default_config())   # must not raise
    assert stats.files >= 1 and graph.number_of_nodes() > 0  # the work itself succeeded
    assert "Couldn't cache the graph" in graph.graph["view_unwritable"]


def test_the_unwritable_flag_never_enters_the_persisted_view(tmp_path: Path):
    """Design law #6: a per-run signal is stripped at store time, like every other volatile attr."""
    root = _repo(tmp_path)
    graph, _ = build_graph(root, default_config())
    graph.graph["view_unwritable"] = "stale guidance from an earlier failure"
    graphdb.materialize(graph, graphdb.db_path(root), "fp")
    loaded = graphdb.load(graphdb.db_path(root))
    assert "view_unwritable" not in loaded.graph


def test_a_programming_error_is_not_disguised_as_an_unwritable_view(tmp_path: Path, monkeypatch):
    """The catch is narrow on purpose: a real bug must surface as itself, not as bad permissions."""
    root = _repo(tmp_path)
    graph, _ = build_graph(root, default_config())

    class _BuggyConn:
        def executescript(self, *_a):
            raise sqlite3.IntegrityError("UNIQUE constraint failed: nodes.id")

        def close(self):
            pass

    monkeypatch.setattr(graphdb.sqlite3, "connect", lambda *_a, **_k: _BuggyConn())
    with pytest.raises(sqlite3.IntegrityError):
        graphdb.materialize(graph, graphdb.db_path(root), "fp")
