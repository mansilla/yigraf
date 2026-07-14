from pathlib import Path

from yigraf.graph import SCHEMA_VERSION, empty_graph, read_graph, to_node_link, write_graph


def test_empty_graph_has_schema_version():
    g = empty_graph()
    assert g.number_of_nodes() == 0
    assert g.number_of_edges() == 0
    assert g.graph["schema_version"] == SCHEMA_VERSION


def test_write_then_read_roundtrips(tmp_path: Path):
    p = tmp_path / "graph.json"
    write_graph(empty_graph(), p)
    g = read_graph(p)
    assert g.number_of_nodes() == 0
    assert g.number_of_edges() == 0
    assert g.graph["schema_version"] == SCHEMA_VERSION


def test_write_is_deterministic(tmp_path: Path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    write_graph(empty_graph(), a)
    write_graph(empty_graph(), b)
    assert a.read_text() == b.read_text()


def test_serialization_strips_volatile_but_leaves_the_in_memory_graph(tmp_path: Path):
    """R1/mem:034 #10: git-derived ``survival`` and the sidecar overlay never reach graph.json (they
    churn or are machine-local), but the in-memory graph keeps them so read paths still rank/mature."""
    g = empty_graph()
    g.add_node("mem:001", family="memory", kind="decision",
               survival=42, usage=7, last_seen=123, upholds=1.5, maturity="working")
    node = next(n for n in to_node_link(g)["nodes"] if n["id"] == "mem:001")
    assert not ({"survival", "usage", "last_seen", "upholds"} & node.keys())  # stripped from the projection
    assert node["maturity"] == "working"          # HEAD-stable, recomputable state stays
    assert g.nodes["mem:001"]["survival"] == 42    # the in-memory graph is untouched (read paths use it)

    p = tmp_path / "graph.json"
    write_graph(g, p)
    assert '"survival"' not in p.read_text()       # the churn source is gone from the committed file
