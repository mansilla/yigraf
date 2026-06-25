"""The ``yigraf`` command-line interface.

M0 ships ``init`` only. Later milestones add the verbs the design names — ``intent`` / ``plan`` /
``link`` (M2), ``context`` (M4) — as sibling subcommands under this app.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import typer

from yigraf import __version__, artifacts, embeddings, memory, retrieval
from yigraf.astnorm import ANCHOR_ALGO
from yigraf.config import load_config
from yigraf.drift import compute_drift
from yigraf.extract import build_graph, symbol_content_hash
from yigraf.graph import write_graph
from yigraf.hooks import install_claude_hooks, install_post_commit_hook
from yigraf.scaffold import WORKSPACE_DIRNAME, init_workspace

_TASK_ID = re.compile(r"^task:(.+)/(\d+)$")

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


def _find_plan_file(workspace: Path, plan_slug_cf: str) -> Path | None:
    for sub in ("active", "completed"):
        for path in sorted((workspace / "plans" / sub).glob("*.md")):
            if path.stem.casefold() == plan_slug_cf:
                return path
    return None


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
        typer.echo(f"Intent already exists: {dest} — edit it directly.", err=True)
        raise typer.Exit(code=1)
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
        typer.echo(f"Plan already exists: {dest} — edit it directly.", err=True)
        raise typer.Exit(code=1)
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
        typer.echo(f"Not a task id: {task_id} (expected task:<plan>/<n>).", err=True)
        raise typer.Exit(code=1)

    plan_file = _find_plan_file(workspace, match.group(1).casefold())
    if plan_file is None:
        typer.echo(f"No plan found for {task_id}.", err=True)
        raise typer.Exit(code=1)
    if not any(t.id == task_id for t in artifacts.read_plan(plan_file).tasks):
        typer.echo(f"{task_id} is not a task in {plan_file.name}.", err=True)
        raise typer.Exit(code=1)

    if target.startswith("sym:"):
        config = load_config(workspace / "config.yaml")
        anchor = symbol_content_hash(repo, target, config)
        if anchor is None:
            typer.echo(f"Symbol not found in the current source: {target}", err=True)
            raise typer.Exit(code=1)
        artifacts.add_edge_to_plan(plan_file, task_id, "implements", target, anchor=anchor)
        typer.echo(f"Linked {task_id} —implements→ {target} (anchored {anchor[:12]})")
    elif target.startswith("int:"):
        artifacts.add_edge_to_plan(plan_file, task_id, "tracks", target)
        typer.echo(f"Linked {task_id} —tracks→ {target}")
    else:
        typer.echo("Target must be a symbol (sym:<path>#<name>) or an intent (int:<slug>).", err=True)
        raise typer.Exit(code=1)

    _rebuild(repo)


def _resolve_concerns(repo: Path, workspace: Path, syms: list[str]) -> list[memory.Concern]:
    """Resolve each ``--concerns`` symbol to a :class:`Concern` with a stamped anchor (or exit)."""
    config = load_config(workspace / "config.yaml")
    concerns: list[memory.Concern] = []
    for sym in syms:
        if not sym.startswith("sym:"):
            typer.echo(f"--concerns must be a symbol (sym:<path>#<name>), got: {sym}", err=True)
            raise typer.Exit(code=1)
        anchor = symbol_content_hash(repo, sym, config)
        if anchor is None:
            typer.echo(f"Symbol not found in the current source: {sym}", err=True)
            raise typer.Exit(code=1)
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
        typer.echo(
            f"This looks like a near-duplicate of {hit[0]} (cosine {hit[1]:.2f}). "
            f"If you're changing your mind, `yigraf supersede {hit[0]} \"<new>\"`; "
            f"otherwise re-run with --new to capture it anyway.",
            err=True,
        )
        raise typer.Exit(code=1)


def _capture_memory(repo: Path, workspace: Path, *, statement: str, type_: str, why: str,
                    serves: list[str], concern_syms: list[str], rejected: str | None,
                    supersedes: list[str], promotable: bool, force_new: bool = False) -> memory.Memory:
    """Write a new memory artifact, then rebuild graph.json. Shared by remember/supersede/note-constraint."""
    if type_ not in memory.MEMORY_TYPES:
        typer.echo(f"--type must be one of {', '.join(memory.MEMORY_TYPES)} (got {type_}).", err=True)
        raise typer.Exit(code=1)

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
        typer.echo(f"No memory node with id {old_id} to supersede.", err=True)
        raise typer.Exit(code=1)
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
    semantic = embeddings.semantic_scores(repo, graph, config, query)  # {} ⇒ lexical-only (M8 / v0)
    result = retrieval.context(graph, query, config, family=family, budget_tokens=budget,
                               semantic_match=semantic)
    typer.echo(result.text, nl=False)
    typer.echo(f"[~{result.token_estimate} tokens · {result.nodes_rendered}/{result.nodes_total} nodes shown]")


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


@app.command(name="install-claude-hooks")
def install_claude_hooks_cmd(
    path: Path = typer.Argument(Path("."), help="Repo root to wire up for Claude Code."),
) -> None:
    """Register the PostToolUse + SessionStart hooks + skill so Claude Code surfaces intent & drift."""
    _require_workspace(path)
    result = install_claude_hooks(path)
    typer.echo(f"Wrote hooks → {result.settings_path}")
    typer.echo(f"Wrote skill → {result.skill_path}")
    typer.echo(f"Updated     → {result.agents_path}")


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


def _post_tool_use(data: dict) -> dict | None:
    if data.get("tool_name") not in ("Edit", "Write", "MultiEdit"):
        return None
    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("path")
    if not file_path:
        return None
    root = Path(data.get("cwd") or os.getcwd())
    built = _hook_graph(root)
    if built is None:
        return None
    try:
        rel = Path(file_path).resolve().relative_to(root.resolve())
    except ValueError:
        return None  # edited file is outside the repo
    if rel.suffix != ".py":
        return None
    graph, config = built
    result = retrieval.context_for_locus(graph, rel.as_posix(), config)
    if result is None:
        return None  # silent: nothing governs this locus and no drift
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": result.text}}


def _session_start(data: dict) -> dict | None:
    root = Path(data.get("cwd") or os.getcwd())
    built = _hook_graph(root)
    if built is None:
        return None
    graph, config = built
    result = retrieval.session_context(graph, config)
    if result is None:
        return None
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
