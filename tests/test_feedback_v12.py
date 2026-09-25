"""The field's ninth report: concurrent sidecar writes, the `graph` phase's sub-steps, and the statusline.

L#1 is a concurrency defect, so its tests run real **processes** that start together — a thread-level
test would pass on the unlocked code under the GIL often enough to prove nothing. Each asserts a count
against a file on disk: N writers, N updates kept. The field measured 8 hooks keeping 6–7 ledger rows;
we measured 16 surfacing bumps landing as `usage=7`.
"""
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from yigraf import cli, graphdb, hookbudget, sidecar, status
from yigraf.cli import app
from yigraf.config import load_config

runner = CliRunner()

WRITERS = 8


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    (tmp_path / "mod.py").write_text("def widget():\n    return 1\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _together(body: str, root: Path, n: int = WRITERS) -> None:
    """Run ``body`` in ``n`` fresh interpreters that all start the critical part at one instant.

    ``body`` sees ``root`` (a Path) and ``i`` (its index). Imports happen before the start line, so the
    processes collide on the write, not on interpreter startup.
    """
    start = time.time() + 2.0
    script = textwrap.dedent("""
        import sys, time
        from pathlib import Path
        import networkx as nx
        from yigraf import cli, counters, hookbudget
        root, i, start = Path(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
        while time.time() < start:
            time.sleep(0.001)
    """) + textwrap.dedent(body)
    procs = [subprocess.Popen([sys.executable, "-c", script, str(root), str(i), str(start)])
             for i in range(n)]
    assert all(p.wait(timeout=60) == 0 for p in procs)


# --- L#1: every concurrent read-modify-write keeps every update ---------------------------------

def test_concurrent_surfacing_bumps_are_all_counted(tmp_path):
    """`usage` feeds the relevance prior; unlocked, concurrent edit hooks each lost the other's bump."""
    _together("""
        g = nx.DiGraph(); g.add_node("mem:x", family="memory")
        counters.record_injection(root, g, ["mem:x"])
        counters.record_uphold(root, g, ["mem:x"], 1.0)
    """, tmp_path)
    entry = json.loads((tmp_path / "yigraf" / ".local" / "telemetry.json").read_text())["mem:x"]
    assert entry["usage"] == WRITERS
    assert entry["upholds"] == WRITERS


def test_concurrent_hooks_each_leave_their_ledger_row(tmp_path):
    """The instrument shipped for K#4 under-counted the bursts it exists to explain."""
    _together("""
        config = {"hooks": {"slow_run_ms": 0, "timings_kept": 200}}
        with hookbudget.Budget(root, "PostToolUse", config):
            pass
    """, tmp_path)
    assert len(hookbudget.read_ledger(tmp_path)) == WRITERS


def test_concurrent_edit_hooks_each_latch_their_packet(tmp_path):
    """A lost latch entry re-injects a packet the agent already holds — the 3.47M-token defect."""
    _together("""
        assert cli._already_emitted(root, "s", f"file:{i}.py", "digest") is False
    """, tmp_path)
    latch = json.loads((tmp_path / "yigraf" / ".local" / "emitted.json").read_text())
    assert len(latch["s"]) == WRITERS
    assert all(cli._already_emitted(tmp_path, "s", f"file:{i}.py", "digest") for i in range(WRITERS))


def test_a_held_lock_delays_the_writer_and_then_lets_it_through(tmp_path):
    """Fail-open: a lock nobody releases costs one wait, never a hook that cannot record (law #5)."""
    import fcntl

    target = tmp_path / "state.json"
    holder = os.open(target.with_name("state.json.lock"), os.O_CREAT | os.O_WRONLY)
    fcntl.flock(holder, fcntl.LOCK_EX)
    try:
        began = time.monotonic()
        with sidecar.locked(target):
            sidecar.write_atomic(target, "{}")
        waited = time.monotonic() - began
    finally:
        os.close(holder)
    assert target.read_text() == "{}"
    assert sidecar.LOCK_WAIT_SECONDS <= waited < sidecar.LOCK_WAIT_SECONDS + 1.0


def test_an_atomic_write_replaces_the_file_and_leaves_no_temp(tmp_path):
    """Truncate-in-place let a lock-free reader parse a prefix and fall back to empty (the torn read)."""
    target = tmp_path / "deep" / "state.json"
    sidecar.write_atomic(target, '{"a": 1}')
    before = target.stat().st_ino
    sidecar.write_atomic(target, '{"a": 2}')
    assert json.loads(target.read_text()) == {"a": 2}
    assert target.stat().st_ino != before, "same inode ⇒ written in place, readable half-done"
    assert [p.name for p in target.parent.iterdir()] == ["state.json"]


# --- the materialized view: its temp file and its fingerprint -----------------------------------

def test_materialize_writes_through_a_per_process_temp_and_sweeps_dead_ones(tmp_path):
    """Two rebuilding hooks shared `graph.db.tmp`: one could unlink or rename the other's half-written view."""
    root = _repo(tmp_path)
    local = graphdb.db_path(root).parent
    dead = local / "graph.db.99999.tmp"
    dead.write_text("killed mid-write")
    old = time.time() - graphdb._ORPHAN_TEMP_SECONDS - 60
    os.utime(dead, (old, old))
    live = local / "graph.db.88888.tmp"
    live.write_text("another writer, right now")

    graph, _ = graphdb.rebuild(root, load_config(root / "yigraf" / "config.yaml"))
    assert graphdb.load(graphdb.db_path(root)) is not None
    assert not dead.exists(), "a killed writer's temp is never reused under per-pid names — sweep it"
    assert live.exists(), "a live writer's temp must survive, or its rename fails"


def test_a_cache_miss_walks_the_tree_once_not_twice(tmp_path, monkeypatch):
    """`graph.materialize` measured about equal to `graph.fingerprint`: it was a second full walk."""
    root = _repo(tmp_path)
    config = load_config(root / "yigraf" / "config.yaml")
    (root / "mod.py").write_text("def widget():\n    return 2\n")
    walks = []
    real = graphdb.source_fingerprint
    monkeypatch.setattr(graphdb, "source_fingerprint", lambda *a, **k: walks.append(1) or real(*a, **k))

    graph, cached = graphdb.load_or_build(root, config)
    assert not cached
    assert len(walks) == 1
    assert graphdb.stored_fingerprint(graphdb.db_path(root)) == real(root, config,
                                                                   graphdb.governed_file_paths(graph))
    assert graphdb.load_or_build(root, config)[1], "the reused digest must still key a hit next read"


def test_the_graph_phase_names_its_steps(tmp_path):
    """One `graph` label covered the walk, the extraction and the write-back — three remedies."""
    root = _repo(tmp_path)
    config = load_config(root / "yigraf" / "config.yaml")
    (root / "mod.py").write_text("def widget():\n    return 3\n")
    with hookbudget.Budget(root, "PostToolUse", {}) as miss:
        graphdb.load_or_build(root, config, budget=miss)
    with hookbudget.Budget(root, "PostToolUse", {}) as hit:
        graphdb.load_or_build(root, config, budget=hit)
    assert [n for n, _ in miss.phases] == ["graph.fingerprint", "graph.build", "graph.materialize"]
    assert [n for n, _ in hit.phases] == ["graph.fingerprint", "graph.load"]


def test_the_stop_hook_walks_once(tmp_path, monkeypatch):
    """It walked for its latch, then `load_or_build` walked again — on every session's first turn too."""
    root = _repo(tmp_path)
    walks = []
    real = graphdb.source_fingerprint
    monkeypatch.setattr(graphdb, "source_fingerprint", lambda *a, **k: walks.append(1) or real(*a, **k))
    cli._stop({"cwd": str(root), "session_id": "fresh", "hook_event_name": "Stop"})
    assert len(walks) == 1


# --- the statusline ------------------------------------------------------------------------------

def _statusline(cwd: Path, **workspace):
    event = {"cwd": str(cwd), "workspace": {"current_dir": str(cwd), **workspace}}
    return runner.invoke(app, ["statusline"], input=json.dumps(event), color=False)


def test_the_statusline_reads_the_view_instead_of_rebuilding(tmp_path, monkeypatch):
    """It ran a bare `build_graph` per refresh: every file re-read and hashed, the cache rewritten."""
    root = _repo(tmp_path)
    cache = root / "yigraf" / "cache" / "structure.json"
    stamp = cache.stat().st_mtime_ns
    monkeypatch.setattr(status, "_freshness", lambda *a: pytest.fail("the view IS the graph here"))
    out = _statusline(root).output
    assert "sym" in out and "fresh" in out
    assert cache.stat().st_mtime_ns == stamp, "a warm refresh rewrote the extraction cache"


def test_a_session_below_the_store_root_says_so_on_the_bar(tmp_path):
    """SessionStart named the store once; the bar stayed blank all session, like an unwired install."""
    root = _repo(tmp_path)
    (root / "sub").mkdir()
    out = _statusline(root / "sub", project_dir=str(root / "sub")).output
    assert "no store here" in out and str(root.resolve()) in out


def test_an_unrelated_repo_still_gets_a_blank_bar(tmp_path):
    """The common case: no store anywhere above. Silence, as before (law #4)."""
    (tmp_path / "plain").mkdir()
    assert _statusline(tmp_path / "plain").output == ""
