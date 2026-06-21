from pathlib import Path

from yigraf.graph import SCHEMA_VERSION, empty_graph, read_graph, write_graph


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
