"""yigraf as an MCP server — the host-agnostic *pull* channel (int:mcp-server).

One adapter, every MCP host. Claude Code gets yigraf's value through push hooks, but Codex, Antigravity,
Cursor, Windsurf — and Claude Code too — all speak **MCP**, so exposing the graph as MCP tools reaches
them all with a single implementation. This is the pull channel: the agent *asks* for the slice (vs the
hook *pushing* it). Per the A-series eval pull is the weaker channel, but on a host with no lifecycle
hook (e.g. the Antigravity IDE) it's the only one — so it's how those hosts get yigraf at all.

Optional by design (mirrors ``mem:005``): the ``[mcp]`` extra carries the SDK; absent it, ``yigraf mcp``
prints an install hint and exits non-zero rather than crashing. The CLI + Claude Code hooks never need it.

In-process (not a per-call CLI subprocess) so the structure graph + the embedding model stay **warm**
across tool calls within a session — a second ``context`` query doesn't re-pay the cold build/model load.
Read tools (``context``, ``status``) ship first; the capture verbs (``remember``/``link``) are the next
increment (they need the cli orchestration extracted to stay drift-safe).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from yigraf import counters, embeddings, retrieval
from yigraf import status as status_mod
from yigraf.config import load_config
from yigraf.extract import build_graph
from yigraf.scaffold import WORKSPACE_DIRNAME

INSTALL_HINT = (
    "yigraf mcp needs the optional [mcp] extra. Install it with:\n"
    "  uv pip install -e '.[mcp]'      # from a checkout\n"
    "  pip install 'yigraf[mcp]'       # from PyPI"
)


def _resolve_root(repo: str | os.PathLike | None) -> Path:
    """The repo the server serves: explicit arg › ``$YIGRAF_REPO`` › cwd."""
    return Path(repo or os.environ.get("YIGRAF_REPO") or ".").resolve()


def _no_workspace(root: Path, also_build: bool = False) -> str:
    tail = " (and `yigraf build`)" if also_build else ""
    return f"No yigraf workspace at {root / WORKSPACE_DIRNAME} — run `yigraf init`{tail} there first."


def run_context(repo: str | None, query: str, family: str | None = None,
                budget: int | None = None) -> str:
    """The ``context`` verb as a plain function (no typer): returns the rendered slice + footer.

    Mirrors ``cli.context`` so the MCP and CLI surfaces answer identically. Fail-soft: a missing
    workspace returns guidance text rather than raising (an MCP error is less useful to the agent).
    """
    root = _resolve_root(repo)
    if not (root / WORKSPACE_DIRNAME).is_dir():
        return _no_workspace(root, also_build=True)
    config = load_config(root / WORKSPACE_DIRNAME / "config.yaml")
    graph, _ = build_graph(root, config)
    counters.apply_telemetry(graph, counters.load_telemetry(root))  # recency/popularity overlay (R1)
    semantic = embeddings.semantic_scores(root, graph, config, query)  # {} ⇒ lexical-only
    result = retrieval.context(graph, query, config, family=family, budget_tokens=budget,
                               semantic_match=semantic, root=root)
    try:
        counters.record_injection(root, graph, list(result.rendered))  # soft usage signal (sidecar)
    except OSError:
        pass
    return (result.text
            + f"[~{result.token_estimate} tokens · {result.nodes_rendered}/{result.nodes_total} nodes shown]")


def run_status(repo: str | None) -> str:
    """The ``status`` verb as a plain function: the compact line (no ANSI — MCP text is for the model)."""
    root = _resolve_root(repo)
    if not (root / WORKSPACE_DIRNAME).is_dir():
        return _no_workspace(root)
    config = load_config(root / WORKSPACE_DIRNAME / "config.yaml")
    graph, _ = build_graph(root, config)
    return status_mod.compute_status(graph, root, config).render_line()


def build_server(default_repo: str | None = None):
    """Construct the FastMCP server with yigraf's read tools. Imports the SDK lazily (⇒ guided absence)."""
    from mcp.server.fastmcp import FastMCP  # ImportError here ⇒ the [mcp] extra isn't installed

    server = FastMCP("yigraf")

    @server.tool()
    def context(query: str, repo: str | None = None, family: str | None = None,
                budget: int | None = None) -> str:
        """Pull a token-cheap slice of the yigraf graph for what you're about to work on.

        Returns the governing intents (the SHALL/MUST contracts), the active plan, the implementing
        symbols as signatures, prior decisions and their *why*, and any drift to re-verify. Call this
        BEFORE writing or changing code in an area — it loads what governs it, so you don't re-derive
        intent or re-read files already encoded in the graph.

        Args:
            query: what you're about to work on, e.g. "session expiry" or "drift detection".
            repo: repo root (defaults to the server's configured root / $YIGRAF_REPO / cwd).
            family: optional filter — one of structure|intent|plan.
            budget: optional token budget for the slice.
        """
        return run_context(repo or default_repo, query, family, budget)

    @server.tool()
    def status(repo: str | None = None) -> str:
        """A compact status line for the yigraf graph: counts (symbols/intents/tasks/decisions),
        drift count, freshness (committed graph.json vs source), and the semantic index size."""
        return run_status(repo or default_repo)

    return server


def run(repo: str | os.PathLike | None = None) -> int:
    """Run the stdio MCP server, blocking until the client disconnects. Returns a process exit code."""
    default_repo = _resolve_root(repo)
    try:
        server = build_server(str(default_repo))
    except ImportError:
        print(INSTALL_HINT, file=sys.stderr)
        return 1
    os.environ.setdefault("YIGRAF_REPO", str(default_repo))  # so tool calls omitting repo resolve here
    server.run()  # stdio transport by default
    return 0
