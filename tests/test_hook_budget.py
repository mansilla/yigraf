"""The hook's own wall-clock budget and its slow-run ledger (feedback-v11 K#4).

The field measured yigraf's hooks being cancelled at the `"timeout": 15` our own installer writes — 24
cancellations across 58 transcripts — each failing silently and differently. Reproduction failed here
(every hook sub-second on a 2404-symbol store), so none of these tests claim anything about *why* a
render is slow. What they pin is the part that was wrong whatever the cause: a hook that runs out of
time must degrade to something honest instead of being killed having emitted nothing, and must leave
evidence behind.

Each test forces the trip with a tiny `hooks.deadline_seconds` and a slow step, because the interesting
behaviour is what yigraf does at the boundary, not how long anything takes.
"""
import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from yigraf import cli, graphdb, hookbudget, obligations, retrieval
from yigraf.cli import app

runner = CliRunner()


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    (tmp_path / "mod.py").write_text("def widget():\n    return 1\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _budget(root: Path, seconds, slow_ms: int = 2000) -> None:
    """Rewrite the store's hook budget — on disk, because that is what a real store tunes."""
    cfg = root / "yigraf" / "config.yaml"
    cfg.write_text(cfg.read_text() + f"\nhooks:\n  deadline_seconds: {seconds}\n"
                                     f"  slow_run_ms: {slow_ms}\n  timings_kept: 5\n")


def _payload(root: Path, event: str = "SessionStart", **extra) -> dict:
    return {"session_id": "probe", "hook_event_name": event, "source": "startup",
            "cwd": str(root), **extra}


def _edit_payload(root: Path) -> dict:
    return _payload(root, "PostToolUse", tool_name="Edit",
                    tool_input={"file_path": str(root / "mod.py")})


# --- the deadline degrades instead of dying ------------------------------------------------------

def test_session_start_serves_the_previous_packet_when_the_render_runs_out_of_budget(tmp_path, monkeypatch):
    """The field's third ask. A lost SessionStart packet leaves the session acting as though the store
    did not exist — and that is indistinguishable from yigraf correctly having nothing to say."""
    root = _repo(tmp_path)
    first = cli._session_start(_payload(root))
    assert first is not None, "precondition: this store renders a packet at all"
    original = first["hookSpecificOutput"]["additionalContext"]

    _budget(root, 0.2)
    real = retrieval.session_context
    monkeypatch.setattr(retrieval, "session_context",
                        lambda *a, **k: (time.sleep(1.5), real(*a, **k))[1])
    out = cli._session_start(_payload(root))

    assert out is not None, "a timed-out render must not be silent — that is the defect"
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "exceeded its 0.2s budget" in text
    assert "PREVIOUS packet" in text and "yigraf doctor" in text
    assert original in text, "the cached packet is served, not merely described"


def test_session_start_says_so_when_it_times_out_with_no_cached_packet(tmp_path, monkeypatch):
    """Nothing honest to serve is still not a reason to say nothing."""
    root = _repo(tmp_path)
    _budget(root, 0.2)
    monkeypatch.setattr(retrieval, "session_context",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("unreachable")))
    monkeypatch.setattr(cli, "_ranked_with_telemetry", lambda *a, **k: time.sleep(1.5))
    out = cli._session_start(_payload(root))

    text = out["hookSpecificOutput"]["additionalContext"]
    assert "has NOT been oriented" in text and "yigraf context" in text
    assert "PREVIOUS packet" not in text


def test_the_edit_hook_names_the_timeout_and_never_serves_a_stale_drift_packet(tmp_path, monkeypatch):
    """The one place serve-stale is WRONG: this payload describes the symbol just edited, so a cached
    one describes the code as it was before the edit that triggered the hook."""
    root = _repo(tmp_path)
    _budget(root, 0.05)
    monkeypatch.setattr(cli, "_ranked_with_telemetry", lambda *a, **k: time.sleep(0.4))
    out = cli._post_tool_use(_edit_payload(root))

    assert out is not None
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "exceeded the 0.05s hook budget" in text
    assert "NOT 'nothing governs it'" in text, "a timeout must not read as the silent-unless default"
    assert 'yigraf context "mod.py"' in text, "the path it hands over must be repo-relative, not the host's absolute one"
    assert "PREVIOUS" not in text and "Decisions (why)" not in text


def test_the_stop_hook_stays_silent_on_a_timeout(tmp_path, monkeypatch):
    """The principal's ambient channel is edge-triggered and costs the agent nothing, so a missed turn
    costs a notice the next turn re-raises — not knowledge. Announcing the timeout there is furniture."""
    root = _repo(tmp_path)
    _budget(root, 0.05)
    monkeypatch.setattr(graphdb, "current_fingerprint", lambda *a, **k: time.sleep(0.4) or "x")
    assert cli._stop(_payload(root, "Stop")) is None


