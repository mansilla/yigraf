"""yigraf as an MCP server — the host-agnostic *pull* channel (int:mcp-server).

One adapter, every MCP host. Claude Code gets yigraf's value through push hooks, but Codex, Antigravity,
Cursor, Windsurf — and Claude Code too — all speak **MCP**, so exposing the graph as MCP tools reaches
them all with a single implementation. This is the pull channel: the agent *asks* for the slice (vs the
hook *pushing* it). Per the A-series eval pull is the weaker channel, but on a host with no lifecycle
hook (e.g. the Antigravity IDE) it's the only one — so it's how those hosts get yigraf at all.

Optional by design (mirrors ``mem:005``): the ``[mcp]`` extra carries the SDK; absent it, ``yigraf mcp``
prints an install hint and exits non-zero rather than crashing. The CLI + Claude Code hooks never need it.

Read tools (``context``, ``status``) run **in-process** so the structure graph + the embedding model
stay **warm** across calls in a session — a second ``context`` query doesn't re-pay the cold build/model
load. Write tools (``remember``/``link``/``note_constraint``/``supersede``) run the matching CLI verb in a
**subprocess** (arg-list, no shell): writes are rare and already rebuild the graph, and shelling out
reuses the CLI's dedup guard, anchoring, and exit-0 "did you mean" guidance verbatim — so the MCP write
path can't drift from the CLI's (``mem:018``). This completes the agent loop (context → link → remember)
on hosts with no lifecycle hook — the whole bet: one MCP surface, every vendor.
"""
from __future__ import annotations

import os
import subprocess
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


# ── Write verbs (subprocess) ────────────────────────────────────────────────────────────────────
# The capture/link verbs run the matching CLI command in a subprocess rather than in-process. Reads
# stay in-process for warmth (``mem:017``); writes are rare, already rebuild the graph, and — by
# shelling out — reuse the CLI's dedup guard, anchoring, and exit-0 "did you mean" guidance verbatim,
# so the MCP write path can never drift from the CLI's (``mem:018``). Args go as a list (no shell), so
# a multi-word ``--why`` needs no quoting.


def _multi(flag: str, values: list[str] | None) -> list[str]:
    """Expand a repeatable option: ``["a","b"] → [flag,"a",flag,"b"]``."""
    out: list[str] = []
    for v in values or []:
        out += [flag, v]
    return out


def _run_cli(verb: str, args: list[str], repo: str | None) -> str:
    """Run ``yigraf <verb> <args> --repo <root>`` and return its agent-facing output.

    The result is **stdout** — where success messages and the exit-0 "did you mean" guidance live.
    stderr carries embedding-model load progress / HF notices, so it's folded in only on a non-zero
    exit or when stdout is empty (a genuine error worth surfacing) — never polluting a normal result.
    """
    root = str(_resolve_root(repo))
    cmd = [sys.executable, "-m", "yigraf", verb, *args, "--repo", root]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=root)
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - environmental
        return f"yigraf {verb} could not run: {exc}"
    out = done.stdout.strip()
    if done.returncode != 0 or not out:
        return (out + "\n" + done.stderr.strip()).strip() or f"(yigraf {verb} produced no output)"
    return out


def run_link(repo: str | None, task: str, target: str) -> str:
    return _run_cli("link", [task, target], repo)


def run_remember(repo: str | None, statement: str, why: str = "", serves: list[str] | None = None,
                 concerns: list[str] | None = None, rejected: str | None = None,
                 type: str = "decision") -> str:
    args = [statement, "--type", type]
    if why:
        args += ["--why", why]
    args += _multi("--serves", serves) + _multi("--concerns", concerns)
    if rejected:
        args += ["--rejected", rejected]
    return _run_cli("remember", args, repo)


def run_note_constraint(repo: str | None, rule: str, concerns: list[str] | None = None,
                        why: str = "", serves: list[str] | None = None) -> str:
    args = [rule] + _multi("--concerns", concerns)
    if why:
        args += ["--why", why]
    args += _multi("--serves", serves)
    return _run_cli("note-constraint", args, repo)


def run_supersede(repo: str | None, old_id: str, statement: str, why: str = "",
                  serves: list[str] | None = None, concerns: list[str] | None = None,
                  rejected: str | None = None, type: str = "decision") -> str:
    args = [old_id, statement, "--type", type]
    if why:
        args += ["--why", why]
    args += _multi("--serves", serves) + _multi("--concerns", concerns)
    if rejected:
        args += ["--rejected", rejected]
    return _run_cli("supersede", args, repo)


def build_server(default_repo: str | None = None):
    """Construct the FastMCP server with yigraf's read + write tools. Imports the SDK lazily."""
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

    @server.tool()
    def link(task: str, target: str, repo: str | None = None) -> str:
        """Name what a finished task implements (or the intent it tracks), anchored to current content.

        Call this when you finish a task, to bind the task to the symbols that implement it — anchoring
        is what later surfaces drift when that code changes.

        Args:
            task: the task id, e.g. "task:auth/1".
            target: a symbol "sym:<path>#<name>" (implements) or an intent "int:<slug>" (tracks).
        """
        return run_link(repo or default_repo, task, target)

    @server.tool()
    def remember(statement: str, why: str = "", serves: list[str] | None = None,
                 concerns: list[str] | None = None, rejected: str | None = None,
                 type: str = "decision", repo: str | None = None) -> str:
        """Persist a non-obvious decision/rationale as a durable memory node — the *why* a reset loses.

        Capture at a conclusion (a chosen approach, a worked-around constraint), not mid-thinking. A
        `concerns` symbol is anchored, so editing that code later re-surfaces "re-verify this decision".

        Args:
            statement: the decision in one line.
            why: the reasoning — what a context reset would otherwise lose.
            serves: intent/plan ids this serves, e.g. ["int:auth"].
            concerns: symbols this governs, e.g. ["sym:auth/session.py#refresh"] (anchored).
            rejected: the rejected alternative + why not (the most perishable content).
            type: one of decision|constraint|learning (default decision).
        """
        return run_remember(repo or default_repo, statement, why, serves, concerns, rejected, type)

    @server.tool()
    def note_constraint(rule: str, concerns: list[str] | None = None, why: str = "",
                        serves: list[str] | None = None, repo: str | None = None) -> str:
        """Capture a constraint/rule governing code (flagged as a candidate to promote to a check).

        Args:
            rule: the rule, in one line.
            concerns: symbols it governs, e.g. ["sym:path.py#fn"] (anchored).
            why: why the rule exists.
            serves: intent/plan ids it serves.
        """
        return run_note_constraint(repo or default_repo, rule, concerns, why, serves)

    @server.tool()
    def supersede(old_id: str, statement: str, why: str = "", serves: list[str] | None = None,
                  concerns: list[str] | None = None, rejected: str | None = None,
                  type: str = "decision", repo: str | None = None) -> str:
        """Record a mind-change: a new memory node that supersedes an old one (never edit in place).

        Args:
            old_id: the memory being superseded, e.g. "mem:007".
            statement: the new decision in one line.
            why: what changed.
            serves/concerns/rejected/type: as for `remember`.
        """
        return run_supersede(repo or default_repo, old_id, statement, why, serves, concerns, rejected, type)

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
