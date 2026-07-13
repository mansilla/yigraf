"""yigraf MCP server (int:mcp-server) — the verbs-as-functions and the tool registration surface.

The MCP SDK is a core dependency (``yigraf install`` wires the pull channel by default), so
``build_server`` and the tool surface are always importable; the ``run_*`` functions are the CLI verbs
as plain functions and need no SDK at all.
"""
import asyncio
import re
from pathlib import Path

from typer.testing import CliRunner

from yigraf import mcp_server
from yigraf.cli import app

runner = CliRunner()


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def test_run_status_returns_the_line(tmp_path: Path):
    out = mcp_server.run_status(str(_repo(tmp_path)))
    assert out.startswith("yigraf ") and "fresh" in out and "\x1b[" not in out  # plain, no ANSI for MCP


def test_run_context_returns_a_slice_with_footer(tmp_path: Path):
    out = mcp_server.run_context(str(_repo(tmp_path)), "session refresh")
    assert "Context for" in out and "tokens" in out


def test_missing_workspace_is_guided_not_raised(tmp_path: Path):
    assert "No yigraf workspace" in mcp_server.run_status(str(tmp_path))
    assert "No yigraf workspace" in mcp_server.run_context(str(tmp_path), "anything")


def test_resolve_root_prefers_arg_then_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("YIGRAF_REPO", str(tmp_path / "from_env"))
    assert mcp_server._resolve_root(str(tmp_path / "explicit")).name == "explicit"
    assert mcp_server._resolve_root(None).name == "from_env"


def _linked_repo(tmp_path: Path) -> Path:
    """A built repo with a plan task ready to link/remember against."""
    root = _repo(tmp_path)
    assert runner.invoke(app, ["plan", "demo", "--repo", str(root), "-t", "Demo",
                               "--task", "do it"]).exit_code == 0
    return root


def test_link_writes_and_anchors(tmp_path: Path):
    out = mcp_server.run_link(str(_linked_repo(tmp_path)), "task:demo/1",
                              "sym:auth/session.py#refresh")
    assert "Linked task:demo/1" in out and "implements" in out


def test_bad_locator_returns_guidance_not_error(tmp_path: Path):
    """A write verb reuses the CLI's exit-0 'did you mean' guidance through MCP (errors teach abandonment)."""
    out = mcp_server.run_link(str(_linked_repo(tmp_path)), "task:demo/1",
                              "sym:auth/session.py#nope")
    assert "Couldn't find" in out and "Did you mean" in out


def test_remember_captures_a_decision(tmp_path: Path):
    out = mcp_server.run_remember(str(_linked_repo(tmp_path)), "use token rotation",
                                  why="security", concerns=["sym:auth/session.py#refresh"])
    assert out.startswith("Captured mem:") and "concerns" in out
    # stderr noise (model-load progress / HF notices) must not pollute a successful result.
    assert "Loading weights" not in out and "HF Hub" not in out


def test_reaffirm_re_anchors_through_mcp(tmp_path: Path):
    root = _linked_repo(tmp_path)
    captured = mcp_server.run_remember(str(root), "refresh stays immutable",
                                       concerns=["sym:auth/session.py#refresh"])
    mem = re.search(r"Captured (mem:[0-9a-f]{16})", captured).group(1)
    (root / "auth" / "session.py").write_text("def refresh(token):\n    return token + 1\n")  # drift
    out = mcp_server.run_reaffirm(str(root), mem)
    assert "re-anchored" in out and "drift cleared" in out


def test_supersede_intent_through_mcp(tmp_path: Path):
    root = _repo(tmp_path)
    assert runner.invoke(app, ["intent", "auth-aud", "--repo", str(root),
                               "-s", "SHALL bind on aud"]).exit_code == 0
    out = mcp_server.run_supersede_intent(str(root), "auth-aud", "auth-clientid",
                                          "SHALL bind on client_id", why="aud absent under the target runtime")
    assert "Superseded int:auth-aud → int:auth-clientid" in out and "supersedes" in out


def test_file_concern_through_mcp(tmp_path: Path):
    root = _repo(tmp_path)
    (root / "Dockerfile").write_text('FROM python:3.11\nENTRYPOINT ["python","-m","app"]\n')
    out = mcp_server.run_remember(str(root), "entrypoint must be exec-form",
                                  why="signal handling", concerns=["file:Dockerfile"])
    assert out.startswith("Captured mem:") and "file:Dockerfile" in out


def test_propose_lands_a_proposed_candidate_through_mcp(tmp_path: Path):
    out = mcp_server.run_propose(str(_linked_repo(tmp_path)),
                                 "never refresh without validating the token", from_="review",
                                 concerns=["sym:auth/session.py#refresh"], rejected="unchecked return")
    assert out.startswith("Captured mem:") and "constraint" in out  # review → constraint by default


def test_propose_bad_from_returns_guidance_not_error(tmp_path: Path):
    out = mcp_server.run_propose(str(_linked_repo(tmp_path)), "x", from_="scraped")
    assert "--from must be one of" in out  # exit-0 guidance reused through MCP


def test_multi_expands_repeatable_options():
    assert mcp_server._multi("--serves", ["int:a", "int:b"]) == ["--serves", "int:a", "--serves", "int:b"]
    assert mcp_server._multi("--concerns", None) == []


def test_build_server_registers_all_tools(tmp_path: Path):
    import pytest
    pytest.importorskip("mcp")  # core dep; this guards only a deps-not-synced editable checkout
    server = mcp_server.build_server(str(_repo(tmp_path)))
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"context", "status", "link", "remember", "note_constraint", "propose", "supersede",
            "reaffirm", "supersede_intent"} <= names
