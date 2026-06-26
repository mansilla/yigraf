"""Maturity, telemetry, and GC — v0 keeps graph.json recomputable (DESIGN R1/R2/R3).

Covers: maturity is **git-derived** (settled after K commits un-superseded, recomputed each build, never
a stored counter); telemetry (usage/last_seen) lives in the **gitignored sidecar**, never in
graph.json; recency + maturity lift the relevance prior; GC **archives** superseded churn (never
deletes, never gates on usage); and the union driver merges two graph.json without conflict.

The shared-committed-counter model (accumulated survival/usage in graph.json + a counter-reconciling
merge driver) is v1/Enterprise — explicitly out of scope here.
"""
import json
import subprocess
from pathlib import Path

import networkx as nx
from typer.testing import CliRunner

from yigraf import counters, retrieval
from yigraf.cli import app
from yigraf.config import default_config
from yigraf.graph import read_graph, to_node_link

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"
SRC = "auth/session.py"


def _repo(tmp_path: Path) -> Path:
    """An initialized, built repo with one symbol and one active intent (mirrors test_memory)."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["intent", "session-expiry", "--repo", str(tmp_path),
                               "-s", "Sessions SHALL expire after 30m idle.",
                               "--scenario", "Given idle 30m, When a request arrives, Then 401.",
                               "--status", "active"]).exit_code == 0
    return tmp_path


def _run(args: list[str]):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result


def _graph(root: Path):
    return read_graph(root / "yigraf" / "graph.json")


def _mem_graph(**overrides) -> nx.DiGraph:
    """A tiny in-memory graph: one active memory node, attrs overridable per test."""
    g = nx.DiGraph()
    g.add_node("mem:001", family="memory", kind="decision", maturity="working", **overrides)
    return g


def _git_init(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)


def _commit(root: Path, msg: str) -> None:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", msg, "--allow-empty"], check=True)


# --------------------------------------------------------------------------------------------------
# Maturity — git-derived, settles at K, self-healing (R2)
# --------------------------------------------------------------------------------------------------


def test_apply_maturity_settles_from_git_survival(monkeypatch):
    monkeypatch.setattr(counters, "survival_of", lambda root, path: 3)
    g = _mem_graph(source_file="memory/001-x.md")
    counters.apply_maturity(g, Path("."), {"maturity_k": 3})
    assert g.nodes["mem:001"]["survival"] == 3 and g.nodes["mem:001"]["maturity"] == "settled"


def test_apply_maturity_stays_working_below_k(monkeypatch):
    monkeypatch.setattr(counters, "survival_of", lambda root, path: 2)
    g = _mem_graph(source_file="memory/001-x.md")
    counters.apply_maturity(g, Path("."), {"maturity_k": 3})
    assert g.nodes["mem:001"]["maturity"] == "working"


def test_superseded_node_never_settles(monkeypatch):
    monkeypatch.setattr(counters, "survival_of", lambda root, path: 99)
    g = _mem_graph(source_file="memory/001-x.md", superseded_in=1)
    counters.apply_maturity(g, Path("."), {"maturity_k": 3})
    assert g.nodes["mem:001"]["maturity"] == "working"


def test_decision_settles_after_k_commits(tmp_path: Path):
    """The git-derived done-test: a decision un-superseded across K commits is settled — recomputably."""
    _git_init(tmp_path)
    root = _repo(tmp_path)
    _run(["remember", "refresh uses optimistic locking", "--concerns", SYM, "--repo", str(root)])
    _commit(root, "capture the decision")  # introduces the memory artifact (survival starts at 0)

    _run(["build", str(root)])
    assert _graph(root).nodes["mem:001"]["maturity"] == "working"

    for i in range(3):  # K=3 commits move the branch on past the decision
        _commit(root, f"later work {i}")
    _run(["build", str(root)])
    node = _graph(root).nodes["mem:001"]
    assert node["survival"] == 3 and node["maturity"] == "settled"


# --------------------------------------------------------------------------------------------------
# Relevance terms — recency + maturity lift the prior
# --------------------------------------------------------------------------------------------------


def test_recency_decays_from_one():
    assert counters.recency(1000, now=1000, half_life_days=14) == 1.0
    assert counters.recency(None, now=1000, half_life_days=14) == 0.0
    week = counters.recency(1000, now=1000 + 7 * 86400, half_life_days=14)
    assert 0.6 < week < 0.8  # half a half-life → ~0.71


def test_settled_memory_outranks_a_working_twin():
    g = nx.DiGraph()
    for nid, mat in (("mem:settled", "settled"), ("mem:working", "working")):
        g.add_node(nid, family="memory", kind="decision", maturity=mat)
    cfg = default_config()
    assert retrieval._relevance(g, "mem:settled", cfg, now=1000.0) > \
           retrieval._relevance(g, "mem:working", cfg, now=1000.0)


# --------------------------------------------------------------------------------------------------
# Telemetry — gitignored sidecar, never in graph.json (R1)
# --------------------------------------------------------------------------------------------------


def test_record_injection_writes_sidecar_scoped_to_memory_and_intent(tmp_path: Path):
    g = nx.DiGraph()
    g.add_node("mem:001", family="memory")
    g.add_node("int:x", family="intent")
    g.add_node("sym:a#f", family="structure")
    bumped = counters.record_injection(tmp_path, g, ["mem:001", "int:x", "sym:a#f"], now=4242)

    assert set(bumped) == {"mem:001", "int:x"}  # structure is ranked by refs_in, never recorded
    tele = counters.load_telemetry(tmp_path)
    assert tele["mem:001"] == {"usage": 1, "last_seen": 4242} and "sym:a#f" not in tele
    assert "usage" not in g.nodes["mem:001"]  # the graph itself isn't mutated — only the sidecar


def test_apply_telemetry_overlays_for_ranking():
    g = _mem_graph()
    counters.apply_telemetry(g, {"mem:001": {"usage": 3, "last_seen": 111}})
    assert g.nodes["mem:001"]["last_seen"] == 111 and g.nodes["mem:001"]["usage"] == 3


def test_context_records_telemetry_without_dirtying_graph_json(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["remember", "refresh uses optimistic locking", "--why", "the hot path",
          "--concerns", SYM, "--repo", str(root)])

    _run(["context", "optimistic locking refresh", "--repo", str(root)])
    tele = counters.load_telemetry(root)
    assert tele.get("mem:001", {}).get("usage", 0) >= 1  # surfacing recorded in the sidecar

    # graph.json holds no runtime telemetry — it stays fully recomputable, across rebuilds.
    _run(["build", str(root)])
    for _, attrs in _graph(root).nodes(data=True):
        assert "usage" not in attrs and "last_seen" not in attrs


# --------------------------------------------------------------------------------------------------
# GC — archive churn, never delete, never gate on usage (R3)
# --------------------------------------------------------------------------------------------------


def test_classify_gc_archives_only_superseded_churn():
    g = nx.DiGraph()
    g.add_node("mem:churn", family="memory", superseded_in=1)             # superseded, unreferenced
    g.add_node("mem:ref", family="memory", superseded_in=1)               # superseded but referenced
    g.add_node("mem:active", family="memory")                             # not superseded
    g.add_node("task:p/1", family="plan")
    g.add_edge("task:p/1", "mem:ref", relation="references")
    assert counters.classify_gc(g) == {"mem:churn": "archive"}            # only churn, only archive


def test_gc_archives_superseded_churn_without_deleting(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["remember", "refresh uses optimistic locking", "--concerns", SYM, "--repo", str(root)])
    _run(["supersede", "mem:001", "refresh uses pessimistic locking", "--concerns", SYM, "--repo", str(root)])

    dry = _run(["gc", str(root)])
    assert "Dry run" in dry.output and "mem:001 → archive" in dry.output

    _run(["gc", str(root), "--apply"])
    g = _graph(root)
    assert "mem:001" not in g                                             # dropped from the active graph
    archived = list((root / "yigraf" / "memory" / "archive").glob("*.md"))
    assert len(archived) == 1 and "optimistic" in archived[0].name        # moved, not deleted


# --------------------------------------------------------------------------------------------------
# Union-merge driver — unions nodes+edges (no counter reconciliation in v0)
# --------------------------------------------------------------------------------------------------


def _nl(node_attrs: dict, edges: list[tuple] = ()) -> dict:
    g = nx.DiGraph()
    for nid, attrs in node_attrs.items():
        g.add_node(nid, **attrs)
    for s, t in edges:
        g.add_edge(s, t, relation="serves")
    return to_node_link(g)


def test_merge_unions_nodes_and_edges():
    ours = _nl({"mem:001": {"family": "memory"}, "int:x": {"family": "intent"}},
               edges=[("mem:001", "int:x")])
    theirs = _nl({"mem:002": {"family": "memory"}, "int:x": {"family": "intent"}})
    merged = counters.merge_node_link(ours, theirs)
    ids = {n["id"] for n in merged["nodes"]}
    assert {"mem:001", "mem:002", "int:x"} <= ids                         # union — never drops a node


def test_graph_merge_cli_unions_two_branches(tmp_path: Path):
    ours = _nl({"mem:001": {"family": "memory"}})
    theirs = _nl({"mem:002": {"family": "memory"}})
    paths = {}
    for name, data in (("base", {}), ("ours", ours), ("theirs", theirs)):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(data) if data else "{}")
        paths[name] = p
    _run(["graph-merge", str(paths["base"]), str(paths["ours"]), str(paths["theirs"])])
    merged = read_graph(paths["ours"])  # driver writes the union back to %A (ours)
    assert "mem:001" in merged and "mem:002" in merged


def test_install_hooks_registers_the_merge_driver(tmp_path: Path):
    _git_init(tmp_path)
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    result = _run(["install-hooks", str(tmp_path)])
    assert "union-merge driver" in result.output
    got = subprocess.run(["git", "-C", str(tmp_path), "config", "merge.yigraf-graph.driver"],
                         capture_output=True, text=True)
    assert "graph-merge" in got.stdout
