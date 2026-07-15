"""Whole-repo build: cache hits, byte-identical rebuilds, intra-repo import edges (M1 done-test)."""
import subprocess
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


def _make_pkg(root: Path) -> Path:
    """A two-level src-layout package (src/pkg + src/pkg/sub) for relative-import tests."""
    init_workspace(root)
    sub = root / "src" / "pkg" / "sub"
    sub.mkdir(parents=True)
    (root / "src" / "pkg" / "__init__.py").write_text("")
    (sub / "__init__.py").write_text("")
    (root / "src" / "pkg" / "b.py").write_text("def g():\n    return 1\n")
    return root / "src" / "pkg"


def test_sibling_relative_import_resolves(tmp_path: Path):
    pkg = _make_pkg(tmp_path)
    (pkg / "a.py").write_text("from .b import g\n\n\ndef f():\n    return g()\n")  # #16: `.b`
    graph, _ = build_graph(tmp_path, default_config())
    assert graph.has_edge("file:src/pkg/a.py", "file:src/pkg/b.py")


def test_parent_relative_import_resolves(tmp_path: Path):
    pkg = _make_pkg(tmp_path)
    (pkg / "sub" / "a.py").write_text("from ..b import g\n")  # #16: `..b` from src/pkg/sub → src/pkg/b
    graph, _ = build_graph(tmp_path, default_config())
    assert graph.has_edge("file:src/pkg/sub/a.py", "file:src/pkg/b.py")


def test_bare_relative_import_resolves_submodule(tmp_path: Path):
    pkg = _make_pkg(tmp_path)
    (pkg / "a.py").write_text("from . import b\n")  # #16: `from . import b` → sibling module b
    graph, _ = build_graph(tmp_path, default_config())
    assert graph.has_edge("file:src/pkg/a.py", "file:src/pkg/b.py")


def test_over_relative_import_makes_no_edge(tmp_path: Path):
    pkg = _make_pkg(tmp_path)
    (pkg / "a.py").write_text("from ....way.too.deep import g\n")  # more dots than depth → no phantom
    graph, _ = build_graph(tmp_path, default_config())
    assert not any(d == "file:src/pkg/b.py" for _, d in graph.out_edges("file:src/pkg/a.py"))


def test_ignore_supports_path_prefixes_not_just_dir_names(tmp_path: Path):
    # The config documents "path prefixes" — a multi-segment ignore must prune (not just bare dir names).
    init_workspace(tmp_path)
    (tmp_path / "keep.py").write_text("def a():\n    return 1\n")
    gen = tmp_path / "scripts" / "eval" / "runs"
    gen.mkdir(parents=True)
    (gen / "snap.py").write_text("def b():\n    return 2\n")
    cfg = default_config()
    cfg["ignore"] = list(cfg.get("ignore", [])) + ["scripts/eval/runs/"]
    graph, _ = build_graph(tmp_path, cfg)
    assert "sym:keep.py#a" in graph
    assert not any("scripts/eval/runs" in n for n in graph)  # path-prefix pruned the snapshot copy


def _git_init(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)


def test_gitignored_dir_is_never_indexed(tmp_path: Path):
    # The motivating crash: a build dir full of generated source (`.next/`) gets indexed and exhausts
    # RAM. In a git work tree, `.gitignore` is the arbiter — a gitignored tree is never enumerated.
    init_workspace(tmp_path)
    _git_init(tmp_path)
    (tmp_path / ".gitignore").write_text(".next/\n")
    (tmp_path / "app.py").write_text("def real():\n    return 1\n")
    generated = tmp_path / ".next" / "server" / "chunks"
    generated.mkdir(parents=True)
    (generated / "bundle.js").write_text("export function junk(){return 0}\n")

    graph, _ = build_graph(tmp_path, default_config())
    assert "sym:app.py#real" in graph
    assert not any(".next/" in n for n in graph)  # gitignored build output pruned wholesale


def test_explicit_ignore_excludes_a_git_tracked_dir(tmp_path: Path):
    # git would keep a *tracked* dir; the explicit `ignore` config must still prune it on the git path.
    init_workspace(tmp_path)
    _git_init(tmp_path)
    (tmp_path / "keep.py").write_text("def a():\n    return 1\n")
    tracked = tmp_path / "origins" / "clone"
    tracked.mkdir(parents=True)
    (tracked / "vendored.py").write_text("def b():\n    return 2\n")  # tracked, NOT gitignored here

    graph, _ = build_graph(tmp_path, default_config())  # default ignore lists `origins/`
    assert "sym:keep.py#a" in graph
    assert not any("origins/" in n for n in graph)


def test_go_import_edges_resolve_via_go_mod(tmp_path: Path):
    # task #5: a Go import is a package path; the go.mod module prefix maps it to a directory, and the
    # import edges go to every file of that package. `fmt` (external) makes no edge.
    init_workspace(tmp_path)
    (tmp_path / "go.mod").write_text("module myrepo\n\ngo 1.21\n")
    (tmp_path / "util").mkdir()
    (tmp_path / "util" / "u.go").write_text("package util\n\nfunc Help() int { return 1 }\n")
    (tmp_path / "main.go").write_text('package main\n\nimport (\n\t"fmt"\n\t"myrepo/util"\n)\n\n'
                                      "func main() { fmt.Println(util.Help()) }\n")
    graph, _ = build_graph(tmp_path, default_config())
    assert graph.has_edge("file:main.go", "file:util/u.go")
    assert graph["file:main.go"]["file:util/u.go"]["relation"] == "imports"
    assert not any(d == "file:main.go" for _, d in graph.out_edges("file:main.go"))  # no self/external edge


def test_inheritance_edge_resolves_same_file(tmp_path: Path):
    init_workspace(tmp_path)
    (tmp_path / "m.py").write_text("class Base:\n    pass\n\n\nclass C(Base):\n    pass\n")
    graph, _ = build_graph(tmp_path, default_config())
    assert graph.has_edge("sym:m.py#C", "sym:m.py#Base")
    assert graph["sym:m.py#C"]["sym:m.py#Base"]["relation"] == "inherits"


def test_inheritance_edge_resolves_across_relative_import(tmp_path: Path):
    init_workspace(tmp_path)
    pkg = tmp_path / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "base.py").write_text("class Base:\n    pass\n")
    (pkg / "impl.py").write_text("from .base import Base\n\n\nclass C(Base):\n    pass\n")
    graph, _ = build_graph(tmp_path, default_config())
    assert graph.has_edge("sym:src/pkg/impl.py#C", "sym:src/pkg/base.py#Base")
    assert graph["sym:src/pkg/impl.py#C"]["sym:src/pkg/base.py#Base"]["relation"] == "inherits"


def test_external_base_makes_no_inheritance_edge_or_phantom(tmp_path: Path):
    init_workspace(tmp_path)
    (tmp_path / "m.py").write_text("from typing import Protocol\n\n\nclass C(Protocol):\n    pass\n")
    graph, _ = build_graph(tmp_path, default_config())
    assert not graph.has_node("sym:typing#Protocol")  # external base → no phantom node
    assert all(d.get("relation") != "inherits"
               for _, _, d in graph.out_edges("sym:m.py#C", data=True))


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
    assert (tmp_path / "yigraf" / ".local" / "graph.db").is_file()  # gitignored materialized view


def test_build_cli_requires_a_workspace(tmp_path: Path):
    result = runner.invoke(app, ["build", str(tmp_path)])
    assert result.exit_code == 1
    assert "run `yigraf init`" in result.output
