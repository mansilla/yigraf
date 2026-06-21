from typer.testing import CliRunner

from yigraf import __version__
from yigraf.cli import app

runner = CliRunner()


def test_help_runs():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "yigraf" in result.output


def test_version_runs():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_init_via_cli(tmp_path):
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "yigraf" / "graph.json").is_file()
    assert "Initialized yigraf workspace" in result.output


def test_init_via_cli_idempotent(tmp_path):
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0
    assert "already present" in result.output
