"""The ``yigraf`` command-line interface.

M0 ships ``init`` only. Later milestones add the verbs the design names — ``intent`` / ``plan`` /
``link`` (M2), ``context`` (M4) — as sibling subcommands under this app.
"""
from __future__ import annotations

from pathlib import Path

import typer

from yigraf import __version__
from yigraf.config import load_config
from yigraf.extract import build_graph
from yigraf.graph import write_graph
from yigraf.scaffold import WORKSPACE_DIRNAME, init_workspace

app = typer.Typer(
    help="yigraf — one connected graph over code, intent, plan, and memory.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"yigraf {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the yigraf version and exit.",
    ),
) -> None:
    """yigraf — a harness primitive for AI coding agents."""


@app.command()
def init(
    path: Path = typer.Argument(
        Path("."),
        help="Repo root to initialize (defaults to the current directory).",
    ),
) -> None:
    """Create the yigraf/ workspace in a repo (idempotent)."""
    result = init_workspace(path)
    if result.already_initialized:
        typer.echo(f"yigraf workspace already present at {result.workspace} — nothing to do.")
        raise typer.Exit()
    typer.echo(f"Initialized yigraf workspace at {result.workspace}")
    for rel in result.created:
        typer.echo(f"  + {rel}")
    if result.skipped:
        typer.echo(f"  ({len(result.skipped)} item(s) already existed, left untouched)")


@app.command()
def build(
    path: Path = typer.Argument(
        Path("."),
        help="Repo root to index (must contain a yigraf/ workspace from `yigraf init`).",
    ),
) -> None:
    """Extract the structure graph from the repo's Python source into yigraf/graph.json."""
    root = Path(path)
    workspace = root / WORKSPACE_DIRNAME
    if not workspace.is_dir():
        typer.echo(f"No yigraf workspace at {workspace} — run `yigraf init` first.", err=True)
        raise typer.Exit(code=1)

    config = load_config(workspace / "config.yaml")
    graph, stats = build_graph(root, config)
    write_graph(graph, workspace / "graph.json")

    typer.echo(
        f"Indexed {stats.files} file(s): {stats.extracted} parsed, {stats.cached} cached."
    )
    typer.echo(f"  {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges.")


def main() -> None:
    """Console-script entry point (see ``[project.scripts]`` in pyproject.toml)."""
    app()
