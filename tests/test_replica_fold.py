"""Case A: a teammate's assertion, arriving only over the sync log, participates in local drift.

``build_graph`` folds the synced replica onto the same structure base the authored artifacts land on,
so a belief that exists in no markdown file in this repo still anchors to *this* repo's code — and
starts drifting when you edit it. Structure never crosses the wire; only assertions do.
"""
from pathlib import Path

import pytest
from typer.testing import CliRunner

from yigraf.cli import app
from yigraf.config import load_config
from yigraf.drift import compute_drift
from yigraf.extract import build_graph, symbol_content_hash
from yigraf.log import Assertion
from yigraf.onlinelog import OnlineLog, SqliteAssertionStore

runner = CliRunner()

PROJECT = "teamproj"
SYM = "sym:app.py#greet"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    (tmp_path / "app.py").write_text("def greet():\n    return 'hi'\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _config(repo: Path, online: bool = True) -> dict:
    config = load_config(repo / "yigraf" / "config.yaml")
    if online:
        config["online"]["project"] = PROJECT
    return config


def _teammate_belief(repo: Path, config: dict, anchor: str | None) -> None:
    """Append a memory to the replica as if ``yigraf sync`` had pulled it from a teammate."""
    store = SqliteAssertionStore(repo / "yigraf" / "cache" / "replica.db")
    log = OnlineLog(store, PROJECT, signer_key=None, require_signed_provenance=False)
    log.append(Assertion(
        id="mem:teammate1", kind="memory",
        body={"family": "memory",
              "attrs": {"kind": "constraint", "status": "active",
                        "statement": "greet() must stay side-effect free",
                        "source_file": "memory/theirs.md"},
              "edges": [{"relation": "concerns", "target": SYM,
                         "attrs": {"anchor": anchor, "anchor_algo": "astnorm-v1"}}]},
        provenance=[{"actor": "teammate@example.com", "source": "cli"}]))


def test_offline_workspace_is_unchanged(repo):
    """The default: no project configured ⇒ nothing folded, graph is purely local."""
    config = _config(repo, online=False)
    _teammate_belief(repo, config, symbol_content_hash(repo, SYM, config))
    graph, stats = build_graph(repo, config)
    assert stats.synced == 0
    assert "mem:teammate1" not in graph


def test_absent_replica_degrades_to_local(repo):
    config = _config(repo)
    graph, stats = build_graph(repo, config)  # configured, but nothing has ever synced
    assert stats.synced == 0
    assert graph.number_of_nodes() > 0


def test_unreadable_replica_degrades_to_local_rather_than_breaking_the_build(repo):
    """Fail-open (design law #5): a corrupt replica must never take the build down."""
    config = _config(repo)
    replica = repo / "yigraf" / "cache" / "replica.db"
    replica.parent.mkdir(parents=True, exist_ok=True)
    replica.write_bytes(b"this is not a sqlite database")
    graph, stats = build_graph(repo, config)
    assert stats.synced == 0
    assert graph.number_of_nodes() > 0


def test_teammate_belief_enters_my_graph_and_drifts_against_my_edit(repo):
    config = _config(repo)
    _teammate_belief(repo, config, symbol_content_hash(repo, SYM, config))

    graph, stats = build_graph(repo, config)
    assert stats.synced == 1
    assert "mem:teammate1" in graph, "a belief with no local artifact must still fold in"
    assert compute_drift(graph) == [], "unedited code must not drift"

    # Now I edit the code THEIR belief governs.
    (repo / "app.py").write_text("def greet():\n    print('side effect')\n    return 'hi'\n")
    graph2, _ = build_graph(repo, config)
    drift = compute_drift(graph2)
    assert [(d.kind, d.task_id, d.locator, d.relation) for d in drift] == [
        ("soft", "mem:teammate1", SYM, "concerns")]


def test_rename_re_anchors_a_teammate_belief_rather_than_drifting(repo):
    """The rename machinery is family-agnostic, so it covers synced beliefs for free."""
    config = _config(repo)
    _teammate_belief(repo, config, symbol_content_hash(repo, SYM, config))
    build_graph(repo, config)

    (repo / "app.py").write_text("def welcome():\n    return 'hi'\n")
    graph, _ = build_graph(repo, config)
    drift = compute_drift(graph)
    assert [(d.kind, d.locator, d.new_locator) for d in drift] == [
        ("renamed", SYM, "sym:app.py#welcome")]


def test_a_belief_authored_here_and_synced_collapses_to_one_node(repo):
    """Two folds over one base is safe because assertions are content-addressed (mem:060)."""
    config = _config(repo)
    out = runner.invoke(app, ["remember", "greet returns a greeting", "--why", "clarity",
                              "--concerns", SYM, "--repo", str(repo)])
    assert out.exit_code == 0, out.output

    from yigraf import filelog, memory
    mine = memory.iter_memories(repo)[0]
    assertion = filelog._memory_assertion(mine)

    store = SqliteAssertionStore(repo / "yigraf" / "cache" / "replica.db")
    OnlineLog(store, PROJECT, signer_key=None, require_signed_provenance=False).append(assertion)

    graph, stats = build_graph(repo, config)
    assert stats.synced == 1
    assert mine.id in graph
    assert len([n for n in graph.nodes if n == mine.id]) == 1
    # The round trip must not have manufactured a second, competing copy of the same belief.
    memories = [n for n, a in graph.nodes(data=True) if a.get("family") == "memory"]
    assert memories == [mine.id]
