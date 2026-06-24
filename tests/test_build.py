"""Whole-repo build: cache hits, byte-identical rebuilds, intra-repo import edges (M1 done-test)."""
from pathlib import Path

from typer.testing import CliRunner

from yigraf.cli import app
from yigraf.config import default_config
from yigraf.extract import build_graph
from yigraf.graph import write_graph
from yigraf.scaffold import init_workspace

runner = CliRunner()


def _make_repo(root: Path) -> None:
    """A tiny src-layout package: a.py imports b.py; b.py stands alone."""
    init_workspace(root)
    pkg = root / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "b.py").write_text("def g():\n    return 1\n")
    (pkg / "a.py").write_text("from pkg.b import g\n\n\ndef f():\n    return g()\n")


def test_build_projects_the_repo_structure(tmp_path: Path):
    _make_repo(tmp_path)
    graph, stats = build_graph(tmp_path, default_config())

    assert stats.files == 3 and stats.extracted == 3 and stats.cached == 0
    assert "file:src/pkg/a.py" in graph
    assert "sym:src/pkg/a.py#f" in graph
    assert "sym:src/pkg/b.py#g" in graph


def test_intra_repo_import_resolves_to_an_edge(tmp_path: Path):
    _make_repo(tmp_path)
    graph, _ = build_graph(tmp_path, default_config())
    # `from pkg.b import g` in a.py resolves across the src-layout to b.py's file node
    assert graph.has_edge("file:src/pkg/a.py", "file:src/pkg/b.py")
    assert graph["file:src/pkg/a.py"]["file:src/pkg/b.py"]["relation"] == "imports"


def test_external_import_makes_no_edge_or_phantom_node(tmp_path: Path):
    init_workspace(tmp_path)
    (tmp_path / "x.py").write_text("import os\n")
    graph, _ = build_graph(tmp_path, default_config())
    assert "file:os" not in graph and "module:os" not in graph
    assert graph.out_degree("file:x.py") == 1  # only the contains→module edge


def test_second_build_hits_the_cache(tmp_path: Path):
    _make_repo(tmp_path)
    build_graph(tmp_path, default_config())
    _, stats = build_graph(tmp_path, default_config())
    assert stats.files == 3 and stats.extracted == 0 and stats.cached == 3


def test_unchanged_rebuild_is_byte_identical(tmp_path: Path):
    _make_repo(tmp_path)
    first, _ = build_graph(tmp_path, default_config())
    out1 = tmp_path / "g1.json"
    write_graph(first, out1)

    second, _ = build_graph(tmp_path, default_config())  # served from cache
    out2 = tmp_path / "g2.json"
    write_graph(second, out2)

    assert out1.read_bytes() == out2.read_bytes()


def test_comment_only_edit_keeps_every_content_hash(tmp_path: Path):
    _make_repo(tmp_path)
    before, _ = build_graph(tmp_path, default_config())
    before_hashes = {n: d["content_hash"] for n, d in before.nodes(data=True) if "content_hash" in d}

    # A comment-only edit busts the byte SHA (cache miss) but must not move any anchor.
    (tmp_path / "src" / "pkg" / "b.py").write_text("def g():\n    # tweak\n    return 1\n")
    after, stats = build_graph(tmp_path, default_config())
    after_hashes = {n: d["content_hash"] for n, d in after.nodes(data=True) if "content_hash" in d}

    assert stats.extracted == 1 and stats.cached == 2  # only b.py re-parsed
    assert before_hashes == after_hashes


def test_graph_records_the_anchor_algo(tmp_path: Path):
    _make_repo(tmp_path)
    graph, _ = build_graph(tmp_path, default_config())
    assert graph.graph["anchor_algo"] == "astnorm-v1"


def test_build_cli_writes_the_graph(tmp_path: Path):
    _make_repo(tmp_path)
    result = runner.invoke(app, ["build", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Indexed 3 file(s)" in result.output
    assert (tmp_path / "yigraf" / "graph.json").is_file()


def test_build_cli_requires_a_workspace(tmp_path: Path):
    result = runner.invoke(app, ["build", str(tmp_path)])
    assert result.exit_code == 1
    assert "run `yigraf init`" in result.output
