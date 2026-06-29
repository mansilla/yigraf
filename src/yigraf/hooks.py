"""Git hook installation: keep ``graph.json`` synced to HEAD at the commit boundary (R5, M2b).

``yigraf install-hooks`` writes a ``post-commit`` hook that rebuilds the graph after each commit —
the BUILD-PLAN's "detached AST rebuild." It is **fail-open** (never blocks or fails a commit) and
bakes in the absolute interpreter path + repo root, so it runs even when ``PATH`` lacks the venv.

Anchors themselves are stamped at ``yigraf link`` time, not here (docs/m2-notes.md §4): the hook
only refreshes the projection. A symbol edited after linking, without a re-link, is left to surface
as drift — the hook does not silently re-anchor it.
"""
from __future__ import annotations

import json
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: Marks a hook as yigraf-authored, so re-install overwrites ours but never a user's own hook.
_MARKER = "# yigraf-managed post-commit hook"

#: The git merge-driver name keyed in .gitattributes (``graph.json merge=yigraf-graph``).
_MERGE_DRIVER = "yigraf-graph"

#: Markers bounding the always-on block yigraf maintains in AGENTS.md (idempotent replace).
_AGENTS_START = "<!-- yigraf:start -->"
_AGENTS_END = "<!-- yigraf:end -->"


@dataclass
class HookResult:
    path: Path
    installed: bool  # False when an unmanaged hook is already present (left untouched)
    merge_driver: bool = False  # whether the graph.json union-merge driver was registered (M9)


def _hook_body(python: str, root: Path) -> str:
    return (
        "#!/bin/sh\n"
        f"{_MARKER}\n"
        "# Rebuild yigraf/graph.json to match HEAD. Fail-open: never block a commit.\n"
        f'"{python}" -m yigraf build "{root}" >/dev/null 2>&1 || true\n'
    )


def git_dir(root: Path) -> Path | None:
    """The repo's ``.git`` directory, or ``None`` if ``root`` isn't a (plain) git repo.

    Handles the ``.git``-as-file indirection that worktrees/submodules use (``gitdir: <path>``).
    """
    dot_git = Path(root) / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        line = dot_git.read_text(encoding="utf-8").strip()
        if line.startswith("gitdir:"):
            target = (Path(root) / line[len("gitdir:") :].strip()).resolve()
            return target if target.is_dir() else None
    return None


def install_post_commit_hook(root: Path) -> HookResult:
    """Install (or refresh) the yigraf ``post-commit`` hook. Leaves a foreign hook untouched."""
    root = Path(root).resolve()
    gd = git_dir(root)
    if gd is None:
        raise FileNotFoundError(f"{root} is not a git repository (no .git)")

    hooks_dir = gd / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "post-commit"

    if hook_path.exists() and _MARKER not in hook_path.read_text(encoding="utf-8"):
        return HookResult(path=hook_path, installed=False)

    hook_path.write_text(_hook_body(sys.executable, root), encoding="utf-8")
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    merge_driver = register_merge_driver(root)
    return HookResult(path=hook_path, installed=True, merge_driver=merge_driver)


def register_merge_driver(root: Path) -> bool:
    """Register the ``graph.json`` union-merge driver in ``.git/config`` (DESIGN R1).

    ``.gitattributes`` already routes ``graph.json`` to ``merge=yigraf-graph``; this points that name
    at ``yigraf graph-merge`` so a merge/rebase unions the two sides instead of throwing a line-level
    JSON conflict. v0 ``graph.json`` is recomputable, so the post-merge build re-projects it exactly —
    the driver just keeps the merge clean in the meantime. Bakes in the absolute interpreter (like the
    hook) so it runs without the venv on ``PATH``. Fail-open: returns ``False`` if ``git config`` is
    unavailable rather than aborting the install.
    """
    driver = f'"{sys.executable}" -m yigraf graph-merge %O %A %B'
    try:
        for key, value in (
            (f"merge.{_MERGE_DRIVER}.name", "yigraf graph union-merge driver"),
            (f"merge.{_MERGE_DRIVER}.driver", driver),
        ):
            done = subprocess.run(["git", "-C", str(root), "config", key, value],
                                  capture_output=True, timeout=5)
            if done.returncode != 0:
                return False
    except (OSError, subprocess.SubprocessError):
        return False
    return True


