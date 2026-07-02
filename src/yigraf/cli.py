"""The ``yigraf`` command-line interface.

M0 ships ``init`` only. Later milestones add the verbs the design names — ``intent`` / ``plan`` /
``link`` (M2), ``context`` (M4) — as sibling subcommands under this app.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import NoReturn

import typer

from yigraf import __version__, artifacts, counters, embeddings, memory, retrieval, status, update
from yigraf.astnorm import ANCHOR_ALGO
from yigraf.config import load_config
from yigraf.drift import compute_drift
from yigraf.extract import build_graph, symbol_content_hash
from yigraf.graph import from_node_link, write_graph
from yigraf.languages import available_extractors, extension_map
from yigraf.hooks import (_write_agents_block, detect_hosts, install_antigravity,
                          install_claude_hooks, install_codex_hooks, install_post_commit_hook)
from yigraf.scaffold import WORKSPACE_DIRNAME, init_workspace

_TASK_ID = re.compile(r"^task:(.+)/(\d+)$")


def _guidance(message: str) -> NoReturn:
    """Decline a recoverable condition with agent-facing guidance, exiting 0 (never a hard error).

    An unresolved locator, a near-duplicate, or a name that already exists is *not* a tool failure: a
    non-zero exit trains an agent to stop calling the tool ("errors teach abandonment", the lesson
    imported from CodeGraph). So we print how to fix it and exit 0 — the agent reads the guidance and
    retries with a corrected argument. Genuine "stop" cases (no workspace, the CI ``drift`` gate) keep
    their non-zero exit.
    """
    typer.echo(message)
    raise typer.Exit(code=0)


def _symbol_suggestion(graph, target: str) -> str:
    """A 'did you mean' tail for an unresolved ``sym:`` locator, fuzzy-matched against the graph."""
    candidates = [n for n in graph.nodes if str(n).startswith("sym:")]
    close = difflib.get_close_matches(target, candidates, n=3, cutoff=0.6)
    if close:
        return " Did you mean: " + ", ".join(close) + "?"
    name = target.split("#", 1)[-1]
    same_name = sorted(c for c in candidates if c.split("#", 1)[-1] == name)
    if same_name:
        return " A symbol named that exists at: " + ", ".join(same_name[:3]) + "."
    return f' Run `yigraf context "{name}"` to find its locator.'


def _anchor_or_guide(repo: Path, config: dict, target: str) -> str:
    """Stamp the astnorm anchor for ``target``; if it's unresolved, emit a 'did you mean' and exit 0."""
    anchor = symbol_content_hash(repo, target, config)
    if anchor is not None:
        return anchor
    graph, _ = build_graph(repo, config)
    _guidance(f"Couldn't find {target} in the current source." + _symbol_suggestion(graph, target))


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
    graph, stats = build_graph(root, config)  # maturity is git-derived inside build_graph (R2)
    write_graph(graph, workspace / "graph.json")
    reindexed = embeddings.refresh_index(root, graph, config)  # scoped semantic index (M8; no-op if no backend)

    typer.echo(
        f"Indexed {stats.files} file(s): {stats.extracted} parsed, {stats.cached} cached."
    )
    typer.echo(f"  {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges.")
    if reindexed:
        typer.echo("  embedding index refreshed.")


def _require_workspace(root: Path) -> Path:
    workspace = root / WORKSPACE_DIRNAME
    if not workspace.is_dir():
        typer.echo(f"No yigraf workspace at {workspace} — run `yigraf init` first.", err=True)
        raise typer.Exit(code=1)
    return workspace


def _rebuild(root: Path) -> None:
    """Re-project the graph so graph.json reflects a just-written artifact, and refresh the index.

    ``refresh_index`` re-embeds only memory/intent nodes whose text changed (a no-op — no model load —
    when nothing did), so a captured decision/intent becomes semantically searchable immediately.
    """
    config = load_config(root / WORKSPACE_DIRNAME / "config.yaml")
    graph, _ = build_graph(root, config)
    write_graph(graph, root / WORKSPACE_DIRNAME / "graph.json")
    embeddings.refresh_index(root, graph, config)


def _ranked_with_telemetry(root: Path, graph) -> None:
    """Overlay the machine-local usage/last_seen sidecar onto the graph for recency-aware ranking (R1).

    Read-path only: ``graph.json`` stays recomputable — telemetry is never written back into it.
    """
    counters.apply_telemetry(graph, counters.load_telemetry(root))


def _record_injection(root: Path, graph, result) -> None:
    """Record a surfacing in the gitignored telemetry sidecar (R1): a soft recency/popularity nudge.

    Machine-local and best-effort — it never touches the committed ``graph.json``, so a query/hook
    never dirties git. A failed write must never break a query or a hook.
    """
    try:
        counters.record_injection(root, graph, list(result.rendered))
    except OSError:
        pass