def test_a_disarmed_budget_restores_the_unbounded_behaviour(tmp_path, monkeypatch):
    """`deadline_seconds: 0` is the escape hatch — a store may prefer the host's kill to a degraded
    packet, and the tests need the un-armed path proven to still work."""
    root = _repo(tmp_path)
    _budget(root, 0)
    real = retrieval.session_context
    monkeypatch.setattr(retrieval, "session_context",
                        lambda *a, **k: (time.sleep(0.2), real(*a, **k))[1])
    out = cli._session_start(_payload(root))
    assert "exceeded" not in out["hookSpecificOutput"]["additionalContext"]


# --- the ledger ----------------------------------------------------------------------------------

def test_a_fast_run_writes_nothing_at_all(tmp_path):
    """Design law #4 applied to disk: the ordinary sub-second run costs one comparison and no I/O."""
    root = _repo(tmp_path)
    _budget(root, 10, slow_ms=2000)
    cli._session_start(_payload(root))
    assert not hookbudget.ledger_path(root).exists()
    assert hookbudget.read_ledger(root) == []


def test_a_slow_run_records_its_phase_breakdown(tmp_path, monkeypatch):
    """The instrument this whole finding needed: there was no timing anywhere in the tree, which is why
    'what was slow?' had no answer on either side of the report."""
    root = _repo(tmp_path)
    _budget(root, 10, slow_ms=100)
    real = retrieval.session_context
    monkeypatch.setattr(retrieval, "session_context",
                        lambda *a, **k: (time.sleep(0.25), real(*a, **k))[1])
    cli._session_start(_payload(root))

    rows = hookbudget.read_ledger(root)
    assert len(rows) == 1
    assert rows[0]["event"] == "SessionStart" and rows[0]["tripped"] is False
    phases = {p["name"]: p["ms"] for p in rows[0]["phases"]}
    assert "render" in phases and phases["render"] >= 200, phases
    assert "graph" in phases, "the expensive step must be nameable separately from the render"


def test_a_tripped_run_is_recorded_even_when_it_is_under_the_slow_threshold(tmp_path, monkeypatch):
    """A trip is always worth a row: it is the event the ledger exists for."""
    root = _repo(tmp_path)
    _budget(root, 0.05, slow_ms=10_000_000)
    monkeypatch.setattr(cli, "_ranked_with_telemetry", lambda *a, **k: time.sleep(0.4))
    cli._session_start(_payload(root))

    rows = hookbudget.read_ledger(root)
    assert len(rows) == 1 and rows[0]["tripped"] is True
    assert rows[0]["deadline_s"] == 0.05


def test_the_ledger_is_a_ring_buffer_and_machine_local(tmp_path, monkeypatch):
    """Bounded, and under `.local/` — a rendered timing is derived state and design law #6 keeps
    derived state out of the committed artifacts."""
    root = _repo(tmp_path)
    _budget(root, 10, slow_ms=100)
    real = retrieval.session_context
    monkeypatch.setattr(retrieval, "session_context",
                        lambda *a, **k: (time.sleep(0.15), real(*a, **k))[1])
    for _ in range(8):
        cli._session_start(_payload(root))

    assert len(hookbudget.read_ledger(root)) == 5  # timings_kept
    assert hookbudget.ledger_path(root).parent.name == ".local"
    assert ".local/" in (root / "yigraf" / ".gitignore").read_text()


# --- the report ----------------------------------------------------------------------------------

def test_doctor_is_quiet_and_says_what_quiet_means(tmp_path):
    """A quiet report means 'nothing has been slow', never 'the hooks are wired' — the exact confusion
    a silent cancellation already caused once."""
    root = _repo(tmp_path)
    res = runner.invoke(app, ["doctor", "--repo", str(root)])
    assert res.exit_code == 0
    assert "No slow hook runs recorded" in res.output
    assert "whether hooks are INSTALLED" in res.output


def test_doctor_reports_the_trip_and_the_phase_that_ran_long(tmp_path, monkeypatch):
    # A full second, where the other tests here use 0.05: this is the one test that asserts WHICH phase
    # ran long, so the budget has to be comfortably longer than an unrelated phase can take. At 0.05s a
    # loaded machine trips inside `graph` and the named phase is legitimately a different one.
    root = _repo(tmp_path)
    _budget(root, 1.0, slow_ms=100)
    monkeypatch.setattr(cli, "_ranked_with_telemetry", lambda *a, **k: time.sleep(2.0))
    cli._session_start(_payload(root))

    res = runner.invoke(app, ["doctor", "--repo", str(root)])
    assert res.exit_code == 0
    assert "hit the 1s budget" in res.output
    assert "⚠ BUDGET" in res.output and "SessionStart" in res.output
    assert "telemetry=" in res.output, "the slow phase must be named, not just the total"
    assert "design law #5" in res.output, "raising the deadline is not the default advice"

    as_json = runner.invoke(app, ["doctor", "--repo", str(root), "--json"])
    assert json.loads(as_json.output)[0]["tripped"] is True


def test_doctor_refuses_outside_a_workspace(tmp_path):
    """The one stop-condition: no store here. Consistent with every other verb."""
    res = runner.invoke(app, ["doctor", "--repo", str(tmp_path)])
    assert res.exit_code == 1 and "No yigraf workspace" in res.output
