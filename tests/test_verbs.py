"""The M2 authoring verbs end-to-end: intent/plan/link → projected graph (the M2 done-test)."""
from pathlib import Path

from typer.testing import CliRunner

from yigraf.cli import app
from yigraf.config import default_config
from yigraf.extract import build_graph
from yigraf.graph import read_graph

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"


def _repo(tmp_path: Path) -> Path:
    """An initialized repo with one linkable symbol, already built."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _run(args: list[str]):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result


def _graph(root: Path):
    return read_graph(root / "yigraf" / "graph.json")


def test_intent_verb_projects_an_enriched_node(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["intent", "session-expiry", "--repo", str(root),
          "-s", "The system SHALL expire a session after 30m idle.",
          "--scenario", "Given idle 30m, When a request arrives, Then respond 401.",
          "--design", "Optimistic-locked refresh.", "--status", "active"])
    node = _graph(root).nodes["int:session-expiry"]
    assert node["family"] == "intent" and node["status"] == "active"
    assert node["statement"].startswith("The system SHALL expire")
    assert node["scenarios"] == ["Given idle 30m, When a request arrives, Then respond 401."]
    assert node["design"] == "Optimistic-locked refresh."


def test_plan_verb_projects_plan_and_task_nodes(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["plan", "auth-hardening", "--repo", str(root), "-t", "Auth hardening",
          "--task", "implement idle expiry"])
    g = _graph(root)
    assert g.nodes["plan:auth-hardening"]["kind"] == "plan"
    assert g.nodes["task:auth-hardening/1"]["state"] == "todo"
    assert g.has_edge("plan:auth-hardening", "task:auth-hardening/1")


def test_link_implements_anchors_with_no_drift(tmp_path: Path):
    """The M2 done-test: link a task to a symbol → edge carries an anchor == the symbol's hash."""
    root = _repo(tmp_path)
    _run(["plan", "auth-hardening", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    _run(["link", "task:auth-hardening/1", SYM, "--repo", str(root)])

    g = _graph(root)
    edge = g.edges["task:auth-hardening/1", SYM]
    assert edge["relation"] == "implements" and edge["anchor_algo"] == "astnorm-v1"
    assert edge["anchor"] == g.nodes[SYM]["content_hash"]  # no drift


def test_link_tracks_an_intent(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["intent", "session-expiry", "--repo", str(root), "-s", "SHALL expire.",
          "--scenario", "Given a, When b, Then c."])
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    _run(["link", "task:auth/1", "int:session-expiry", "--repo", str(root)])
    assert _graph(root).edges["task:auth/1", "int:session-expiry"]["relation"] == "tracks"


def test_editing_a_linked_symbol_makes_the_anchor_drift(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    _run(["link", "task:auth/1", SYM, "--repo", str(root)])

    (root / "auth" / "session.py").write_text("def refresh(token):\n    return token + 1\n")
    graph, _ = build_graph(root, default_config())
    edge = graph.edges["task:auth/1", SYM]
    assert edge["anchor"] != graph.nodes[SYM]["content_hash"]  # body changed → drift


def test_deleting_a_linked_symbol_dangles_without_a_phantom_node(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    _run(["link", "task:auth/1", SYM, "--repo", str(root)])

    (root / "auth" / "session.py").write_text("def other():\n    return 0\n")
    graph, _ = build_graph(root, default_config())
    assert SYM not in graph  # no phantom node conjured for the vanished symbol
    assert not graph.has_edge("task:auth/1", SYM)
    assert [e["sym"] for e in graph.nodes["task:auth/1"]["dangling_implements"]] == [SYM]


def test_intent_verb_refuses_to_clobber(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["intent", "x", "--repo", str(root), "-s", "SHALL x.", "--scenario", "Given a, When b, Then c."])
    result = runner.invoke(app, ["intent", "x", "--repo", str(root), "-s", "again", "--scenario", "g"])
    assert result.exit_code == 1 and "already exists" in result.output


def test_link_rejects_an_unknown_symbol(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    result = runner.invoke(app, ["link", "task:auth/1", "sym:auth/session.py#ghost", "--repo", str(root)])
    assert result.exit_code == 1 and "not found" in result.output


def test_link_rejects_an_unknown_task(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    result = runner.invoke(app, ["link", "task:auth/9", SYM, "--repo", str(root)])
    assert result.exit_code == 1 and "not a task" in result.output
