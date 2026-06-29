"""yigraf MCP server (int:mcp-server) — the verbs-as-functions, tool registration, graceful absence.

The ``run_context``/``run_status`` functions need no SDK (they're the CLI verbs as plain functions);
``build_server`` + the tool surface need the ``[mcp]`` extra and are skipped when it's absent — so the
suite passes either way, the same fallback discipline the embeddings suite proves.
"""
import asyncio
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


def test_run_guides_when_sdk_absent(monkeypatch, capsys):
    """`yigraf mcp` without the [mcp] extra prints an install hint and exits non-zero — never crashes."""
    def _no_sdk(_default):
        raise ImportError("No module named 'mcp'")
    monkeypatch.setattr(mcp_server, "build_server", _no_sdk)
    assert mcp_server.run(".") == 1
    assert "[mcp] extra" in capsys.readouterr().err


def test_build_server_registers_read_tools(tmp_path: Path):
    import pytest
    pytest.importorskip("mcp")  # the [mcp] extra; skip cleanly when absent
    server = mcp_server.build_server(str(_repo(tmp_path)))
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"context", "status"} <= names