# --------------------------------------------------------------------------------------------------
# Claude Code hooks: PostToolUse (drift/intent surfacing) + SessionStart (re-inject) — R8
# --------------------------------------------------------------------------------------------------

SKILL_MD = """\
---
name: yigraf
description: Use when implementing or changing code in this repo to keep intent, code, and the reasoning behind it in sync. Before starting work, run `yigraf context "<topic>"` to surface governing intents, plans, prior decisions, and drift. After finishing a task, run `yigraf link <task> <symbol>` to name the symbols that implement it, and `yigraf remember` the non-obvious choices you made.
---

# yigraf — the intent↔code spine

This repo is indexed by **yigraf**: one graph over code structure, intents (specs), plans, and the
**memory** of why the code is the way it is — with enforceable links (`implements`, `concerns`)
whose drift is surfaced when code and the thing that governs it diverge. A few rituals keep it
useful — the hooks are a safety net, not a substitute.

## 0. Orient before you touch code (always)
Run `yigraf context "<what you're about to work on>"`. **This is the one command you need to read the
graph** — the governing requirement(s), the implementing symbols (signature by default, full source
when configured), the open tasks, the prior **decisions and their *why***, and any **drift** all come
back through it, as a token-cheap map. Don't reach for a separate query or drift tool. If a spec
already covers your change, refine it; don't duplicate. If a decision already settled the question,
follow it (or `supersede` it on purpose).

## 1. Link when a task is done (the seam)
When you finish a task, name the symbols that implement it:
`yigraf link task:<plan>/<n> sym:<path>#<name>` — this anchors the link to the symbol's current
content. Linking once per completed task (not per edit) is enough.

## 2. Capture the *why* (decisions & constraints)
When you make a non-obvious choice — picked an approach over a named alternative, set a constraint,
worked around something — persist the reasoning that `/clear` would otherwise lose. One line of why
plus the rejected option is enough; capture at the *conclusion*, not mid-thinking.
- `yigraf remember "<the decision, one line>" --type decision --why "<reasoning>" --serves int:<slug> --concerns sym:<path>#<name> [--rejected "<the alternative + why not>"]`
- A correction or rule → `yigraf note-constraint "<rule>" --concerns sym:<path>#<name>` (flagged as a
  candidate to promote into an enforced check).
- Changed your mind? Never edit a decision in place — `yigraf supersede mem:<id> "<new decision>" --why "<what changed>"`. The old one stays as a rejected alternative.

A `--concerns` link is **anchored** like `implements`: edit that code later and yigraf surfaces a
"re-verify this decision still holds" reconcile. That's the payoff — the next agent to touch the code
sees the decision and its rationale without reading the history.

## 3. Author specs as you plan
- `yigraf intent <slug> -s "The system SHALL …" --scenario "Given …, When …, Then …" [--design "…"]`
- `yigraf plan <slug> -t "<title>" --task "<description>"` then `yigraf link task:<plan>/1 int:<slug>`
  to track the intent.

## 4. Drift means re-verify
You don't poll for drift — `yigraf context` and the edit hook surface it for you: soft drift (a linked
symbol's body changed) or hard drift (it's gone), for both `implements` (task→code) and `concerns`
(decision→code) links. A pure rename auto-re-anchors. When drift surfaces, re-verify the code still
satisfies the spec/decision, then `yigraf link` (or re-`remember` / `supersede` the decision) to
re-anchor. (`yigraf drift` exits non-zero on drift — that's the commit/CI gate, not something you poll.)
"""

_AGENTS_BLOCK = f"""{_AGENTS_START}
## yigraf
This repo uses **yigraf** (a graph over code, intent, plan, and the *why*). Before changing code, run
`yigraf context "<topic>"` — the one read command: it surfaces governing intents, prior decisions, and
any drift to re-verify. After finishing a task, run `yigraf link task:<plan>/<n> sym:<path>#<name>`, and
`yigraf remember` the non-obvious choices (with `--why` and `--concerns <sym>`).
{_AGENTS_END}"""

