"""Host-agnostic status surface (int:status-surface) — counts, drift, freshness, context, render."""
import json
from pathlib import Path

from typer.testing import CliRunner

from yigraf import status
from yigraf.cli import app
from yigraf.config import default_config
from yigraf.extract import build_graph

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"
SRC = "auth/session.py"


def _repo(tmp_path: Path) -> Path:
    """An initialized, built repo with one task linked (implements) to ``refresh``, anchored."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["plan", "auth", "--repo", str(tmp_path), "-t", "Auth",
                               "--task", "do it"]).exit_code == 0
    assert runner.invoke(app, ["link", "task:auth/1", SYM, "--repo", str(tmp_path)]).exit_code == 0
    # graph.json is written by build; link rewrites the plan but rebuilds graph.json too.
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _summary(root: Path, **kw) -> status.StatusSummary:
    graph, _ = build_graph(root, default_config())
    return status.compute_status(graph, root, default_config(), **kw)


def test_counts_reflect_the_graph(tmp_path: Path):
    s = _summary(_repo(tmp_path))
    assert s.symbols == 1  # refresh; the file/module containers are not symbols
    assert s.plans == 1 and s.tasks_total == 1 and s.tasks_open == 1  # link doesn't complete the task
    assert s.drifting == 0


def test_open_tasks_counted(tmp_path: Path):
    root = _repo(tmp_path)
    # the seeded task is still 'todo' (link doesn't complete it), so it counts as open
    s = _summary(root)
    assert s.tasks_open == s.tasks_total == 1


def test_all_done_renders_a_check_not_a_bare_count(tmp_path: Path):
    """Total>0 with zero open must read as 'all done' (✓), distinct from an empty '0 task'."""
    root = _repo(tmp_path)
    plan = root / "yigraf" / "plans" / "active" / "auth.md"
    plan.write_text(plan.read_text().replace("- [ ] {#1}", "- [x] {#1}"))
    s = _summary(root)
    assert s.tasks_total == 1 and s.tasks_open == 0
    assert "1 task ✓" in s.render_line()  # the "you're clear" signal, not a bare "1 task"
    assert "/0 open" not in s.render_line()
    assert " ✓" in s.render_line(color=True, icon=status.SPIN[0])


def test_empty_and_all_done_render_differently(tmp_path: Path):
    """The whole point: 'no plans yet' (0 task) and 'all done' (N task ✓) must not look identical."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    empty = _summary(tmp_path)
    assert empty.tasks_total == 0 and "0 task" in empty.render_line() and "✓" not in empty.render_line()


def test_freshness_fresh_then_stale_then_absent(tmp_path: Path):
    root = _repo(tmp_path)
    assert _summary(root).freshness == "fresh"
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")  # source moved past graph.json
    assert _summary(root).freshness == "stale"
    (root / "yigraf" / "graph.json").unlink()
    assert _summary(root).freshness == "absent"


def test_body_edit_surfaces_as_drift_in_the_summary(tmp_path: Path):
    root = _repo(tmp_path)
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")
    assert _summary(root).drifting == 1


def test_update_marker_shows_when_the_cache_has_a_newer_version(tmp_path: Path):
    root = _repo(tmp_path)
    # Simulate the daily check having found a newer release (a pure sidecar read — no network).
    cache = root / "yigraf" / ".local" / "update-check.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"checked_at": 0, "latest": "99.0.0"}))
    line = _summary(root).render_line()
    assert "⬆ 99.0.0" in line  # the human-facing nudge; silent otherwise


def test_no_update_marker_without_a_newer_version(tmp_path: Path):
    assert "⬆" not in _summary(_repo(tmp_path)).render_line()  # silence is a feature


def test_context_is_injected_not_read(tmp_path: Path):
    """The one non-agnostic datum is host-supplied: absent ⇒ no ctx segment; present ⇒ a percentage."""
    root = _repo(tmp_path)
    assert _summary(root).ctx_used is None
    assert "ctx" not in _summary(root).render_line()
    s = _summary(root, ctx_used=40_000, ctx_limit=200_000)
    assert s.ctx_used == 40_000
    assert "ctx 20%" in s.render_line()


def test_render_line_is_a_single_compact_line(tmp_path: Path):
    line = _summary(_repo(tmp_path)).render_line()
    assert "\n" not in line
    assert line.startswith("yigraf ") and "fresh" in line and "no drift" in line


def test_plain_render_has_no_ansi_but_color_does(tmp_path: Path):
    s = _summary(_repo(tmp_path), ctx_used=40_000, ctx_limit=200_000)
    assert "\x1b[" not in s.render_line()  # plain stays escape-free (pipes/tests/agent injection)
    pretty = s.render_line(color=True, icon=status.SPIN[0])
    assert "\x1b[" in pretty and status.SPIN[0] in pretty
    assert "●" in pretty  # the "fresh" shape glyph
    assert "▰" in pretty and "20%" in pretty  # the context gauge


def test_status_cli_line_and_json(tmp_path: Path):
    root = _repo(tmp_path)
    line = runner.invoke(app, ["status", "--repo", str(root)])  # CliRunner is non-TTY ⇒ plain
    assert line.exit_code == 0 and line.stdout.startswith("yigraf ")

    forced = runner.invoke(app, ["status", "--repo", str(root), "--color"])
    assert forced.exit_code == 0 and "\x1b[" in forced.stdout

    out = runner.invoke(app, ["status", "--repo", str(root), "--json"])
    assert out.exit_code == 0
    data = json.loads(out.stdout)
    assert data["symbols"] == 1 and data["freshness"] == "fresh" and data["ctx_used"] is None
