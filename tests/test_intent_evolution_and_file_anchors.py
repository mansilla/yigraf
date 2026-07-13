"""Cluster B (intent evolution) + Cluster A (#12 file-level anchoring) from the 2026-07 friend review.

int→int supersedes was the biggest structural gap (a reversal couldn't be an edge); file: anchoring
lets infra/glue files with no code symbol carry a governed decision, with region-scoped drift.
"""
import re
from pathlib import Path

from typer.testing import CliRunner

from yigraf.cli import app
from yigraf.config import default_config
from yigraf.drift import compute_drift
from yigraf.extract import build_graph
from yigraf.graph import read_graph

runner = CliRunner()


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    (tmp_path / "code.py").write_text("def f():\n    return 1\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _run(args: list[str]):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result


def _graph(root: Path):
    return read_graph(root / "yigraf" / "graph.json")


def _drift(root: Path):
    graph, _ = build_graph(root, default_config())
    return compute_drift(graph)


# ── Cluster B: intent evolution ──────────────────────────────────────────────────────────────────


def test_supersede_intent_writes_a_traversable_edge_and_archives_the_old(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["intent", "auth-aud", "--repo", str(root), "-s", "SHALL bind the JWT on the aud claim"])
    _run(["supersede-intent", "auth-aud", "auth-clientid", "--repo", str(root),
          "-s", "SHALL bind the JWT on the client_id claim",
          "--why", "a live spike showed aud is absent under the target runtime"])

    g = _graph(root)
    # The edge the old `superseded_by:` frontmatter never produced (friend-review #1).
    assert g.edges["int:auth-clientid", "int:auth-aud"]["relation"] == "supersedes"
    assert g.nodes["int:auth-aud"]["status"] == "archived"
    assert g.nodes["int:auth-clientid"]["status"] == "active"
    # --why is captured as a memory serving the new intent (the perishable rationale).
    mem = next(n for n, a in g.nodes(data=True)
               if a.get("family") == "memory" and "supersedes int:auth-aud" in a.get("statement", ""))
    assert g.edges[mem, "int:auth-clientid"]["relation"] == "serves"


def test_intent_status_updates_in_place_but_anti_clobber_holds(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["intent", "retention", "--repo", str(root), "-s", "SHALL retain logs 30d"])

    # No --status on an existing intent → refuse (anti-clobber), exit 0 with guidance (never clobber).
    clobber = runner.invoke(app, ["intent", "retention", "--repo", str(root), "-s", "different"])
    assert clobber.exit_code == 0 and "already exists" in clobber.output
    assert _graph(root).nodes["int:retention"]["statement"] == "SHALL retain logs 30d"  # unchanged

    _run(["intent", "retention", "--repo", str(root), "--status", "satisfied"])
    assert _graph(root).nodes["int:retention"]["status"] == "satisfied"


# ── Cluster A: file-level anchoring (#12) ────────────────────────────────────────────────────────


def test_file_anchor_drifts_only_when_that_file_changes(tmp_path: Path):
    root = _repo(tmp_path)
    (root / "Dockerfile").write_text('FROM python:3.11\nENTRYPOINT ["python","-m","app"]\n')
    out = _run(["remember", "entrypoint must be exec-form", "--repo", str(root),
                "--why", "shell-form breaks signal handling", "--concerns", "file:Dockerfile"]).output
    mem = re.search(r"Captured (mem:[0-9a-f]{16})", out).group(1)

    # An unrelated code edit does not drift the Dockerfile decision.
    (root / "code.py").write_text("def f():\n    return 2\n")
    assert _drift(root) == []

    # Editing the Dockerfile itself does.
    (root / "Dockerfile").write_text('FROM python:3.12\nENTRYPOINT ["python","-m","app"]\n')
    drift = _drift(root)
    assert [(d.kind, d.locator) for d in drift] == [("soft", "file:Dockerfile")]

    # reaffirm re-stamps the file anchor and clears the drift.
    _run(["reaffirm", mem, "--repo", str(root)])
    assert _drift(root) == []


def test_line_range_anchor_is_region_scoped(tmp_path: Path):
    root = _repo(tmp_path)
    (root / "cfg.txt").write_text("l1 stable\nl2 governed\nl3 governed\nl4 volatile\n")
    _run(["remember", "l2-l3 encode policy", "--repo", str(root),
          "--why", "region", "--concerns", "file:cfg.txt:L2-L3"])

    # Edit OUTSIDE the range → no drift.
    (root / "cfg.txt").write_text("l1 stable\nl2 governed\nl3 governed\nl4 CHANGED\n")
    assert _drift(root) == []

    # Edit INSIDE the range → soft drift.
    (root / "cfg.txt").write_text("l1 stable\nl2 CHANGED\nl3 governed\nl4 CHANGED\n")
    assert [(d.kind, d.locator) for d in _drift(root)] == [("soft", "file:cfg.txt:L2-L3")]


def test_locus_scoped_reaffirm_clears_every_memory_on_that_locus(tmp_path: Path):
    root = _repo(tmp_path)
    (root / "Dockerfile").write_text("FROM python:3.11\n")
    _run(["remember", "base image is pinned to 3.11", "--repo", str(root),
          "--why", "repro", "--concerns", "file:Dockerfile"])
    _run(["remember", "entrypoint is exec-form", "--repo", str(root),
          "--why", "signals", "--concerns", "file:Dockerfile"])

    (root / "Dockerfile").write_text("FROM python:3.12\n")  # both decisions now drift
    assert len(_drift(root)) == 2

    # One locus-scoped call reaffirms every memory concerning that file (you verified the file once).
    out = _run(["reaffirm", "file:Dockerfile", "--repo", str(root)]).output
    assert "2 memory(ies) concerning file:Dockerfile" in out
    assert _drift(root) == []


def test_reaffirm_locus_with_no_concerning_memory_is_guided(tmp_path: Path):
    root = _repo(tmp_path)
    out = _run(["reaffirm", "sym:code.py#f", "--repo", str(root)]).output
    assert "No memory concerns sym:code.py#f" in out  # guidance, exit 0


def test_whole_file_anchor_on_indexed_code_is_guided_away(tmp_path: Path):
    """A whole-file file: anchor on a code file would collide with the extractor node → silent no-drift."""
    root = _repo(tmp_path)
    result = _run(["remember", "x", "--repo", str(root), "--why", "y", "--concerns", "file:code.py"])
    assert "indexed as code" in result.output
    # No memory was captured (guidance-and-exit, not a broken anchor).
    assert not any(a.get("family") == "memory" for _, a in _graph(root).nodes(data=True))