#: Self-contained ignore so the per-machine hook wiring never reaches a commit (see install docstring).
_CLAUDE_GITIGNORE = """\
# Machine-local Claude Code settings written by `yigraf install-claude-hooks`. The hook commands bake
# in this clone's absolute interpreter path, so they're per-machine — kept out of git. A teammate
# inherits the committed SKILL.md + AGENTS.md block and just re-runs `yigraf install-claude-hooks`.
settings.local.json
"""


@dataclass
class ClaudeHookResult:
    settings_path: Path
    skill_path: Path
    agents_path: Path
    hooks_changed: bool
    gitignore_path: Path | None = None  # .claude/.gitignore keeping settings.local.json out of git
    statusline: str = "unchanged"  # "set" | "refreshed" | "kept-foreign" | "unchanged"


def _ensure_claude_gitignore(claude: Path) -> Path:
    """Ensure ``.claude/.gitignore`` ignores ``settings.local.json`` (idempotent, non-clobbering)."""
    path = claude / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if "settings.local.json" not in {ln.strip() for ln in existing.splitlines()}:
        prefix = existing.rstrip() + "\n\n" if existing.strip() else ""
        path.write_text(prefix + _CLAUDE_GITIGNORE, encoding="utf-8")
    return path


def _ensure_hook(hooks: dict, event: str, matcher: str, command: str, verb: str) -> bool:
    """Idempotently register ``command`` under ``event``; refresh it if the interpreter path moved."""
    entries = hooks.setdefault(event, [])
    for entry in entries:
        for h in entry.get("hooks", []):
            if verb in h.get("command", ""):
                if h["command"] != command:
                    h["command"] = command
                    return True
                return False
    entries.append({"matcher": matcher, "hooks": [{"type": "command", "command": command, "timeout": 15}]})
    return True


def _ensure_statusline(settings: dict, command: str) -> str:
    """Point Claude Code's ``statusLine`` at ``yigraf status --color`` — idempotent, non-clobbering.

    The hooks speak into the *agent's* context; the statusline is the *human's* ambient surface, so
    wiring it is what makes the ``[Yigraf]`` brand + graph health actually visible on every refresh
    (int:status-surface). A statusLine is a single object (not a list), so we only set it when it's
    absent or already ours (refreshing this clone's interpreter path); a *foreign* statusLine is left
    untouched — clobbering a user's own status bar would be hostile (mirrors the non-clobbering rule
    the hook merge already follows). Returns the action taken for the install summary.
    """
    existing = settings.get("statusLine")
    if isinstance(existing, dict) and "yigraf status" not in existing.get("command", ""):
        return "kept-foreign"
    if isinstance(existing, dict) and existing.get("command") == command:
        return "unchanged"
    refreshed = isinstance(existing, dict)
    settings["statusLine"] = {"type": "command", "command": command}
    return "refreshed" if refreshed else "set"


def install_claude_hooks(root: Path) -> ClaudeHookResult:
    """Register the PostToolUse + SessionStart hooks in .claude/settings.local.json + lay the skill.

    The hook commands bake in this clone's **absolute interpreter** so they run regardless of ``PATH``
    — which makes them machine-specific, so they go in **``settings.local.json``** (Claude Code's
    per-machine settings), never the committed ``settings.json``. A self-contained ``.claude/.gitignore``
    keeps that file out of git; the shareable ``SKILL.md`` + ``AGENTS.md`` block ARE committed, so a
    teammate inherits the skill and just re-runs this command to wire their own paths. Idempotent and
    non-clobbering: merges into any existing *local* settings, only touching the two yigraf hook entries
    (keyed by their ``hook <verb>`` command), and never reads or rewrites the committed ``settings.json``.
    The hook reads the repo root from the event's ``cwd``.
    """
    root = Path(root).resolve()
    claude = root / ".claude"
    settings_path = claude / "settings.local.json"

    settings: dict = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError:
            settings = {}
    hooks = settings.setdefault("hooks", {})

    py = sys.executable
    changed = _ensure_hook(hooks, "PostToolUse", "Edit|Write",
                           f'"{py}" -m yigraf hook post-tool-use', "hook post-tool-use")
    changed |= _ensure_hook(hooks, "SessionStart", "startup|resume|clear|compact",
                            f'"{py}" -m yigraf hook session-start', "hook session-start")
    statusline = _ensure_statusline(settings, f'"{py}" -m yigraf status --color')
    changed |= statusline in ("set", "refreshed")

    claude.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    gitignore_path = _ensure_claude_gitignore(claude)

    skill_path = claude / "skills" / "yigraf" / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(SKILL_MD, encoding="utf-8")

    agents_path = _write_agents_block(root / "AGENTS.md")
    return ClaudeHookResult(settings_path=settings_path, skill_path=skill_path,
                            agents_path=agents_path, hooks_changed=changed,
                            gitignore_path=gitignore_path, statusline=statusline)


