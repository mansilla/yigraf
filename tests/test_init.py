from pathlib import Path

from yigraf.scaffold import init_workspace


def test_init_creates_full_tree(tmp_path: Path):
    init_workspace(tmp_path)
    ws = tmp_path / "yigraf"
    for d in ["intents", "plans/active", "plans/completed", "memory", "index", "cache", ".local"]:
        assert (ws / d).is_dir(), f"missing dir {d}"
    for f in ["config.yaml", ".gitignore"]:
        assert (ws / f).is_file(), f"missing file {f}"


def test_init_commits_no_projection(tmp_path: Path):
    """The graph is a gitignored SQLite view materialized on first build (mem:059) — init lays down no
    committed ``graph.json`` and no ``.gitattributes`` merge driver (both retired with the whole-graph lock)."""
    init_workspace(tmp_path)
    ws = tmp_path / "yigraf"
    assert not (ws / "graph.json").exists()
    assert not (ws / ".gitattributes").exists()
    assert not (ws / ".local" / "graph.db").exists()  # materialized lazily, not at init


def test_workspace_gitignore_lists_runtime_dirs_and_legacy_graph(tmp_path: Path):
    init_workspace(tmp_path)
    ignore = (tmp_path / "yigraf" / ".gitignore").read_text()
    patterns = {ln.strip() for ln in ignore.splitlines() if ln.strip() and not ln.startswith("#")}
    assert {"index/", "cache/", ".local/"} <= patterns
    assert "graph.json" in patterns  # a stale pre-v1 committed projection drops out of git once removed


def test_init_is_idempotent_and_does_not_clobber(tmp_path: Path):
    first = init_workspace(tmp_path)
    assert first.created and not first.already_initialized

    # Tamper with a created file; a second init must leave it untouched.
    cfg = tmp_path / "yigraf" / "config.yaml"
    cfg.write_text("maturity_k: 99\n")
    second = init_workspace(tmp_path)
    assert second.already_initialized
    assert cfg.read_text() == "maturity_k: 99\n"
