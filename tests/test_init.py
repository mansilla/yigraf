import json
from pathlib import Path

from yigraf.scaffold import init_workspace


def test_init_creates_full_tree(tmp_path: Path):
    init_workspace(tmp_path)
    ws = tmp_path / "yigraf"
    for d in ["intents", "plans/active", "plans/completed", "memory", "index", "cache", ".local"]:
        assert (ws / d).is_dir(), f"missing dir {d}"
    for f in ["config.yaml", "graph.json", ".gitignore", ".gitattributes"]:
        assert (ws / f).is_file(), f"missing file {f}"


def test_graph_stub_is_valid_empty_node_link(tmp_path: Path):
    init_workspace(tmp_path)
    data = json.loads((tmp_path / "yigraf" / "graph.json").read_text())
    assert data["directed"] is True
    assert data["nodes"] == []
    assert data["links"] == []
    assert data["graph"]["schema_version"] == 0


def test_workspace_gitignore_lists_runtime_dirs(tmp_path: Path):
    init_workspace(tmp_path)
    ignore = (tmp_path / "yigraf" / ".gitignore").read_text()
    patterns = {ln.strip() for ln in ignore.splitlines() if ln.strip() and not ln.startswith("#")}
    assert {"index/", "cache/", ".local/"} <= patterns


def test_gitattributes_has_union_merge_for_graph(tmp_path: Path):
    init_workspace(tmp_path)
    attrs = (tmp_path / "yigraf" / ".gitattributes").read_text()
    assert "graph.json" in attrs and "merge=" in attrs


def test_init_is_idempotent_and_does_not_clobber(tmp_path: Path):
    first = init_workspace(tmp_path)
    assert first.created and not first.already_initialized

    # Tamper with a created file; a second init must leave it untouched.
    cfg = tmp_path / "yigraf" / "config.yaml"
    cfg.write_text("maturity_k: 99\n")
    second = init_workspace(tmp_path)
    assert second.already_initialized
    assert cfg.read_text() == "maturity_k: 99\n"
