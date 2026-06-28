"""The memory node family + capture verbs — the M7 done-test (docs/memory-model.md, capture-flow.md).

Covers: ``remember``/``note-constraint``/``supersede`` project memory nodes with their
``serves``/``concerns``/``supersedes`` edges; a ``concerns`` edge is anchored and drift-bearing (the
second drift relation after ``implements``); a rename auto-re-anchors a ``concerns`` edge for free;
supersession materializes the ``superseded_in`` counter and the active decision out-ranks the stale
one; and the decision surfaces in ``context`` / the action-driven hook.
"""
from pathlib import Path

from typer.testing import CliRunner

from yigraf import memory
from yigraf.cli import app
from yigraf.config import default_config
from yigraf.drift import compute_drift
from yigraf.extract import build_graph
from yigraf.graph import read_graph
from yigraf import retrieval

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"
SRC = "auth/session.py"


def _repo(tmp_path: Path) -> Path:
    """An initialized, built repo with one symbol and one active intent to serve."""
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


def _remember(root: Path, statement: str, **opts) -> None:
    args = ["remember", statement, "--repo", str(root)]
    for key in ("type", "why", "rejected"):
        if key in opts:
            args += [f"--{key}", opts[key]]
    for target in opts.get("serves", []):
        args += ["--serves", target]
    for sym in opts.get("concerns", []):
        args += ["--concerns", sym]
    _run(args)


# --------------------------------------------------------------------------------------------------
# remember → node + edges + anchor
# --------------------------------------------------------------------------------------------------


def test_remember_projects_a_memory_node_with_its_edges(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "session refresh uses optimistic locking", type="decision",
              why="refresh path is hot; a retry is cheaper than serializing",
              serves=["int:session-expiry"], concerns=[SYM], rejected="pessimistic row lock")
    g = _graph(root)
    node = g.nodes["mem:001"]
    assert node["family"] == "memory" and node["kind"] == "decision" and node["status"] == "active"
    assert node["statement"] == "session refresh uses optimistic locking"
    assert node["why"].startswith("refresh path is hot")
    assert node["alternatives"] == "pessimistic row lock"
    assert g.edges["mem:001", "int:session-expiry"]["relation"] == "serves"
    assert g.edges["mem:001", SYM]["relation"] == "concerns"


def test_concerns_edge_is_anchored_to_the_symbol_hash(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    g = _graph(root)
    edge = g.edges["mem:001", SYM]
    assert edge["anchor_algo"] == "astnorm-v1"
    assert edge["anchor"] == g.nodes[SYM]["content_hash"]  # freshly captured → no drift


def test_remember_rejects_an_unknown_type(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["remember", "x", "--type", "bogus", "--repo", str(root)])
    # Recoverable conditions return exit 0 + guidance, never a hard error (errors teach abandonment).
    assert result.exit_code == 0 and "--type must be one of" in result.output


def test_remember_rejects_an_unknown_concerns_symbol(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["remember", "x", "--concerns", "sym:auth/session.py#ghost",
                                 "--repo", str(root)])
    assert result.exit_code == 0 and "Couldn't find" in result.output


def test_note_constraint_is_a_promotable_constraint(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["note-constraint", "refresh() must not block over 50ms", "--concerns", SYM,
          "--repo", str(root)])
    node = _graph(root).nodes["mem:001"]
    assert node["kind"] == "constraint" and node["promotable"] is True


# --------------------------------------------------------------------------------------------------
# concerns drift (the second drift-bearing relation)
# --------------------------------------------------------------------------------------------------


def test_editing_concerned_code_surfaces_concerns_drift(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")  # body changed
    graph, _ = build_graph(root, default_config())
    items = [i for i in compute_drift(graph) if i.relation == "concerns"]
    assert [i.kind for i in items] == ["soft"]
    assert items[0].task_id == "mem:001" and items[0].locator == SYM


def test_concerns_edge_auto_reanchors_on_rename(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    (root / SRC).write_text("def renew(token):\n    return token\n")  # pure rename, identical body
    graph, _ = build_graph(root, default_config())
    new = "sym:auth/session.py#renew"
    assert graph.has_edge("mem:001", new)
    assert graph["mem:001"][new]["relation"] == "concerns"
    assert graph["mem:001"][new]["renamed_from"] == SYM
    assert [i.kind for i in compute_drift(graph) if i.relation == "concerns"] == ["renamed"]


def test_deleting_concerned_code_is_hard_concerns_drift(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "refresh keeps the token immutable", concerns=[SYM])
    (root / SRC).write_text("def unrelated():\n    return 0\n")
    graph, _ = build_graph(root, default_config())
    items = [i for i in compute_drift(graph) if i.relation == "concerns"]
    assert [i.kind for i in items] == ["hard"] and items[0].locator == SYM


# --------------------------------------------------------------------------------------------------
# supersede → counters + ranking
# --------------------------------------------------------------------------------------------------


def test_supersede_links_and_marks_the_predecessor_stale(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "session refresh uses optimistic locking", concerns=[SYM])
    _run(["supersede", "mem:001", "session refresh uses pessimistic locking",
          "--why", "contention is low; a row lock is simpler", "--concerns", SYM, "--repo", str(root)])
    g = _graph(root)
    assert g.edges["mem:002", "mem:001"]["relation"] == "supersedes"
    assert g.nodes["mem:001"]["superseded_in"] == 1
    assert g.nodes["mem:002"]["supersedes_out"] == 1
    assert g.nodes["mem:002"]["superseded_in"] == 0


def test_active_decision_outranks_its_superseded_predecessor(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "session refresh uses optimistic locking", concerns=[SYM])
    _run(["supersede", "mem:001", "session refresh uses pessimistic locking",
          "--concerns", SYM, "--repo", str(root)])
    graph, _ = build_graph(root, default_config())
    result = retrieval.context(graph, "session refresh locking", default_config(), family="memory")
    # Both decisions render; the active one (mem:002) appears before the superseded mem:001.
    assert result.text.index("mem:002") < result.text.index("mem:001")
    assert "·superseded" in result.text


def test_supersede_rejects_an_unknown_old_id(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["supersede", "mem:999", "new claim", "--repo", str(root)])
    assert result.exit_code == 0 and "No memory node" in result.output


# --------------------------------------------------------------------------------------------------
# render + artifact round-trip
# --------------------------------------------------------------------------------------------------


def test_context_renders_the_decision_with_its_why(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "session refresh uses optimistic locking", type="decision",
              why="refresh path is hot", serves=["int:session-expiry"], concerns=[SYM])
    graph, _ = build_graph(root, default_config())
    result = retrieval.context(graph, "optimistic locking refresh", default_config())
    assert "Decisions (why):" in result.text
    assert "mem:001 [decision]" in result.text
    assert "why: refresh path is hot" in result.text


def test_memory_artifact_round_trips(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "a decision", why="because", concerns=[SYM], rejected="the alternative")
    path = memory.find_memory(root, "mem:001")
    assert path is not None
    mem = memory.read_memory(path)
    assert mem.id == "mem:001" and mem.statement == "a decision" and mem.why == "because"
    assert mem.alternatives == "the alternative"
    assert mem.concerns[0].sym == SYM and mem.concerns[0].anchor is not None


def test_next_seq_increments_across_captures(tmp_path: Path):
    root = _repo(tmp_path)
    assert memory.next_seq(root) == 1
    _remember(root, "first")
    assert memory.next_seq(root) == 2
    _remember(root, "second")
    assert memory.next_seq(root) == 3