def _find_plan_file(workspace: Path, plan_slug_cf: str) -> Path | None:
    for sub in ("active", "completed"):
        for path in sorted((workspace / "plans" / sub).glob("*.md")):
            if path.stem.casefold() == plan_slug_cf:
                return path
    return None


def _known_plans(workspace: Path) -> list[str]:
    """Plan slugs across active/ and completed/ — for a 'did you mean' on an unknown plan."""
    out: list[str] = []
    for sub in ("active", "completed"):
        out += [p.stem for p in sorted((workspace / "plans" / sub).glob("*.md"))]
    return out


@app.command()
def intent(
    slug: str = typer.Argument(..., help="Slug for the intent file (intents/<slug>.md)."),
    statement: str = typer.Option(..., "--statement", "-s", help="One-line SHALL/MUST contract."),
    scenario: list[str] = typer.Option(None, "--scenario", help="A Given/When/Then example (repeatable)."),
    design: str = typer.Option(None, "--design", help="Optional approach / the 'how'."),
    type: str = typer.Option("requirement", "--type", help="requirement | goal | capability."),
    status: str = typer.Option("proposed", "--status", help="proposed | active | satisfied | archived."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Create an intent artifact (statement + scenarios + optional design)."""
    workspace = _require_workspace(repo)
    dest = workspace / "intents" / f"{slug}.md"
    if dest.exists():
        _guidance(f"Intent int:{slug.casefold()} already exists ({dest}). Edit it directly, or pick a new slug.")
    dest.write_text(
        artifacts.render_intent(slug, statement, scenario or [], design, type=type, status=status),
        encoding="utf-8",
    )
    _rebuild(repo)
    typer.echo(f"Created intent int:{slug.casefold()} ({dest})")


@app.command()
def plan(
    slug: str = typer.Argument(..., help="Slug for the plan file (plans/active/<slug>.md)."),
    title: str = typer.Option(..., "--title", "-t", help="Plan title."),
    task: list[str] = typer.Option(None, "--task", help="A task description (repeatable)."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Create a plan artifact with todo tasks (link/track them with `yigraf link`)."""
    workspace = _require_workspace(repo)
    dest = workspace / "plans" / "active" / f"{slug}.md"
    if dest.exists():
        _guidance(f"Plan plan:{slug.casefold()} already exists ({dest}). Edit it directly, or pick a new slug.")
    dest.write_text(artifacts.render_plan(slug, title, task or []), encoding="utf-8")
    _rebuild(repo)
    typer.echo(f"Created plan plan:{slug.casefold()} with {len(task or [])} task(s) ({dest})")


@app.command()
def link(
    task_id: str = typer.Argument(..., help="Task locator, e.g. task:<plan>/1."),
    target: str = typer.Argument(..., help="A symbol (sym:<path>#<name>) → implements, or an intent (int:<slug>) → tracks."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Declare an implements (→ symbol) or tracks (→ intent) edge from a task; stamps the anchor."""
    workspace = _require_workspace(repo)
    match = _TASK_ID.match(task_id)
    if match is None:
        _guidance(f"{task_id} isn't a task locator (expected task:<plan>/<n>, e.g. task:auth/1). "
                  f'Find tasks with `yigraf context "<plan>"`.')

    plan_file = _find_plan_file(workspace, match.group(1).casefold())
    if plan_file is None:
        known = _known_plans(workspace)
        _guidance(f"No plan found for {task_id}." +
                  (f" Known plans: {', '.join(known)}." if known else " Create one with `yigraf plan`."))
    tasks = artifacts.read_plan(plan_file).tasks
    if not any(t.id == task_id for t in tasks):
        ids = ", ".join(t.id for t in tasks) or "(none)"
        _guidance(f"{task_id} is not a task in {plan_file.name}. Tasks there: {ids}.")

    if target.startswith("sym:"):
        config = load_config(workspace / "config.yaml")
        anchor = _anchor_or_guide(repo, config, target)
        artifacts.add_edge_to_plan(plan_file, task_id, "implements", target, anchor=anchor)
        typer.echo(f"Linked {task_id} —implements→ {target} (anchored {anchor[:12]})")
    elif target.startswith("int:"):
        artifacts.add_edge_to_plan(plan_file, task_id, "tracks", target)
        typer.echo(f"Linked {task_id} —tracks→ {target}")
    else:
        _guidance("Target must be a symbol (sym:<path>#<name>) → implements, or an intent "
                  f"(int:<slug>) → tracks. Got: {target}")

    _rebuild(repo)


def _resolve_concerns(repo: Path, workspace: Path, syms: list[str]) -> list[memory.Concern]:
    """Resolve each ``--concerns`` symbol to a :class:`Concern` with a stamped anchor (or exit)."""
    config = load_config(workspace / "config.yaml")
    concerns: list[memory.Concern] = []
    for sym in syms:
        if not sym.startswith("sym:"):
            _guidance(f"--concerns must be a symbol (sym:<path>#<name>), got: {sym}")
        anchor = _anchor_or_guide(repo, config, sym)
        concerns.append(memory.Concern(sym=sym, anchor=anchor, anchor_algo=ANCHOR_ALGO))
    return concerns


def _dedup_guard(repo: Path, config: dict, statement: str, why: str,
                 concerns: list[memory.Concern], serves: list[str]) -> None:
    """Advisory write-time near-duplicate check (capture-flow §4); no-op without an embedding backend.

    Builds the current graph + asks the index for the most similar *active* memory node sharing a
    serves/concerns target; over the ``dup_cosine`` threshold ⇒ refuse (point at it; suggest supersede
    or ``--new``). Cheap when there's no backend (returns immediately) — dedup is then trivially skipped.
    """
    graph, _ = build_graph(repo, config)
    text = statement + (f"\n{why}" if why else "")
    scope = set(serves) | {c.sym for c in concerns}
    hit = embeddings.most_similar_memory(repo, graph, config, text, scope)
    threshold = config.get("embeddings", {}).get("dup_cosine", 0.9)
    if hit and hit[1] >= threshold:
        _guidance(
            f"This looks like a near-duplicate of {hit[0]} (cosine {hit[1]:.2f}). "
            f"If you're changing your mind, `yigraf supersede {hit[0]} \"<new>\"`; "
            f"otherwise re-run with --new to capture it anyway."
        )


def _capture_memory(repo: Path, workspace: Path, *, statement: str, type_: str, why: str,
                    serves: list[str], concern_syms: list[str], rejected: str | None,
                    supersedes: list[str], promotable: bool, force_new: bool = False) -> memory.Memory:
    """Write a new memory artifact, then rebuild graph.json. Shared by remember/supersede/note-constraint."""
    if type_ not in memory.MEMORY_TYPES:
        _guidance(f"--type must be one of {', '.join(memory.MEMORY_TYPES)} (got {type_}).")

    concerns = _resolve_concerns(repo, workspace, concern_syms)
    # A supersede is a deliberate mind-change (it *should* resemble its predecessor) → skip the guard.
    if not supersedes and not force_new:
        _dedup_guard(repo, load_config(workspace / "config.yaml"), statement, why, concerns, serves)
    seq = memory.next_seq(repo)
    slug = memory.slugify(statement)
    node = memory.Memory(
        id=f"mem:{seq:03d}", seq=seq, slug=slug, type=type_, statement=statement, why=why,
        alternatives=rejected, serves=list(serves), concerns=concerns, supersedes=list(supersedes),
        promotable=promotable, provenance={"source": "cli"},
    )
    dest = memory.memory_path(repo, seq, slug)
    dest.write_text(memory.render_memory(node), encoding="utf-8")
    _rebuild(repo)
    return node


def _report_capture(node: memory.Memory) -> None:
    bits = [f"type={node.type}"]
    if node.serves:
        bits.append("serves " + ", ".join(node.serves))
    if node.concerns:
        bits.append("concerns " + ", ".join(c.sym for c in node.concerns))
    if node.supersedes:
        bits.append("supersedes " + ", ".join(node.supersedes))
    typer.echo(f"Captured {node.id} ({'; '.join(bits)})")


@app.command()
def remember(
    statement: str = typer.Argument(..., help="The claim in one line (the H2 heading)."),
    type: str = typer.Option("decision", "--type", help=f"One of: {', '.join(memory.MEMORY_TYPES)}."),
    why: str = typer.Option("", "--why", help="The reasoning (ReCAP's T) — what /clear loses."),
    serves: list[str] = typer.Option(None, "--serves", help="An intent/plan id this serves (repeatable)."),
    concerns: list[str] = typer.Option(None, "--concerns", help="A symbol this governs, sym:<path>#<name> (repeatable, anchored)."),
    rejected: str = typer.Option(None, "--rejected", help="The rejected alternative + why (the most perishable content)."),
    new: bool = typer.Option(False, "--new", help="Capture even if it looks like a near-duplicate (skip the dedup guard)."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Capture a decision/rationale/learned-fact as a memory node (serves an intent, concerns code)."""
    workspace = _require_workspace(repo)
    node = _capture_memory(repo, workspace, statement=statement, type_=type, why=why,
                           serves=serves or [], concern_syms=concerns or [], rejected=rejected,
                           supersedes=[], promotable=False, force_new=new)
    _report_capture(node)


@app.command(name="note-constraint")
def note_constraint(
    rule: str = typer.Argument(..., help="The constraint in one line."),
    concerns: list[str] = typer.Option(None, "--concerns", help="A symbol this constrains, sym:<path>#<name> (repeatable, anchored)."),
    why: str = typer.Option("", "--why", help="Why the constraint holds (optional)."),
    serves: list[str] = typer.Option(None, "--serves", help="An intent/plan id this serves (repeatable)."),
    new: bool = typer.Option(False, "--new", help="Capture even if it looks like a near-duplicate (skip the dedup guard)."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Capture a constraint memory (flagged promotable to an enforced check; capture-flow §0a)."""
    workspace = _require_workspace(repo)
    node = _capture_memory(repo, workspace, statement=rule, type_="constraint", why=why,
                           serves=serves or [], concern_syms=concerns or [], rejected=None,
                           supersedes=[], promotable=True, force_new=new)
    _report_capture(node)


@app.command()
def supersede(
    old_id: str = typer.Argument(..., help="The memory id being superseded, e.g. mem:001."),
    statement: str = typer.Argument(..., help="The new claim in one line."),
    type: str = typer.Option("decision", "--type", help=f"One of: {', '.join(memory.MEMORY_TYPES)}."),
    why: str = typer.Option("", "--why", help="Why the mind changed."),
    serves: list[str] = typer.Option(None, "--serves", help="An intent/plan id this serves (repeatable)."),
    concerns: list[str] = typer.Option(None, "--concerns", help="A symbol this governs (repeatable, anchored)."),
    rejected: str = typer.Option(None, "--rejected", help="The rejected alternative + why."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Record a mind-change: a new memory node with a supersedes edge to the old one (never edit-in-place)."""
    workspace = _require_workspace(repo)
    if memory.find_memory(repo, old_id) is None:
        _guidance(f"No memory node with id {old_id} to supersede. "
                  f'Find the decision you mean with `yigraf context "<topic>"`.')
    node = _capture_memory(repo, workspace, statement=statement, type_=type, why=why,
                           serves=serves or [], concern_syms=concerns or [], rejected=rejected,
                           supersedes=[old_id], promotable=False)
    _report_capture(node)


@app.command()
def context(
    query: str = typer.Argument(..., help="What to look up, e.g. \"session expiry\"."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
    family: str = typer.Option(None, "--family", help="Restrict to one family: structure|intent|plan."),
    budget: int = typer.Option(None, "--budget", help="Token budget for the render."),
) -> None:
    """Retrieve a scoped, token-budgeted slice of the graph for a query (locators + signatures)."""
    workspace = _require_workspace(repo)
    config = load_config(workspace / "config.yaml")
    graph, _ = build_graph(repo, config)
    _ranked_with_telemetry(repo, graph)  # recency/popularity overlay from the local sidecar (R1)
    semantic = embeddings.semantic_scores(repo, graph, config, query)  # {} ⇒ lexical-only (M8 / v0)
    result = retrieval.context(graph, query, config, family=family, budget_tokens=budget,
                               semantic_match=semantic, root=repo)
    _record_injection(repo, graph, result)  # a surfacing is a soft usage signal (sidecar, not graph.json)
    typer.echo(result.text, nl=False)
    typer.echo(f"[~{result.token_estimate} tokens · {result.nodes_rendered}/{result.nodes_total} nodes shown]")


@app.command("status")
def status_cmd(
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
    as_json: bool = typer.Option(False, "--json", help="Emit the summary as JSON (for a host adapter)."),
    ctx_used: int = typer.Option(None, "--ctx-used", help="Context tokens in use (host/adapter-supplied; optional)."),
    ctx_limit: int = typer.Option(None, "--ctx-limit", help="Context window size in tokens (host/adapter-supplied; optional)."),
    color: bool = typer.Option(None, "--color/--no-color", help="Force/disable ANSI color + glyphs (default: auto — on for a TTY)."),
) -> None:
    """Print a host-agnostic status line (graph scale, drift, freshness, semantic, context) for an ambient UI.

    The agnostic backbone of the status surface (int:status-surface): a per-host adapter (e.g. a Claude
    Code ``statusLine`` running ``yigraf status --color``) renders this; the human sees graph health
    without spending the agent's context budget. ``--ctx-*`` are the one non-agnostic, host-fed datum.
    """
    workspace = _require_workspace(repo)
    config = load_config(workspace / "config.yaml")
    update.refresh(repo)  # throttled (≤1×/day) + fail-open: refresh the "newer yigraf on PyPI?" cache
    graph, _ = build_graph(repo, config)  # no telemetry overlay — keep graph byte-equal for freshness
    summary = status.compute_status(graph, repo, config, ctx_used=ctx_used, ctx_limit=ctx_limit)
    if as_json:
        typer.echo(json.dumps(summary.as_dict()))
        return
    # Auto: color a TTY (honoring NO_COLOR); a statusline pipes stdout, so it passes --color explicitly.
    use_color = color if color is not None else (sys.stdout.isatty() and not os.environ.get("NO_COLOR"))
    icon = status.SPIN[int(time.time()) % len(status.SPIN)] if use_color else None
    # color= keeps click from stripping ANSI on a non-TTY pipe — exactly the statusline's case.
    typer.echo(summary.render_line(color=use_color, icon=icon), color=use_color)
    # A one-line "how to update" notice, only for a human at a real terminal (never a piped statusline).
    if summary.update and sys.stdout.isatty():
        typer.echo(f"⬆ yigraf {summary.update} is available — update with: "
                   f"uv tool upgrade yigraf  (or: pipx upgrade yigraf · pip install -U yigraf)")


def _claude_ctx(data: dict) -> tuple[Path, int | None, int | None]:
    """Derive ``(repo, ctx_used, ctx_limit)`` from Claude Code's statusline stdin event.

    Host-specific glue, NOT the agnostic core: ``compute_status`` never reads a transcript (mem:013),
    so this Claude-Code-shaped parse lives here in the adapter command. Token usage = the last
    transcript record's input + cache-read + cache-creation tokens; the window ceiling is model-derived
    (1M-context models report a larger limit). Stdlib ``json`` only — no ``jq``. A missing transcript or
    usage record ⇒ no ctx, and the bar simply renders without the gauge.
    """
    workspace = data.get("workspace") or {}
    repo = Path(workspace.get("current_dir") or data.get("cwd") or ".")
    model_id = ((data.get("model") or {}).get("id") or "")
    limit = 1_000_000 if "1m" in model_id.lower() else 200_000
    used: int | None = None
    tx = data.get("transcript_path")
    if tx and Path(tx).is_file():
        for line in Path(tx).read_text(encoding="utf-8").splitlines():
            try:
                usage = (json.loads(line).get("message") or {}).get("usage")
            except ValueError:
                continue
            if usage:  # keep the last usage record's running total
                used = (usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)) or None
    return repo, used, (limit if used is not None else None)


@app.command("statusline")
def statusline_cmd(
    repo: Path = typer.Option(None, "--repo", help="Repo root; default: the event's cwd, else current dir."),
) -> None:
    """Claude Code statusline adapter: render the [Yigraf] bar with a context-window gauge.

    Wired by ``install-claude-hooks`` as the ``statusLine`` command. Reads Claude Code's session JSON
    on stdin, derives context-window occupancy from the transcript (host-specific; the agnostic core
    never reads a transcript — mem:013), and prints the colored bar. Dependency-free (stdlib ``json``,
    no ``jq``; no shell) and fail-open: any error prints nothing rather than breaking the statusline.
    """
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        data = {}
    try:
        event_repo, ctx_used, ctx_limit = _claude_ctx(data)
        root = repo or event_repo
        workspace = root / WORKSPACE_DIRNAME
        if not workspace.is_dir():
            return  # ungoverned repo — stay silent (fail-open)
        update.refresh(root)  # throttled (≤1×/day) + fail-open: the "newer yigraf on PyPI?" check
        config = load_config(workspace / "config.yaml")
        graph, _ = build_graph(root, config)
        summary = status.compute_status(graph, root, config, ctx_used=ctx_used, ctx_limit=ctx_limit)
        icon = status.SPIN[int(time.time()) % len(status.SPIN)]
        typer.echo(summary.render_line(color=True, icon=icon), color=True)
    except Exception:  # noqa: BLE001 — an ambient surface must never break the host (design law #5)
        return


@app.command("mcp")
def mcp_cmd(
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root the server serves (default: cwd; or $YIGRAF_REPO)."),
) -> None:
    """Run yigraf as an MCP server (stdio) — the host-agnostic pull channel (int:mcp-server).

    Any MCP host (Codex, Antigravity, Cursor, Claude Code, …) can then pull the graph as tool calls:
    `context` (the governing slice) and `status`. See docs/mcp.md for per-host config. The MCP SDK is
    a core dependency, so this always runs.
    """
    from yigraf import mcp_server  # lazy: keep the SDK import off every other command's path
    raise typer.Exit(code=mcp_server.run(repo))


@app.command()
def drift(
    path: Path = typer.Argument(Path("."), help="Repo root (default: current dir)."),
) -> None:
    """Report implements-edge drift: soft (body changed), hard (symbol gone), and renames."""
    workspace = _require_workspace(path)
    config = load_config(workspace / "config.yaml")
    graph, _ = build_graph(path, config)  # build re-anchors renames in-memory first
    items = compute_drift(graph)

    if not items:
        typer.echo("No drift.")
        return

    for item in items:
        if item.kind == "renamed":
            typer.echo(f"renamed (re-anchored): {item.task_id}  {item.locator} ⇒ {item.new_locator}")
        elif item.kind == "soft":
            typer.echo(f"soft drift: {item.task_id} → {item.locator} ({item.detail})")
        else:
            typer.echo(f"hard drift: {item.task_id} → {item.locator} ({item.detail})")

    if any(item.kind in ("soft", "hard") for item in items):
        raise typer.Exit(code=1)


@app.command()
def gc(
    path: Path = typer.Argument(Path("."), help="Repo root (default: current dir)."),
    apply: bool = typer.Option(False, "--apply", help="Actually archive (default: dry-run report)."),
) -> None:
    """Archive superseded churn memory — never delete, never gate on usage (DESIGN R3).

    A superseded node nothing still references (``superseded_in>0 ∧ refs_in=0``) is moved to
    ``yigraf/memory/archive/`` — out of the active graph but kept in the repo for history. A
    superseded node that's still referenced is left in place as an available rejected alternative.
    Dry-run by default — pass ``--apply`` to move the artifacts (the source of truth).
    """
    workspace = _require_workspace(path)
    config = load_config(workspace / "config.yaml")
    graph, _ = build_graph(path, config)
    actions = counters.classify_gc(graph)

    if not actions:
        typer.echo("Nothing to collect (no superseded, unreferenced memory).")
        return

    for mem_id in sorted(actions):
        label = graph.nodes[mem_id].get("statement") or mem_id
        typer.echo(f"  {'✓' if apply else '·'} {mem_id} → archive (superseded churn, kept as history): {label}")

    if not apply:
        typer.echo(f"Dry run — {len(actions)} node(s) would be archived. Re-run with --apply.")
        return

    archive_dir = workspace / "memory" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    for mem_id in sorted(actions):
        mem_path = memory.find_memory(path, mem_id)
        if mem_path is None:
            continue
        mem_path.rename(archive_dir / mem_path.name)  # out of memory/*.md → drops from the active graph
    _rebuild(path)
    typer.echo(f"Archived {len(actions)} node(s) → {archive_dir.relative_to(path)}/.")


@app.command(name="graph-merge")
def graph_merge(
    base: Path = typer.Argument(..., help="Common-ancestor graph.json (git %O; ignored — v0 graph.json is recomputable)."),
    ours: Path = typer.Argument(..., help="Our graph.json (git %A) — the merged result is written here."),
    theirs: Path = typer.Argument(..., help="Their graph.json (git %B)."),
) -> None:
    """Union-merge driver for graph.json (DESIGN R1): union nodes+edges so branches don't conflict.

    Registered as ``merge=yigraf-graph`` (see ``.gitattributes``) by ``yigraf install-hooks``. v0
    ``graph.json`` holds only *recomputable* state, so the post-merge build re-projects it exactly —
    this driver just avoids a line-level JSON conflict in the meantime (no counter reconciliation;
    that's the v1/Enterprise shared-counter model). git invokes it as ``graph-merge %O %A %B`` and
    expects the result in %A with exit 0.
    """
    def _load(p: Path) -> dict:
        try:
            return json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    merged = counters.merge_node_link(_load(ours), _load(theirs))
    write_graph(from_node_link(merged), ours)


@app.command(name="install-hooks")
def install_hooks(
    path: Path = typer.Argument(Path("."), help="Repo root (must be a git repository)."),
) -> None:
    """Install the post-commit git hook that keeps graph.json synced to HEAD (fail-open)."""
    _require_workspace(path)
    try:
        result = install_post_commit_hook(path)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)
    if not result.installed:
        typer.echo(f"A non-yigraf post-commit hook already exists at {result.path} — left untouched.")
        raise typer.Exit(code=1)
    typer.echo(f"Installed post-commit hook at {result.path}")
    if result.merge_driver:
        typer.echo("Registered graph.json union-merge driver (merge=yigraf-graph).")
    else:
        typer.echo("Could not register the graph.json merge driver (git config unavailable) — "
                   "graph.json will fall back to an ordinary 3-way merge.")


@app.command(name="install-claude-hooks")
def install_claude_hooks_cmd(
    path: Path = typer.Argument(Path("."), help="Repo root to wire up for Claude Code."),
) -> None:
    """Register the PostToolUse + SessionStart hooks + skill so Claude Code surfaces intent & drift."""
    _require_workspace(path)
    result = install_claude_hooks(path)
    typer.echo(f"Wrote hooks → {result.settings_path} (per-machine, gitignored)")
    typer.echo(f"Wrote skill → {result.skill_path}")
    typer.echo(f"Updated     → {result.agents_path}")
    _STATUSLINE_NOTE = {
        "set": "Statusline → wired to `yigraf statusline` — the [Yigraf] bar + ctx gauge on every refresh.",
        "refreshed": "Statusline → re-pointed at `yigraf statusline` for this clone's interpreter.",
        "kept-foreign": "Statusline → left your existing statusLine intact (point it at `yigraf statusline` to use the bar).",
        "unchanged": "Statusline → already wired to `yigraf statusline`.",
    }
    typer.echo(_STATUSLINE_NOTE[result.statusline])
    typer.echo("Teammates: re-run this command on your clone to wire your own interpreter path.")


@app.command(name="install-codex-hooks")
def install_codex_hooks_cmd(
    path: Path = typer.Argument(Path("."), help="Repo root to wire up for Codex CLI."),
) -> None:
    """Wire yigraf's SessionStart + PostToolUse hooks into Codex (.codex/hooks.json) + AGENTS.md.

    The push-channel complement for Codex (its hooks mirror Claude Code's). SessionStart re-injection
    is reliable; PostToolUse-on-edit is best-effort — verify your Codex version's edit-tool name.
    """
    _require_workspace(path)
    result = install_codex_hooks(path)
    typer.echo(f"Wrote hooks → {result.hooks_path} (per-machine, gitignored)")
    typer.echo(f"Updated     → {result.agents_path}")
    typer.echo("Note: Codex loads project `.codex/` hooks only for a *trusted* project; trust it once.")
    typer.echo("Teammates: re-run this command on your clone to wire your own interpreter path.")


@app.command(name="install-antigravity")
def install_antigravity_cmd(
    path: Path = typer.Argument(Path("."), help="Repo root to wire up for the Antigravity IDE."),
) -> None:
    """Wire yigraf for Antigravity (which has no hooks): an always-on .agents/rule + AGENTS.md + MCP.

    Antigravity has no lifecycle hook, so the complement is an always-on rule pointing the agent at the
    yigraf MCP tools. Add the printed MCP-server entry via Antigravity's MCP editor to finish wiring.
    """
    _require_workspace(path)
    result = install_antigravity(path)
    typer.echo(f"Wrote rule → {result.rule_path}")
    typer.echo(f"Updated    → {result.agents_path}")
    typer.echo("\nNow add the yigraf MCP server in Antigravity (Agent panel → MCP Servers → raw config),")
    typer.echo("in ~/.gemini/antigravity/mcp_config.json (or ~/.gemini/config/mcp_config.json):")
    _print_mcp_config(path)


def _print_mcp_config(repo: Path) -> None:
    """Print the ``mcpServers`` entry for ``yigraf mcp`` — the universal pull setup any MCP host accepts."""
    cfg = {"mcpServers": {"yigraf": {
        "command": sys.executable,
        "args": ["-m", "yigraf", "mcp", "--repo", str(Path(repo).resolve())]}}}
    typer.echo(json.dumps(cfg, indent=2))


@app.command(name="install")
def install_cmd(
    path: Path = typer.Argument(Path("."), help="Repo root to wire up."),
    host: str = typer.Option("auto", "--host",
                             help="auto | claude | codex | antigravity | mcp (default: auto-detect)."),
) -> None:
    """Wire yigraf's full power by default — the host-agnostic channel every repo gets — plus any
    detected host's native push hooks layered on top.

    The **generic** channel installs unconditionally, because it works regardless of agent host: the
    post-commit rebuild hook + graph.json merge driver (keep graph.json fresh across commits/merges),
    the AGENTS.md instruction block (any agent reads it), and the MCP pull server (the universal
    channel every MCP host speaks). Then ``auto`` detects Claude Code / Codex / Antigravity and layers
    each host's native hooks over that; ``--host`` forces one. Only the heavy embeddings backend stays
    opt-in — install detects it's missing and prints the one-line command to turn it on.
    """
    workspace = _require_workspace(path)
    config = load_config(workspace / "config.yaml")

    # --- Generic channel (host-independent) — always on -------------------------------------------
    typer.echo("== generic (every host) ==")
    try:
        r = install_post_commit_hook(path)
        if r.installed:
            typer.echo(f"  post-commit → {r.path} (rebuilds graph.json on commit)")
            typer.echo("  merge-driver → " + ("registered (merge=yigraf-graph)" if r.merge_driver
                       else "skipped — git config unavailable; graph.json uses a plain 3-way merge"))
        else:
            typer.echo(f"  post-commit → left your existing non-yigraf hook at {r.path} untouched")
    except FileNotFoundError:
        typer.echo("  post-commit → skipped (not a git repository)")
    typer.echo(f"  AGENTS.md   → {_write_agents_block(path / 'AGENTS.md')} (host-agnostic instructions)")
    typer.echo("  MCP pull server (works with any MCP host):")
    _print_mcp_config(path)

    # --- Capability check: embeddings (opt-in, but loudly offered — never a silent degrade) -------
    if not embeddings.backend_available(config):
        typer.echo("\n⚠ semantic recall is OFF — retrieval is lexical-only. Turn it on with:")
        typer.echo("    uv pip install 'yigraf[embeddings]'   # local bge-small, pulls ~1GB torch")
        typer.echo("  (Optional — yigraf works without it, just with weaker recall.)")

    # --- Host-specific push channels (layered on top of the generic channel above) ----------------
    choice = host.lower()
    if choice == "auto":
        targets = detect_hosts(path)
        typer.echo("\nDetected host(s): " + (", ".join(targets) if targets
                   else "none (Claude Code / Codex / Antigravity) — the generic MCP channel covers you"))
    elif choice in ("claude", "codex", "antigravity"):
        targets = [choice]
    else:  # "mcp" or any unrecognized host name → generic MCP channel above is all that's needed
        targets = []

    for h in targets:
        typer.echo(f"\n== {h} ==")
        if h == "claude":
            r = install_claude_hooks(path)
            typer.echo(f"  hooks → {r.settings_path}  ·  skill → {r.skill_path}  ·  AGENTS → {r.agents_path}")
            typer.echo(f"  statusline → {r.statusline} ([Yigraf] bar + ctx gauge; no deps)")
        elif h == "codex":
            r = install_codex_hooks(path)
            typer.echo(f"  hooks → {r.hooks_path}  ·  AGENTS → {r.agents_path}")
            typer.echo("  (Codex loads project `.codex/` hooks only for a *trusted* project.)")
        elif h == "antigravity":
            r = install_antigravity(path)
            typer.echo(f"  rule → {r.rule_path}  ·  AGENTS → {r.agents_path}")
            typer.echo("  add the yigraf MCP server (config above) via Antigravity's MCP editor.")


# --- Claude Code hook entry points (invoked by the hooks above; read event JSON on stdin) ----------

hook_app = typer.Typer(help="Claude Code hook entry points (read the hook event JSON on stdin).",
                       no_args_is_help=True, add_completion=False)
app.add_typer(hook_app, name="hook")


def _run_hook(handler) -> None:
    """Run a hook handler fail-open: parse stdin JSON, print the payload if any, always exit 0."""
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        payload = handler(data)
        if payload is not None:
            typer.echo(json.dumps(payload))
    except Exception:
        pass  # never block or fail the tool/session (R8 fail-open)
    raise typer.Exit(code=0)


def _hook_graph(root: Path):
    """Build the graph for a hook, or None if there's no workspace (→ stay silent)."""
    if not (root / WORKSPACE_DIRNAME).is_dir():
        return None
    config = load_config(root / WORKSPACE_DIRNAME / "config.yaml")
    graph, _ = build_graph(root, config)
    return graph, config


#: Edit-tool names across hosts. Claude Code: Edit/Write/MultiEdit (clean ``file_path``). Codex: the
#: ``apply_patch`` family (path lives *inside* the patch text). Gating on the tool name keeps the hook
#: off frequent non-edit tools (Read) so it doesn't rebuild the graph on every call.
_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "apply_patch", "ApplyPatch",
                         "str_replace_editor", "create_file", "write_file"})
_PATCH_FILE = re.compile(r"^\*\*\*\s+(?:Add|Update|Delete) File:\s*(.+?)\s*$", re.MULTILINE)


def _edited_file(data: dict) -> str | None:
    """The file an edit tool touched, across hosts — or ``None`` (⇒ the hook stays silent, fail-open).

    A direct ``file_path``/``path`` covers Claude Code (Edit/Write/MultiEdit) and any host that hands a
    clean field. Codex's ``apply_patch`` carries the path inside the patch body, so fall back to the
    first ``*** Add|Update|Delete File: <path>`` line. An unknown shape returns ``None``.
    """
    if data.get("tool_name") not in _EDIT_TOOLS:
        return None
    tool_input = data.get("tool_input") or {}
    direct = tool_input.get("file_path") or tool_input.get("path")
    if direct:
        return direct
    for value in (tool_input.get("patch"), tool_input.get("input"), tool_input.get("changes")):
        if isinstance(value, str):
            m = _PATCH_FILE.search(value)
            if m:
                return m.group(1)
    return None


def _post_tool_use(data: dict) -> dict | None:
    file_path = _edited_file(data)
    if not file_path:
        return None
    root = Path(data.get("cwd") or os.getcwd())
    built = _hook_graph(root)
    if built is None:
        return None
    # Claude Code hands an absolute path; Codex's apply_patch path is repo-relative — anchor it to root.
    edited = Path(file_path)
    if not edited.is_absolute():
        edited = root / edited
    try:
        rel = edited.resolve().relative_to(root.resolve())
    except ValueError:
        return None  # edited file is outside the repo
    graph, config = built
    if rel.suffix not in extension_map(available_extractors(config)):
        return None  # not a language yigraf indexes in this repo
    _ranked_with_telemetry(root, graph)  # local recency/popularity overlay (R1)
    result = retrieval.context_for_locus(graph, rel.as_posix(), config, root=root)
    if result is None:
        return None  # silent: nothing governs this locus and no drift
    _record_injection(root, graph, result)  # a surfaced decision/intent is a soft usage signal (sidecar)
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": result.text}}


def _session_start(data: dict) -> dict | None:
    root = Path(data.get("cwd") or os.getcwd())
    built = _hook_graph(root)
    if built is None:
        return None
    graph, config = built
    _ranked_with_telemetry(root, graph)  # local recency/popularity overlay (R1)
    result = retrieval.session_context(graph, config, root=root)
    if result is None:
        return None
    _record_injection(root, graph, result)  # the re-injection is a soft usage signal (sidecar)
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": result.text}}


@hook_app.command("post-tool-use")
def hook_post_tool_use() -> None:
    """PostToolUse(Edit|Write): inject governing intent + drift for the touched file (silent-unless)."""
    _run_hook(_post_tool_use)


@hook_app.command("session-start")
def hook_session_start() -> None:
    """SessionStart(clear|compact|…): re-inject the active plan + governing intents."""
    _run_hook(_session_start)


def main() -> None:
    """Console-script entry point (see ``[project.scripts]`` in pyproject.toml)."""
    app()
