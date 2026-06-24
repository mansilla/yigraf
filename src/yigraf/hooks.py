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
import sys
from dataclasses import dataclass
from pathlib import Path

#: Marks a hook as yigraf-authored, so re-install overwrites ours but never a user's own hook.
_MARKER = "# yigraf-managed post-commit hook"

#: Markers bounding the always-on block yigraf maintains in AGENTS.md (idempotent replace).
_AGENTS_START = "<!-- yigraf:start -->"
_AGENTS_END = "<!-- yigraf:end -->"


@dataclass
class HookResult:
    path: Path
    installed: bool  # False when an unmanaged hook is already present (left untouched)


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
    return HookResult(path=hook_path, installed=True)


# --------------------------------------------------------------------------------------------------
# Claude Code hooks: PostToolUse (drift/intent surfacing) + SessionStart (re-inject) — R8
# --------------------------------------------------------------------------------------------------

SKILL_MD = """\
---
name: yigraf
description: Use when implementing or changing code in this repo to keep intent and code in sync. Before starting work, run `yigraf context "<topic>"` to surface governing intents, plans, and drift. After finishing a task, run `yigraf link <task> <symbol>` to name the symbols that implement it.
---

# yigraf — the intent↔code spine

This repo is indexed by **yigraf**: one graph over code structure, intents (specs), and plans, with
an enforceable `implements` link whose drift is surfaced when code and intent diverge. Two rituals
keep it useful — the hooks are a safety net, not a substitute.

## 0. Orient before you touch code (always)
Run `yigraf context "<what you're about to work on>"`. It returns the governing requirement(s), the
implementing symbol signatures (not source), the open tasks, and any **drift** — a token-cheap map.
If a spec already covers your change, refine it; don't duplicate.

## 1. Link when a task is done (the seam)
When you finish a task, name the symbols that implement it:
`yigraf link task:<plan>/<n> sym:<path>#<name>` — this anchors the link to the symbol's current
content. Linking once per completed task (not per edit) is enough.

## 2. Author specs as you plan
- `yigraf intent <slug> -s "The system SHALL …" --scenario "Given …, When …, Then …" [--design "…"]`
- `yigraf plan <slug> -t "<title>" --task "<description>"` then `yigraf link task:<plan>/1 int:<slug>`
  to track the intent.

## 3. Drift means re-verify
`yigraf drift` lists soft drift (a linked symbol's body changed) and hard drift (it's gone). A pure
rename auto-re-anchors. To clear a real drift, re-verify the code still satisfies the spec, then
`yigraf link` again to re-anchor.
"""

_AGENTS_BLOCK = f"""{_AGENTS_START}
## yigraf
This repo uses **yigraf** (intent↔code graph). Before changing code, run
`yigraf context "<topic>"` to see governing intents + drift. After finishing a task, run
`yigraf link task:<plan>/<n> sym:<path>#<name>`. `yigraf drift` shows what needs re-verifying.
{_AGENTS_END}"""


@dataclass
class ClaudeHookResult:
    settings_path: Path
    skill_path: Path
    agents_path: Path
    hooks_changed: bool


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


def install_claude_hooks(root: Path) -> ClaudeHookResult:
    """Register the PostToolUse + SessionStart hooks in .claude/settings.json and lay down the skill.

    Idempotent and non-clobbering: merges into an existing ``settings.json``, only touching the two
    yigraf hook entries (keyed by their ``hook <verb>`` command), and maintains a marked block in
    ``AGENTS.md``. Commands bake in the absolute interpreter (``python -m yigraf``) so they run
    regardless of ``PATH``; the hook reads the repo root from the event's ``cwd``.
    """
    root = Path(root).resolve()
    claude = root / ".claude"
    settings_path = claude / "settings.json"

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

    claude.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    skill_path = claude / "skills" / "yigraf" / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(SKILL_MD, encoding="utf-8")

    agents_path = _write_agents_block(root / "AGENTS.md")
    return ClaudeHookResult(settings_path=settings_path, skill_path=skill_path,
                            agents_path=agents_path, hooks_changed=changed)


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
