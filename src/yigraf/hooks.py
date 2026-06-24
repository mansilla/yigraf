"""Git hook installation: keep ``graph.json`` synced to HEAD at the commit boundary (R5, M2b).

``yigraf install-hooks`` writes a ``post-commit`` hook that rebuilds the graph after each commit —
the BUILD-PLAN's "detached AST rebuild." It is **fail-open** (never blocks or fails a commit) and
bakes in the absolute interpreter path + repo root, so it runs even when ``PATH`` lacks the venv.

Anchors themselves are stamped at ``yigraf link`` time, not here (docs/m2-notes.md §4): the hook
only refreshes the projection. A symbol edited after linking, without a re-link, is left to surface
as drift — the hook does not silently re-anchor it.
"""
from __future__ import annotations

import stat
import sys
from dataclasses import dataclass
from pathlib import Path

#: Marks a hook as yigraf-authored, so re-install overwrites ours but never a user's own hook.
_MARKER = "# yigraf-managed post-commit hook"


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
