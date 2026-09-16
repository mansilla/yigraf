"""yigraf as an MCP server — the host-agnostic *pull* channel (int:mcp-server).

One adapter, every MCP host. Claude Code gets yigraf's value through push hooks, but Codex, Antigravity,
Cursor, Windsurf — and Claude Code too — all speak **MCP**, so exposing the graph as MCP tools reaches
them all with a single implementation. This is the pull channel: the agent *asks* for the slice (vs the
hook *pushing* it). Per the A-series eval pull is the weaker channel, but on a host with no lifecycle
hook (e.g. the Antigravity IDE) it's the only one — so it's how those hosts get yigraf at all.

The MCP SDK is a core dependency (not an extra): ``yigraf mcp`` is the universal pull channel every host
speaks, and ``yigraf install`` prints its host config by default. The SDK is pinned to 1.x
(``mcp<2``): 2.x renamed ``FastMCP`` and its stub module raises on import (feedback-v10 J#1).

Read tools (``context``, ``status``) run **in-process** so the structure graph + the embedding model
stay **warm** across calls in a session — a second ``context`` query doesn't re-pay the cold build/model
load. Write tools (``remember``/``link``/``note_constraint``/``supersede``/``supersede_intent``/``reaffirm``)
run the matching CLI verb in a **subprocess** (arg-list, no shell): writes are rare and rebuild the graph, and shelling out
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
    counters.apply_telemetry(graph, counters.load_telemetry(root))  # recency/popularity/upholds overlay (R1)
    counters.apply_maturity_verdict(graph, config)  # read-time settled verdict from upholds (mem:033)
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


def run_plan(repo: str | None, slug: str, title: str | None = None,
             tasks: list[str] | None = None, append_tasks: list[str] | None = None) -> str:
    args = [slug]
    if title:
        args += ["--title", title]
    return _run_cli("plan", args + _multi("--task", tasks) + _multi("--append-task", append_tasks), repo)


def run_close(repo: str | None, task: str, reopen: bool = False, force: bool = False) -> str:
    return _run_cli("close", [task] + (["--reopen"] if reopen else []) + (["--force"] if force else []), repo)


def run_tasks(repo: str | None, plan: str | None = None, state: str | None = None) -> str:
    flag = {"open": ["--open"], "done": ["--done"], "stale": ["--stale"]}.get(state or "", [])
    return _run_cli("tasks", ([plan] if plan else []) + flag, repo)


def run_link(repo: str | None, task: str, target: str) -> str:
    return _run_cli("link", [task, target], repo)


def run_unlink(repo: str | None, task: str, target: str) -> str:
    return _run_cli("unlink", [task, target], repo)


def run_show(repo: str | None, target: str) -> str:
    return _run_cli("show", [target], repo)


def run_reanchor(repo: str | None, target: str, old: str, new: str) -> str:
    return _run_cli("reanchor", [target, old, new], repo)


def run_amend(repo: str | None, target: str, statement: str | None = None, why: str | None = None,
              rejected: list[str] | None = None) -> str:
    """``amend`` over MCP. No ``why_file`` counterpart, deliberately: that flag exists to keep a shell
    from rewriting the reasoning, and there is no shell on this path — ``_run_cli`` passes an argv list
    to a subprocess, so the text arrives exactly as the model wrote it."""
    args = [target]
    if statement is not None:
        args += ["--statement", statement]
    if why is not None:
        args += ["--why", why]
    args += _multi("--rejected", rejected)
    return _run_cli("amend", args, repo)


def run_conflicts(repo: str | None) -> str:
    """`conflicts` takes its repo as a positional (drift's sibling), so it bypasses ``_run_cli``.

    A non-zero exit here means "conflicts stand" (the CI gate), not a failure — stdout IS the report,
    so it is returned either way.
    """
    root = str(_resolve_root(repo))
    cmd = [sys.executable, "-m", "yigraf", "conflicts", root]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=root)
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - environmental
        return f"yigraf conflicts could not run: {exc}"
    out = done.stdout.strip()
    return out or done.stderr.strip() or "(yigraf conflicts produced no output)"


def run_pin(repo: str | None, target: str, off: bool = False) -> str:
    return _run_cli("pin", [target] + (["--off"] if off else []), repo)


def _rejection_premise_args(valid_when: list[str] | None,
                            invalidated_when: list[str] | None) -> list[str]:
    """CLI args for a rejection's applicability premises (task 3), shared by every --rejected verb."""
    return (_multi("--rejected-valid-when", valid_when)
            + _multi("--rejected-invalidated-when", invalidated_when))


def run_remember(repo: str | None, statement: str, why: str = "", serves: list[str] | None = None,
                 concerns: list[str] | None = None, rejected: str | None = None,
                 type: str = "decision", grounding: str | None = None,
                 evidence: list[str] | None = None, rejected_valid_when: list[str] | None = None,
                 rejected_invalidated_when: list[str] | None = None,
                 governs: list[str] | None = None) -> str:
    args = [statement, "--type", type]
    if why:
        args += ["--why", why]
    args += _multi("--serves", serves) + _multi("--concerns", concerns) + _multi("--governs", governs)
    if rejected:
        args += ["--rejected", rejected]
    args += _rejection_premise_args(rejected_valid_when, rejected_invalidated_when)
    if grounding:
        args += ["--grounding", grounding]
    args += _multi("--evidence", evidence)
    return _run_cli("remember", args, repo)


def run_note_constraint(repo: str | None, rule: str, concerns: list[str] | None = None,
                        why: str = "", serves: list[str] | None = None,
                        rejected: str | None = None, grounding: str | None = None,
                        evidence: list[str] | None = None, rejected_valid_when: list[str] | None = None,
                        rejected_invalidated_when: list[str] | None = None,
                        governs: list[str] | None = None) -> str:
    args = [rule] + _multi("--concerns", concerns) + _multi("--governs", governs)
    if why:
        args += ["--why", why]
    args += _multi("--serves", serves)
    if rejected:
        args += ["--rejected", rejected]
    args += _rejection_premise_args(rejected_valid_when, rejected_invalidated_when)
    if grounding:
        args += ["--grounding", grounding]
    args += _multi("--evidence", evidence)
    return _run_cli("note-constraint", args, repo)


def run_propose(repo: str | None, statement: str, from_: str, concerns: list[str] | None = None,
                rejected: str | None = None, why: str = "", serves: list[str] | None = None,
                type: str | None = None, origin: str | None = None,
                grounding: str | None = None, evidence: list[str] | None = None,
                rejected_valid_when: list[str] | None = None,
                rejected_invalidated_when: list[str] | None = None,
                governs: list[str] | None = None) -> str:
    args = [statement, "--from", from_]
    if type:
        args += ["--type", type]
    args += (_multi("--concerns", concerns) + _multi("--governs", governs)
             + _multi("--serves", serves))
    if rejected:
        args += ["--rejected", rejected]
    args += _rejection_premise_args(rejected_valid_when, rejected_invalidated_when)
    if why:
        args += ["--why", why]
    if origin:
        args += ["--origin", origin]
    if grounding:
        args += ["--grounding", grounding]
    args += _multi("--evidence", evidence)
    return _run_cli("propose", args, repo)


def run_supersede(repo: str | None, old_id: str, statement: str, why: str = "",
                  serves: list[str] | None = None, concerns: list[str] | None = None,
                  rejected: str | None = None, type: str | None = None,
                  grounding: str | None = None, evidence: list[str] | None = None,
                  rejected_valid_when: list[str] | None = None,
                  rejected_invalidated_when: list[str] | None = None,
                  governs: list[str] | None = None) -> str:
    # Omitted rather than defaulted, so the CLI inherits the superseded node's type (feedback-v4 #12).
    args = [old_id, statement] + (["--type", type] if type else [])
    if why:
        args += ["--why", why]
    args += _multi("--serves", serves) + _multi("--concerns", concerns) + _multi("--governs", governs)
    if rejected:
        args += ["--rejected", rejected]
    args += _rejection_premise_args(rejected_valid_when, rejected_invalidated_when)
    if grounding:
        args += ["--grounding", grounding]
    args += _multi("--evidence", evidence)
    return _run_cli("supersede", args, repo)


def run_reaffirm(repo: str | None, target: str, concerns: list[str] | None = None,
                 grounding: str | None = None, evidence: list[str] | None = None) -> str:
    args = [target] + _multi("--concerns", concerns)
    if grounding:
        args += ["--grounding", grounding]
    args += _multi("--evidence", evidence)
    return _run_cli("reaffirm", args, repo)


def run_attest(repo: str | None, target: str) -> str:
    return _run_cli("attest", [target], repo)


def run_supersede_intent(repo: str | None, old_slug: str, new_slug: str, statement: str,
                         why: str = "", scenario: list[str] | None = None,
                         design: str | None = None, type: str = "requirement") -> str:
    args = [old_slug, new_slug, "-s", statement, "--type", type] + _multi("--scenario", scenario)
    if design:
        args += ["--design", design]
    if why:
        args += ["--why", why]
    return _run_cli("supersede-intent", args, repo)


def build_server(default_repo: str | None = None):
    """Construct the FastMCP server with yigraf's read + write tools. Imports the SDK lazily."""
    from mcp.server.fastmcp import FastMCP  # core dep; imported lazily to keep it off other CLI paths

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
        """A compact status line for the yigraf graph: counts (symbols/intents/tasks/decisions), every
        re-verify signal — `⚠ n drift`, `⚠ n stale`, `⚠ n rename`, `⚠ n conflict` — freshness (the
        gitignored materialized view vs source), and the semantic index size.

        The enumeration has to be complete, because this docstring is what a host reads to decide
        whether calling `status` answers its question: it returns `render_line()`, and a version that
        listed only the drift count read as exhaustive while three signals rode along unnamed
        (feedback-v6 F#1). "Up to date" means no drift, no stale AND no unsettled rename — settle the
        rename first, it is the only one that expires.

        Note: `sem N` counts only the embedded families — memory + intent nodes — not the whole graph
        (code is never embedded; retrieval-design §10). So `sem` staying flat while `sym` grows is
        expected, not a stale index: it tracks decisions/intents, which change far less than code."""
        return run_status(repo or default_repo)

    @server.tool()
    def plan(slug: str, title: str | None = None, tasks: list[str] | None = None,
             append_tasks: list[str] | None = None, repo: str | None = None) -> str:
        """Create a plan of tasks, or add tasks to a live one.

        The missing half of the task surface over MCP (feedback-v4 #1): this server exposed `link` and
        `unlink`, so an MCP-only host could anchor tasks it had no way to create — and none to close.

        Args:
            slug: the plan slug, e.g. "auth-hardening" (its id becomes plan:auth-hardening).
            title: one-line plan title. Required to CREATE; omit when appending.
            tasks: task descriptions for a NEW plan.
            append_tasks: task descriptions to add to an EXISTING plan — numbers continue past the
                highest and are never reused, so an id already on a link edge keeps its meaning.
        """
        return run_plan(repo or default_repo, slug, title, tasks, append_tasks)

    @server.tool()
    def close(task: str, reopen: bool = False, force: bool = False, repo: str | None = None) -> str:
        """Mark a task done (or, with reopen=True, not done) by writing its checkbox in the plan file.

        Call it right after `link`, as the second half of finishing a task. Closing refuses a task that
        implements nothing unless force=True: a completion with no anchor can never go STALE, so the
        drift-as-stale mechanism silently would not apply to it.

        Args:
            task: the task locator, e.g. "task:auth-hardening/3".
            reopen: re-open a done task instead of closing it (the change regressed the work).
            force: close despite no implements link — for a task that shipped no symbol. It RECORDS
                that choice in the plan, which is what stops the capture-gap warning firing on it;
                a later `link` retires the record.
        """
        return run_close(repo or default_repo, task, reopen, force)

    @server.tool()
    def tasks(plan: str | None = None, state: str | None = None, repo: str | None = None) -> str:
        """List tasks and their state — "what is outstanding", without depending on a query matching.

        Args:
            plan: only this plan's slug (default: every plan).
            state: "open" | "done" | "stale" (default: all). "stale" = done, but its implementing
                symbol drifted.
        """
        return run_tasks(repo or default_repo, plan, state)

    @server.tool()
    def link(task: str, target: str, repo: str | None = None) -> str:
        """Name what a finished task implements (or the intent it tracks), anchored to current content.

        Call this when you finish a task, to bind the task to the symbols that implement it — anchoring
        is what later surfaces drift when that code changes.

        Args:
            task: the task id, e.g. "task:auth/1".
            target: a symbol "sym:<path>#<name>", a file "file:<path>[:L<a>-L<b>]" or a markdown
                section "file:<path>#<section>" (implements), or an intent "int:<slug>" (tracks).
                Use file: for infra/glue with no code symbol.
        """
        return run_link(repo or default_repo, task, target)

    @server.tool()
    def unlink(task: str, target: str, repo: str | None = None) -> str:
        """Retire a task's declared edge — the way out of hard drift on a link that will never resolve.

        Call this when a task's implementing symbol is gone for good, or the declaration was wrong.
        A symbol that merely MOVED needs no unlink (yigraf re-anchors a move by content hash), and one
        that moved *and* changed wants `link` to the new locus — not unlink-then-link.

        Args:
            task: the task id, e.g. "task:auth/1".
            target: the edge to retire, exactly as the task declares it.
        """
        return run_unlink(repo or default_repo, task, target)

    @server.tool()
    def show(target: str, repo: str | None = None) -> str:
        """Read ONE node by id, in full — use this whenever yigraf has handed you an id.

        `context` searches by *meaning*; handed an id it returns whichever nodes sit nearest in
        embedding space, which reads like an answer and is not one. Every drift line, conflict line and
        session-start manifest entry pre-fills an id — this is the tool that reads it. Nothing is
        truncated: the whole `why`, the rejected alternatives, every anchor and its current drift state.

        Args:
            target: a node id or unique prefix — "mem:<id>", "int:<slug>", "task:<plan>/<n>",
                "sym:<path>#<name>", or "file:<path>". A bare memory hash works too.
        """
        return run_show(repo or default_repo, target)

    @server.tool()
    def reanchor(target: str, old: str, new: str, repo: str | None = None) -> str:
        """Move ONE anchor of a memory to the locus its subject moved to — a locus repair, never a
        mind-change.

        Use when a belief still holds but the code it governs (or the evidence grounding it) lives
        somewhere else now, or the anchor was mis-declared at capture. No supersedes edge is written:
        the claim, its why, and its history are untouched. An anchor that never belonged → `unlink`;
        a mind-change → `supersede`; an unchanged locus that drifted → `reaffirm`.

        Args:
            target: the memory id, e.g. "mem:1678ce10ad2fcc15".
            old: the anchor to move, exactly as the node carries it.
            new: where the subject now lives — "sym:<path>#<name>", "file:<path>[:L<a>-L<b>]" or
                "file:<path>#<section>".
        """
        return run_reanchor(repo or default_repo, target, old, new)

    @server.tool()
    def amend(target: str, statement: str | None = None, why: str | None = None,
              rejected: list[str] | None = None, repo: str | None = None) -> str:
        """Repair a botched RECORD of a memory — a garbled why, a typo in the claim — filing no
        mind-change.

        For when the belief is right and what was WRITTEN about it is wrong. `reanchor`'s sibling: no
        supersedes edge, and the anchors, grounding, maturity and history are untouched. Your mind
        changed → `supersede` instead, which keeps both readings; the locus moved → `reanchor`.

        The id follows the text, because a memory id is a hash of its statement/why/rejected — so the
        reply names a NEW id for the same belief. It refuses (with the reason) on a node another
        artifact names, or one already pushed to a shared log, where the honest verb is `supersede`.

        Args:
            target: the memory id to repair, e.g. "mem:1678ce10ad2fcc15".
            statement: replacement one-line claim; omit to keep it.
            why: replacement reasoning; omit to keep it.
            rejected: replacement ruled-out alternatives (joined with " || "); omit to keep them.
        """
        return run_amend(repo or default_repo, target, statement, why, rejected)

    @server.tool()
    def conflicts(repo: str | None = None) -> str:
        """List open knowledge-conflicts — the pairs `status`'s `⚠ n conflict` counts.

        Each finding names the two belief ids, their shared anchor, how close they read, which side
        provenance prefers, and the verbs that resolve it (reconcile = compatible, supersede = one
        side won, dispute = nominate for a principal). The count is never a dead end: this is the
        listing behind it.
        """
        return run_conflicts(repo or default_repo)

    @server.tool()
    def pin(target: str, off: bool = False, repo: str | None = None) -> str:
        """Mark a decision for unconditional injection at every session start.

        For the handful of rules that are load-bearing on EVERY task — the ones that, by construction,
        never win a relevance ranking because they resemble no particular topic. Keep the set small: a
        bounded budget drops the lowest-ranked pins, and a session-start block that grows without limit
        stops being read. Everything else stays reachable through `context` and the titles manifest.

        Args:
            target: the memory id, e.g. "mem:1678ce10ad2fcc15".
            off: unpin instead, returning it to relevance-ranked retrieval.
        """
        return run_pin(repo or default_repo, target, off)

    @server.tool()
    def remember(statement: str, why: str = "", serves: list[str] | None = None,
                 concerns: list[str] | None = None, rejected: str | None = None,
                 type: str = "decision", grounding: str | None = None,
                 evidence: list[str] | None = None, rejected_valid_when: list[str] | None = None,
                 rejected_invalidated_when: list[str] | None = None, governs: list[str] | None = None,
                 repo: str | None = None) -> str:
        """Persist a non-obvious decision/rationale as a durable memory node — the *why* a reset loses.

        Capture at a conclusion (a chosen approach, a worked-around constraint), not mid-thinking. A
        `concerns` symbol is anchored, so editing that code later re-surfaces "re-verify this decision".

        Args:
            statement: the decision in one line.
            why: the reasoning — what a context reset would otherwise lose.
            serves: intent/plan ids this serves, e.g. ["int:auth"].
            concerns: the loci this governs, e.g. ["sym:auth/session.py#refresh", "file:Dockerfile",
                "file:cfg.yaml:L10-L40", "file:docs/guide.md#drift"] (anchored; file: for infra/glue).
                For part of a markdown doc use "#<section>", not a line range: a section is addressed
                by heading, so it survives a rewrap and an insertion above it and re-anchors on a
                rename, while a range is positional and slides onto other text.
            rejected: the rejected alternative + why not (the most perishable content).
            type: one of decision|constraint|learning (default decision).
            grounding: how the belief is grounded — inferred|docs|empirical (default inferred). Use
                empirical when a live observation (a spike/test/prod signal) confirmed it; inferred
                beliefs surface as re-verify TODOs in `context`.
            evidence: what grounds the belief — REQUIRED for grounding=empirical. A locus (e.g.
                ["sym:tests/test_x.py#test_case", "file:path"]) is drift-checked, so the evidence
                changing later re-surfaces the belief as unearned; an opaque ref ("commit:abc", a URL)
                is recorded but not drift-checked.
            rejected_valid_when: premises the rejection depends on (int:/mem:/sym:/file: locators). The
                rejection surfaces ONLY while every one still holds — so a stale rejection stops
                mis-steering you once its reason lapses.
            rejected_invalidated_when: conditions that WITHDRAW the rejection once true (same locator
                forms), e.g. rejected "no Redis in deploy" + rejected_invalidated_when
                ["file:infra/redis.tf"] — the rejection vanishes the moment that file appears.
            governs: loci whose *use* this belief governs rather than their contents, e.g.
                ["file:docs/status.md"] for "status.md holds ONLY status" (a "#<section>" works too;
                a line range does not — a policy is about a named locus). Surfaces at the edit hook
                exactly like `concerns` but carries no content hash, so it NEVER drifts — use it when
                a content anchor would demand a rubber-stamp reaffirm on every edit that obeys the
                policy. The locus must already exist.
        """
        return run_remember(repo or default_repo, statement, why, serves, concerns, rejected, type,
                            grounding, evidence, rejected_valid_when, rejected_invalidated_when,
                            governs)

    @server.tool()
    def note_constraint(rule: str, concerns: list[str] | None = None, why: str = "",
                        serves: list[str] | None = None, rejected: str | None = None,
                        grounding: str | None = None, evidence: list[str] | None = None,
                        rejected_valid_when: list[str] | None = None,
                        rejected_invalidated_when: list[str] | None = None,
                        governs: list[str] | None = None, repo: str | None = None) -> str:
        """Capture a constraint/rule governing code (flagged as a candidate to promote to a check).

        Args:
            rule: the rule, in one line.
            concerns: symbols it governs, e.g. ["sym:path.py#fn"] (anchored).
            why: why the rule exists.
            serves: intent/plan ids it serves.
            rejected: the ruled-out alternative + why (a constraint often exists *because* one was).
            grounding: inferred|docs|empirical (default inferred) — see `remember`.
            evidence: what grounds it — REQUIRED for grounding=empirical; see `remember`.
            rejected_valid_when / rejected_invalidated_when: applicability premises for the rejection
                (int:/mem:/sym:/file: locators) — see `remember`.
            governs: loci whose *use* the rule governs rather than their contents — never drifts; see
                `remember`. The natural anchor for a house rule about a document.
        """
        return run_note_constraint(repo or default_repo, rule, concerns, why, serves, rejected,
                                   grounding, evidence, rejected_valid_when,
                                   rejected_invalidated_when, governs)

    @server.tool()
    def propose(statement: str, from_: str, concerns: list[str] | None = None,
                rejected: str | None = None, why: str = "", serves: list[str] | None = None,
                type: str | None = None, origin: str | None = None, grounding: str | None = None,
                evidence: list[str] | None = None, rejected_valid_when: list[str] | None = None,
                rejected_invalidated_when: list[str] | None = None,
                governs: list[str] | None = None, repo: str | None = None) -> str:
        """Land a distilled CANDIDATE memory in quarantine (the `proposed` tier) — near-zero weight.

        Two callers: (1) a code-/security-review finding you confirmed and chose to keep, and (2) the
        knowledge miner distilling durable reasoning from commit rationale, PR discussion, or repo docs.
        A proposed node does NOT pollute a topic query, but — anchored via `concerns` to a locus — it
        re-surfaces at the edit hook when that code is next touched; a real encounter there confirms it
        up to `working`. Over-proposing is safe: an un-encountered candidate expires. Distilling the
        finding into one line is YOUR job; this only persists it with the quarantine provenance.

        Args:
            statement: the candidate belief in one line (a review anti-pattern, or a distilled decision).
            from_: where it came from — "review" or "mined" (both land proposed). Sent as `--from`.
            concerns: the locus it governs, e.g. ["sym:auth/session.py#refresh"] (anchored — this is
                what re-surfaces it at the edit hook). Strongly recommended for a review finding.
            rejected: the anti-pattern (review) / rejected alternative (mined) it warns against.
            why: the reasoning behind the candidate.
            serves: intent/plan ids it serves.
            type: decision|constraint (default: constraint for review, decision for mined).
            origin: free-text provenance detail for the audit trail (e.g. "security-review", "commit abc").
            grounding: inferred|docs|empirical (default inferred) — see `remember`.
            evidence: what grounds it — REQUIRED for grounding=empirical; see `remember`.
            rejected_valid_when / rejected_invalidated_when: applicability premises for the anti-pattern
                (int:/mem:/sym:/file: locators) — see `remember`.
            governs: loci whose *use* the candidate governs rather than their contents — never drifts;
                see `remember`.
        """
        return run_propose(repo or default_repo, statement, from_, concerns, rejected, why, serves,
                          type, origin, grounding, evidence, rejected_valid_when,
                          rejected_invalidated_when, governs)

    @server.tool()
    def supersede(old_id: str, statement: str, why: str = "", serves: list[str] | None = None,
                  concerns: list[str] | None = None, rejected: str | None = None,
                  type: str | None = None, grounding: str | None = None,
                  evidence: list[str] | None = None, rejected_valid_when: list[str] | None = None,
                  rejected_invalidated_when: list[str] | None = None,
                  governs: list[str] | None = None, repo: str | None = None) -> str:
        """Record a mind-change: a new memory node that supersedes an old one (never edit in place).

        The successor INHERITS the superseded node's concerns/governs/serves/type and its `promotable`
        mark unless you re-aim them (each arg overrides its own kind) — a correction that lands with no
        anchor never resurfaces at the edit hook on the symbol it warns about, and a correction to a
        constraint is still a constraint.

        Args:
            old_id: the memory being superseded, e.g. "mem:007".
            statement: the new decision in one line.
            why: what changed.
            serves/concerns/rejected/type/grounding/evidence: as for `remember`; omit to inherit.
            rejected_valid_when / rejected_invalidated_when: applicability premises for the rejection
                (int:/mem:/sym:/file: locators) — see `remember`.
            governs: policy loci that never drift — see `remember`; omit to inherit.
        """
        return run_supersede(repo or default_repo, old_id, statement, why, serves, concerns, rejected,
                            type, grounding, evidence, rejected_valid_when,
                            rejected_invalidated_when, governs)

    @server.tool()
    def reaffirm(target: str, concerns: list[str] | None = None, grounding: str | None = None,
                 evidence: list[str] | None = None, repo: str | None = None) -> str:
        """Re-verify a decision still holds and re-anchor its `concerns` to current code, clearing drift.

        The honest counterpart to `supersede`: when code a memory governs is edited, drift asks you to
        re-verify the decision. If it still holds (no mind-change), call this to re-stamp the anchor and
        clear the drift — don't `supersede` (that records a change that didn't happen) or re-`remember`
        (that duplicates).

        Args:
            target: a memory id "mem:022" (reaffirm its concerns), OR a locus "sym:<path>#<name>" /
                "file:<path>" (reaffirm EVERY memory concerning that locus — the scoped batch for an
                edit-heavy session, after you verified that one locus). No blanket "clear all" exists.
            concerns: with a mem: id, re-anchor only these loci (default: all the node's concerns).
            grounding: with a mem: id, upgrade its grounding in place (e.g. inferred→empirical when a
                live spike just confirmed the decision). Reaching empirical REQUIRES naming `evidence`.
            evidence: with a mem: id, name/re-anchor the observation grounding it — required to reach
                empirical. A locus already grounding it is re-anchored (clearing grounds-drift after you
                re-verified the observation); a new one is added. Never re-stamped on a bare reaffirm.
        """
        return run_reaffirm(repo or default_repo, target, concerns, grounding, evidence)

    @server.tool()
    def attest(target: str, repo: str | None = None) -> str:
        """Record the principal's endorsement: mark a decision or intent HUMAN-attested (a trust floor).

        Call this ONLY after the principal has actually chosen — capturing a preference-fork you elicited
        via the host's question UI, or endorsing a decision you flagged for ack. Attesting a memory that
        pending-supersedes a human-attested node APPLIES the held supersede (the principal accepted it).
        The trust floor depends on honesty: mark human only when the human genuinely decided.

        Args:
            target: a memory id "mem:022" or an intent "int:<slug>".
        """
        return run_attest(repo or default_repo, target)

    @server.tool()
    def supersede_intent(old_slug: str, new_slug: str, statement: str, why: str = "",
                         scenario: list[str] | None = None, design: str | None = None,
                         type: str = "requirement", repo: str | None = None) -> str:
        """Reverse an intent: create the replacement, archive the old, write a traversable int→int edge.

        Use when an intent's premise turned out false — NOT for a memory mind-change (that's `supersede`).
        The replacement is created active with a `supersedes` edge to the old (so `context` can traverse
        from it back to what it replaced), the old is archived, and `--why` is captured as a memory
        serving the new intent. A changed contract is a reversal — don't hand-edit the old intent.

        Args:
            old_slug: slug of the intent being reversed (its int:<slug> is archived).
            new_slug: slug for the replacement intent.
            statement: the replacement's one-line SHALL/MUST contract.
            why: why the premise changed (captured as a memory serving the new intent).
            scenario: optional Given/When/Then examples.
            design: optional approach / the "how".
            type: requirement|goal|capability (default requirement).
        """
        return run_supersede_intent(repo or default_repo, old_slug, new_slug, statement, why,
                                    scenario, design, type)

    return server


def run(repo: str | os.PathLike | None = None) -> int:
    """Run the stdio MCP server, blocking until the client disconnects. Returns a process exit code."""
    default_repo = _resolve_root(repo)
    server = build_server(str(default_repo))
    os.environ.setdefault("YIGRAF_REPO", str(default_repo))  # so tool calls omitting repo resolve here
    server.run()  # stdio transport by default
    return 0