def _write_agents_block(agents_path: Path) -> Path:
    """Insert or refresh the marked yigraf block in AGENTS.md without disturbing the rest."""
    existing = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    if _AGENTS_START in existing and _AGENTS_END in existing:
        head, _, rest = existing.partition(_AGENTS_START)
        _, _, tail = rest.partition(_AGENTS_END)
        updated = head + _AGENTS_BLOCK + tail
    else:
        updated = (existing.rstrip() + "\n\n" if existing.strip() else "") + _AGENTS_BLOCK + "\n"
    agents_path.write_text(updated, encoding="utf-8")
    return agents_path


def _ensure_gitignore(directory: Path, ignore_line: str, comment: str) -> Path:
    """Idempotently add ``ignore_line`` to ``directory/.gitignore`` (non-clobbering)."""
    path = directory / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if ignore_line not in {ln.strip() for ln in existing.splitlines()}:
        prefix = existing.rstrip() + "\n\n" if existing.strip() else ""
        path.write_text(f"{prefix}# {comment}\n{ignore_line}\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------------------------------
# Codex CLI hooks (M-multi): SessionStart re-inject + best-effort PostToolUse — the SAME handlers as
# Claude Code (Codex's hook contract mirrors it: snake_case tool_name/tool_input/cwd in, and
# hookSpecificOutput.additionalContext out). So the only host-specific piece is *where* the wiring
# lives: Codex reads project-local `.codex/hooks.json` (a trusted project) instead of Claude's
# `.claude/settings.local.json`. AGENTS.md (the shared committed block) already instructs Codex.
# --------------------------------------------------------------------------------------------------

#: Codex edits via the apply_patch family; the matcher gates PostToolUse to edit tools (the handler
#: also gates, so a mismatch just stays silent — fail-open). SessionStart is the guaranteed win.
_CODEX_EDIT_MATCHER = "apply_patch|ApplyPatch|str_replace_editor|write_file|create_file"


@dataclass
class CodexHookResult:
    hooks_path: Path
    agents_path: Path
    hooks_changed: bool
    gitignore_path: Path | None = None


def install_codex_hooks(root: Path) -> CodexHookResult:
    """Register yigraf's SessionStart + PostToolUse hooks in ``.codex/hooks.json`` + the AGENTS block.

    Reuses the exact ``yigraf hook session-start`` / ``post-tool-use`` handlers — Codex's hook JSON
    mirrors Claude Code's (same input fields, same ``additionalContext`` output), so only the install
    target differs. Like the Claude installer, the command bakes in this clone's absolute interpreter
    (PATH-independent), making ``hooks.json`` machine-specific — so a ``.codex/.gitignore`` keeps it out
    of git and a teammate re-runs this command. Idempotent + non-clobbering (merges, keyed by verb).
    ``SessionStart`` is the reliable re-injection; ``PostToolUse`` is best-effort (verify the edit-tool
    name on your Codex version — see ``mem:019``).
    """
    root = Path(root).resolve()
    codex = root / ".codex"
    hooks_path = codex / "hooks.json"

    data: dict = {}
    if hooks_path.exists():
        try:
            data = json.loads(hooks_path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError:
            data = {}
    hooks = data.setdefault("hooks", {})

    py = sys.executable
    changed = _ensure_hook(hooks, "SessionStart", "startup|resume|clear|compact",
                           f'"{py}" -m yigraf hook session-start', "hook session-start")
    changed |= _ensure_hook(hooks, "PostToolUse", _CODEX_EDIT_MATCHER,
                            f'"{py}" -m yigraf hook post-tool-use', "hook post-tool-use")

    codex.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    gitignore_path = _ensure_gitignore(
        codex, "hooks.json",
        "Machine-local Codex hooks written by `yigraf install-codex-hooks` (absolute interpreter path).")
    agents_path = _write_agents_block(root / "AGENTS.md")
    return CodexHookResult(hooks_path=hooks_path, agents_path=agents_path,
                           hooks_changed=changed, gitignore_path=gitignore_path)


# --------------------------------------------------------------------------------------------------
# Antigravity (M-multi): there is NO hook system in the IDE (verified — Google staff), so the only
# push-like surface is an *always-on rule* the agent reads, pointing it at the yigraf MCP tools. We
# write `.agents/rules/yigraf.md` (+ the AGENTS block) and hand back the MCP-config snippet for the
# user to add via the in-app MCP editor — we don't auto-write the global `mcp_config.json` (its path
# is version-specific: `~/.gemini/antigravity/` vs `~/.gemini/config/`).
# --------------------------------------------------------------------------------------------------

_ANTIGRAVITY_RULE = """\
# yigraf (via MCP)

This repo is indexed by **yigraf** — one graph over code, intent, plan, and the *why* (decisions,
constraints, rejected alternatives). yigraf is wired as an MCP server; use its tools:

- **Before** changing code, call the `context` tool with your topic — it returns the governing
  intents, the active plan, implementing signatures, prior decisions and their *why*, and any drift to
  re-verify. Don't re-derive intent or re-read what the graph already encodes.
- **After** finishing a task, call `link` to name the symbols it implements, and `remember` the
  non-obvious decisions (with `why` and `concerns`). Changed your mind? `supersede` the old decision.
  A correction/rule → `note_constraint`.
- `status` gives a one-line health check (scale, drift, freshness).

If a spec already governs your change, follow it; if a decision already settled the question, follow
it (or `supersede` it on purpose).
"""


@dataclass
class AntigravityResult:
    rule_path: Path
    agents_path: Path
    mcp_command: str  # the command a host launches for the MCP server (for the printed config snippet)


def install_antigravity(root: Path) -> AntigravityResult:
    """Wire yigraf for the Antigravity IDE (which has no hooks): an always-on rule + the AGENTS block.

    Writes ``.agents/rules/yigraf.md`` (model reads it every session) and refreshes the AGENTS.md
    block — both committed/shareable. The MCP server is the data channel; the caller prints the
    ``mcp_config.json`` snippet for the user to add via Antigravity's MCP editor (its global config
    path is version-specific, so we don't auto-write it).
    """
    root = Path(root).resolve()
    rules_dir = root / ".agents" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    rule_path = rules_dir / "yigraf.md"
    rule_path.write_text(_ANTIGRAVITY_RULE, encoding="utf-8")
    agents_path = _write_agents_block(root / "AGENTS.md")
    mcp_command = f'"{sys.executable}" -m yigraf mcp --repo "{root}"'
    return AntigravityResult(rule_path=rule_path, agents_path=agents_path, mcp_command=mcp_command)


# --------------------------------------------------------------------------------------------------
# Host auto-detection (M-multi): which natively-supported host(s) are present, so `yigraf install`
# can wire the right channel without asking — falling back to MCP for anything else.
# --------------------------------------------------------------------------------------------------

#: A host name → the marker dirs that signal it (repo-local "configured here" OR home "installed here").
_HOST_MARKERS = {
    "claude": (".claude",),       # home: ~/.claude
    "codex": (".codex",),         # home: ~/.codex
    "antigravity": (".agents",),  # home: ~/.gemini, ~/.antigravity
}
_HOST_HOME_MARKERS = {
    "claude": (".claude",),
    "codex": (".codex",),
    "antigravity": (".gemini", ".antigravity"),
}


def detect_hosts(root: Path, home: Path | None = None) -> list[str]:
    """The natively-supported hosts present, by config markers — repo-local or in the home dir.

    Repo markers mean "configured for this repo"; home markers mean "installed on this machine". Either
    counts. ``home`` is injectable for testing. Returns names in install order (claude, codex,
    antigravity); empty ⇒ `yigraf install` falls back to the universal MCP server.
    """
    root = Path(root)
    home = Path(home) if home is not None else Path.home()
    found = []
    for host in ("claude", "codex", "antigravity"):
        repo_hit = any((root / m).exists() for m in _HOST_MARKERS[host])
        home_hit = any((home / m).exists() for m in _HOST_HOME_MARKERS[host])
        if repo_hit or home_hit:
            found.append(host)
    return found
