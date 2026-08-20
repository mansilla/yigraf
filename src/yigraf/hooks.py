"""Git hook installation: keep the materialized view warm at the commit boundary (R5, M2b).

``yigraf install-hooks`` writes a ``post-commit`` hook that re-materializes the gitignored SQLite view
(``.local/graph.db``) after each commit — the BUILD-PLAN's "detached AST rebuild." It is **fail-open**
(never blocks or fails a commit) and bakes in the absolute interpreter path + repo root, so it runs even
when ``PATH`` lacks the venv. No git merge driver is registered: the view is gitignored, never committed,
so there is nothing for concurrent branches to conflict on (mem:059 — this retired the whole-graph lock).

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
        "# Re-materialize yigraf's gitignored view (.local/graph.db) at HEAD. Fail-open: never block a commit.\n"
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
description: Keep intent, code, and the reasoning behind them in sync when changing code in this repo. Read this skill before driving the CLI — the wrong verb rubber-stamps or destroys a trail. Before you report done, run `yigraf status`: up to date means no drift AND no stale, not the same as no open tasks.
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

Two companions to `context`, for the two questions it structurally cannot answer:
- **Handed an id?** `yigraf show <id>` reads that one node in full — every anchor, the whole `why`,
  and which of its anchors are drifting right now. `context` searches by *meaning*, so an id reaches
  it as a bag of characters and comes back as whatever sits nearest; that reads like an answer and
  isn't one. Drift lines, conflict lines and the session-start manifest all hand you ids.
- **Don't know what to ask for?** Session start lists the *titles* of memories the packet didn't show
  ("Also known"). You can't formulate a query for knowledge you don't know exists, and a fresh session
  doesn't know any of it exists — so skim the titles, then `show` or `context` what looks relevant.

## 0b. Before you say you're done: `yigraf status`
"Up to date" means **no drift AND no stale**. Those are different from "no open tasks", and an empty
`context` packet is evidence of neither — `context` answers the *topic* you asked about, while
`status` is the only surface that reports both counts unconditionally. `yigraf drift` explains any
drift; `yigraf drift --stale` lists the stale completions (that's what `⚠ n stale` counts).

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
- Changed your mind? Never edit a decision in place — `yigraf supersede mem:<id> "<new decision>" --why "<what changed>"`. The old one stays as a rejected alternative, and the new one **inherits the old one's `--concerns`/`--serves` anchors** unless you re-aim with explicit flags — a correction that loses its anchor never resurfaces at the edit hook on the exact symbol it warns about.
- Decision still holds after you edited the code it governs? `yigraf reaffirm mem:<id>` — re-stamps the anchor and clears the drift (the honest counterpart to `supersede`: don't re-`remember`, that duplicates).
- Decision holds but its **subject moved** (the code lives somewhere else now, or the anchor was
  mis-declared at capture)? `yigraf reanchor mem:<id> <old> <new>` moves one anchor with **no
  supersedes trail** — a locus repair is not a mind-change, and filing it as one writes a false entry
  into the most valuable structure in the graph. An anchor that never belonged at all →
  `yigraf unlink mem:<id> <ref>` (works for `concerns` and `grounded_by`).
- A belief about how a file is *used* rather than what it contains ("status.md holds ONLY status")?
  `--governs file:<path>`: surfaces at the edit hook exactly like `--concerns` but carries no content
  hash, so it **never drifts** — a content anchor on a usage policy demands a rubber-stamp reaffirm on
  every edit that obeys it, and a ⚠ that is usually noise trains you to clear it without reading.
- Governing an infra/glue file with **no code symbol** (Dockerfile, buildspec, `*.sh`, `*.json`)? Anchor to the file: `--concerns file:<path>` (whole file), or `--concerns file:<path>:L10-L40` for a line range — region-scoped, so an unrelated edit elsewhere in the file doesn't drift it. `sym:` is for code; `file:` is for everything else. (A whole-file `file:` anchor on *indexed code* is refused — use a symbol or a line range there.)
  Prefer a **line range** only for a file that grows at the END — a log, an append-only record. A
  curated list edited in the middle silently *slides* the range onto unrelated text while leaving it
  syntactically valid, so a later reaffirm re-stamps the wrong region. When the locus is code, anchor
  a **symbol** even if the claim feels like it's about a passage — a symbol moves with its body. For a
  usage policy over a whole document, use `--governs` (§2). And note anchor granularity: a *class*
  anchor hashes member names, not method bodies — a belief about what a method computes must anchor
  the method, or it never resurfaces when that arithmetic changes. If what you're asserting is that
  the file *exists* rather than what's in it, don't cite it as `--evidence` at all.
- The human genuinely chose this (you asked, they answered)? `yigraf attest mem:<id>` records the
  principal's endorsement — a sticky trust floor that ranks it up and holds any later agent
  `supersede` of it *pending* a human. Use it for an elicited preference; never to bless your own call.
- A rule that is load-bearing on **every** task, not just this code? `yigraf remember … --pin` (or
  `yigraf pin mem:<id>`) injects it in full at every session start. Relevance ranking structurally
  cannot reach a rule like that — it resembles no particular topic — so this is the only way it gets
  seen. Keep the set tiny; the budget binds and drops the rest.

A `--concerns` link is **anchored** like `implements`: edit that code later and yigraf surfaces a
"re-verify this decision still holds" reconcile. That's the payoff — the next agent to touch the code
sees the decision and its rationale without reading the history.

**yigraf vs. your host's own memory** — they hold different things, so use both. A yigraf memory is
*retrieved by relevance and anchored to code*: durable but topical, and it is the only one that can
tell you your own edit just invalidated it. Your host's project memory is *loaded verbatim every
session*: small and always-on. Anchored-and-topical → yigraf. Small-and-universal → host memory, or
`--pin`. Writing a code-anchored finding into a flat file loses the drift signal, which is the whole
reason to have yigraf at all.

## 3. Author specs as you plan
- `yigraf intent <slug> -s "The system SHALL …" --scenario "Given …, When …, Then …" [--design "…"]`
- `yigraf plan <slug> -t "<title>" --task "<description>"` then `yigraf link task:<plan>/1 int:<slug>`
  to track the intent.

## 4. The three re-verify signals: drift, stale, conflict
`yigraf context` and the hooks push these at you as you work, so you rarely have to go looking —
**but they are scoped**: the hooks to the file you touched, `context` to the topic you asked about. At
the end of a task that is not enough. `yigraf status` is the authority, and it is the one surface that
reports every count unconditionally (§0b). Each signal has **one** resolving verb; using the wrong one
either rubber-stamps a belief you didn't check or destroys a reasoning trail. Read the claim before
choosing — `yigraf show mem:<id>` prints it in full, and `yigraf drift` now prints it inline.

**Drift** — a live link's anchor no longer matches: soft (the symbol's body changed) or hard (it's
gone), on `implements` (task→code), `concerns` (decision→code), or `grounded_by` (decision→evidence).
A pure rename auto-re-anchors and never surfaces. Re-verify the code still satisfies the thing, then:
- a task's `implements` → `yigraf link task:<id> sym:…` (re-anchors; use this for a symbol that moved
  *and* changed — `link` on the new locus, never unlink-then-link)
- a task's `implements` whose symbol is gone for good, or that was declared wrongly →
  `yigraf unlink task:<id> <target>`. `link` keys by the exact locator, so a re-link after a move
  *appends* rather than replaces; without `unlink` the old entry is drift no verb can clear. This is a
  graph edit, not a mind-change — it leaves no supersedes trail, because the declaration was simply
  never (or is no longer) true.
- a decision's `concerns` that still holds → `yigraf reaffirm mem:<id>` (never re-`remember` — that
  duplicates; never `supersede` unless your mind actually changed)
- a decision's anchor whose subject MOVED → `yigraf reanchor mem:<id> <old> <new>` (a locus repair,
  no supersedes trail); one that never belonged → `yigraf unlink mem:<id> <ref>`
- `grounded_by` → `yigraf reaffirm mem:<id> --grounding empirical --evidence <ref>` if you re-observed
  the evidence — **the `--evidence` re-stamp is what clears it**; without it the command is refused
  rather than exiting clean over a standing ⚠. Otherwise downgrade the claim to `inferred`, or retire
  a dead ref with `yigraf unlink mem:<id> <ref>` — an `empirical` tier whose evidence moved is unearned
- an edit-heavy session that drifted many decisions on one locus → `yigraf reaffirm <sym|file>`
  reaffirms every memory concerning that locus at once. Scoped to a locus you *actually re-verified* —
  there is deliberately no blanket "clear all drift", because that is rubber-stamping.

**Stale completion** — a task marked **done** whose implementing symbol drifted. The completion isn't
false, it's *unverified*: the evidence for "done" moved. Re-verify, then `yigraf link task:<id> sym:…`
to re-anchor — or reopen the task if the change actually regressed it. Never flip it to `todo`
automatically. You won't see these at the edit hook (a closed task must not nag mid-edit); they surface
in `yigraf context`, at SessionStart, and to your principal at the turn boundary. This is what
`status`'s `⚠ n stale` counts — `yigraf drift --stale` lists them. (Plain `yigraf drift` says "No
drift." even when stale items exist; that isn't a contradiction, it's the suppression above.)

**Conflict** — two live beliefs saying nearly the same thing about the same code, never reconciled.
Either the cosine sweep found them, or a principal *nominated* them with `dispute`. **`yigraf
conflicts` lists every open pair** with its shared anchor and the verbs that resolve it — that is what
`status`'s `⚠ n conflict` counts, and it exits non-zero exactly like `drift`, so a count is never a
dead end. Read both sides (`yigraf show <id>`), then:
- they're compatible / one refines the other → `yigraf reconcile mem:<a> mem:<b>`
- one genuinely wins → `yigraf supersede mem:<loser> "<the surviving claim>" --why "…"`
- you can see they conflict but the call isn't yours → `yigraf dispute mem:<a> mem:<b> --why "…"`.
  This *nominates* the pair: it blocks nothing, both stay live, but the open question is now durable
  and actor-stamped so it rides the log to everyone — unlike a swept finding, which is index-derived
  and invisible to anyone without an index. Use it instead of silently moving on.
- **pending** conflict (an agent supersede of a human-attested decision is held, never applied) → you
  cannot clear this one. It needs `yigraf attest` from a human. Surface it and move on. (`attest` is
  also a verb you can *reach for* — see §2 — when the principal has genuinely made the call.)
- same provenance tier with no preferred side → that is not a bug. Two equal-authority beliefs stay an
  open question for the principal rather than being tie-broken. Ask, or `dispute` it.

(`yigraf drift` exits non-zero on drift — that's the commit/CI gate, not something you poll.)

## 5. Evolve an intent (retire or reverse a spec)
Specs change too — but **never hand-edit a superseded intent into place**; use one of two supported paths:
- **Retire / reactivate** (obsolete, no replacement): `yigraf intent <slug> --status archived` (or
  `active` / `satisfied`). The contract text is left untouched — no clobber.
- **Reverse** (the premise turned out false): `yigraf supersede-intent <old-slug> <new-slug> -s "<new
  SHALL contract>" --why "<what changed>"`. This creates the replacement (active), archives the old, and
  writes a real `int→int` **supersedes** edge — so `context` can traverse from the replacement back to
  what it replaced (a bare `superseded_by:` line would be invisible to the graph). The `--why` is
  captured as a memory serving the new intent — the perishable reason the reversal happened.
"""

_AGENTS_BLOCK = f"""{_AGENTS_START}
## yigraf
This repo uses **yigraf** (a graph over code, intent, plan, and the *why*). Before changing code, run
`yigraf context "<topic>"` — the one read command: it surfaces governing intents, prior decisions, and
any drift to re-verify. Handed a node id by a warning, read it with `yigraf show <id>` (`context`
searches by meaning and cannot match an id). After finishing a task, run
`yigraf link task:<plan>/<n> sym:<path>#<name>`, and `yigraf remember` the non-obvious choices (with
`--why` and `--concerns <sym>`) — as the work lands, not as a closing ritual.

Before you report done, run `yigraf status`: "up to date" means **no drift AND no stale**, which is not
the same as no open tasks. `yigraf drift` explains the drift; `yigraf drift --stale` lists the stale
completions; `yigraf conflicts` lists the open knowledge-conflicts (`⚠ n conflict`) with the verbs
that resolve them. `yigraf cheatsheet` prints every verb and flag.
{_AGENTS_END}"""

#: Machine-local Claude Code files `yigraf install-claude-hooks` writes — they bake this clone's
#: absolute interpreter path, so they may never reach a commit. A teammate inherits the committed
#: SKILL.md + AGENTS.md block and just re-runs the installer to wire their own paths.
_CLAUDE_GITIGNORE_FILES = ("settings.local.json",)
_CLAUDE_GITIGNORE_HEADER = (
    "# Machine-local Claude Code wiring written by `yigraf install-claude-hooks` — the commands bake\n"
    "# in this clone's absolute interpreter path, so they're per-machine and kept out of git.\n"
)


@dataclass
class ClaudeHookResult:
    settings_path: Path
    skill_path: Path
    agents_path: Path
    hooks_changed: bool
    gitignore_path: Path | None = None  # .claude/.gitignore keeping settings.local.json out of git
    statusline: str = "unchanged"  # "set" | "refreshed" | "kept-foreign" | "unchanged"


def _ensure_claude_gitignore(claude: Path) -> Path:
    """Ensure ``.claude/.gitignore`` ignores the per-machine files (idempotent, non-clobbering)."""
    path = claude / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    present = {ln.strip() for ln in existing.splitlines()}
    missing = [f for f in _CLAUDE_GITIGNORE_FILES if f not in present]
    if missing:
        header = _CLAUDE_GITIGNORE_HEADER if not present else ""  # header only for a fresh file
        prefix = existing.rstrip() + "\n\n" if existing.strip() else ""
        path.write_text(prefix + header + "\n".join(missing) + "\n", encoding="utf-8")
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
    """Point Claude Code's ``statusLine`` at ``yigraf statusline`` — idempotent, non-clobbering.

    The hooks speak into the *agent's* context; the statusline is the *human's* ambient surface, so
    wiring it is what makes the ``[Yigraf]`` brand + graph health actually visible on every refresh
    (int:status-surface). A statusLine is a single object (not a list), so we only set it when it's
    absent or already ours — recognized by ``yigraf statusline`` (the current command), the old
    ``yigraf-statusline.sh`` bash adapter, or the older plain ``yigraf status`` — so any prior version
    refreshes in place. A *foreign* statusLine is left untouched — clobbering a user's own status bar
    would be hostile (mirrors the non-clobbering rule the hook merge already follows). Returns the
    action for the install summary.
    """
    existing = settings.get("statusLine")
    if isinstance(existing, dict):
        cmd = existing.get("command", "")
        if "yigraf-statusline" not in cmd and "yigraf status" not in cmd:
            return "kept-foreign"
        if cmd == command:
            return "unchanged"
        settings["statusLine"] = {"type": "command", "command": command}
        return "refreshed"
    settings["statusLine"] = {"type": "command", "command": command}
    return "set"


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
    # Stop: the PRINCIPAL's turn-boundary notice (int:obligation-notice) — the only yigraf hook whose
    # audience is the human. It emits the universal `systemMessage` field (shown in the UI, never added
    # to the agent's context) and never `decision`, so it informs without gating (mem:bf00a1f5).
    changed |= _ensure_hook(hooks, "Stop", "",
                            f'"{py}" -m yigraf hook stop', "hook stop")

    claude.mkdir(parents=True, exist_ok=True)
    # The statusline adapter is a dependency-free Python command — the [Yigraf] bar + ctx gauge, no jq.
    statusline = _ensure_statusline(settings, f'"{py}" -m yigraf statusline')
    changed |= statusline in ("set", "refreshed")
    (claude / "yigraf-statusline.sh").unlink(missing_ok=True)  # retire the old bash+jq adapter

    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    gitignore_path = _ensure_claude_gitignore(claude)

    skill_path = claude / "skills" / "yigraf" / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(SKILL_MD, encoding="utf-8")

    agents_path = _write_agents_block(root / "AGENTS.md")
    return ClaudeHookResult(settings_path=settings_path, skill_path=skill_path,
                            agents_path=agents_path, hooks_changed=changed,
                            gitignore_path=gitignore_path, statusline=statusline)


def _write_fenced_section(path: Path, block: str) -> Path:
    """Insert or refresh a `yigraf:start`/`yigraf:end`-fenced block in a file yigraf does NOT own.

    Used for every *shared* instruction file — AGENTS.md, and the Tier-A hosts whose native context
    file is a single shared document the user also writes in (Copilot's `.github/copilot-instructions.md`,
    Gemini CLI's `GEMINI.md`). Wholly-owned rule files (`.cursor/rules/yigraf.mdc`) are clobbered
    instead; only shared files get a fence, because clobbering one would eat the user's own content.
    """
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if _AGENTS_START in existing and _AGENTS_END in existing:
        head, _, rest = existing.partition(_AGENTS_START)
        _, _, tail = rest.partition(_AGENTS_END)
        updated = head + block + tail
    else:
        updated = (existing.rstrip() + "\n\n" if existing.strip() else "") + block + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return path


def _write_agents_block(agents_path: Path) -> Path:
    """Insert or refresh the marked yigraf block in AGENTS.md without disturbing the rest."""
    return _write_fenced_section(agents_path, _AGENTS_BLOCK)


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
# Tier-A ambient-rule adapters (int:host-push-adapters): a host with no edit-lifecycle hook but with an
# always-on rules mechanism + MCP lands at Tier A (mem:045). The push channel is an always-on rule the
# agent reads every session pointing it at the yigraf MCP tools — one rule body, one install shape;
# hosts differ ONLY in *where* the rule file lives and whether that host's rule format needs frontmatter
# to mark the rule always-on (Cursor `.mdc`, Windsurf). Antigravity was the first such host (verified
# hookless — Google staff); Kilo/Cursor/Windsurf are the VS Code family (rules + MCP, no agent-edit
# hook). We never auto-write a host's *global* MCP config (paths are version-specific) — the caller
# prints the snippet for the user to add via the host's own MCP editor.
# --------------------------------------------------------------------------------------------------

_AMBIENT_MCP_RULE = """\
# yigraf (via MCP)

This repo is indexed by **yigraf** — one graph over code, intent, plan, and the *why* (decisions,
constraints, rejected alternatives). yigraf is wired as an MCP server; use its tools:

- **Before** changing code, call the `context` tool with your topic — it returns the governing
  intents, the active plan, implementing signatures, prior decisions and their *why*, and any drift to
  re-verify. Don't re-derive intent or re-read what the graph already encodes.
- **After** finishing a task, call `link` to name the symbols it implements, and `remember` the
  non-obvious decisions (with `why` and `concerns`) — as the work lands, not as a closing ritual.
  Changed your mind? `supersede` the old decision; edited code a decision governs but it still holds?
  `reaffirm` it to clear the drift. A correction/rule → `note_constraint`.
- **Handed a node id** by a warning? Call `show` with it. `context` searches by *meaning* and cannot
  match an id except by accident, so it answers an id with proximity noise that reads like an answer.
- **Before you report done**, call `status`: "up to date" means no drift AND no stale, which is not
  the same as no open tasks.
- A rule that is load-bearing on every task, not just this code? `pin` it — relevance ranking cannot
  reach a rule that resembles no particular topic. Keep the set tiny.

If a spec already governs your change, follow it; if a decision already settled the question, follow
it (or `supersede` it on purpose).
"""


@dataclass(frozen=True)
class AmbientRuleHost:
    """A Tier-A host's install target: where its always-on rule file lives and any frontmatter its rule
    format needs to be recognized as always-applied. ``frontmatter`` is prepended verbatim to the shared
    rule body — empty for hosts that apply every file in the rules dir (Antigravity, Kilo).

    ``shared`` splits the two ownership models. False (the default) means yigraf *owns* the file — a
    dedicated rule in the host's rules dir, rewritten wholesale. True means the host's native context
    file is one shared document the user also writes in (Copilot's `.github/copilot-instructions.md`,
    Gemini CLI's `GEMINI.md`), so yigraf may only maintain a `yigraf:start`/`yigraf:end`-fenced section
    of it — clobbering would eat the user's own instructions. Shared hosts take no frontmatter: their
    file is always-on by virtue of being *the* context file.
    """
    name: str
    rules_dir: tuple[str, ...]  # path parts under the repo root, e.g. (".cursor", "rules"); () = repo root
    filename: str
    frontmatter: str = ""
    shared: bool = False


#: Cursor `.mdc` and Windsurf rules gate application on frontmatter — without ``alwaysApply``/``always_on``
#: the rule is only pulled on demand, defeating the "always-on" contract. Antigravity/Kilo apply every
#: file in their rules dir, so no frontmatter is needed. (These keys are host-version-sensitive; see
#: docs/hosts.md — the rule degrades to on-demand, never breaks, if a host renames them.)
_TIER_A_HOSTS: dict[str, AmbientRuleHost] = {
    "antigravity": AmbientRuleHost("antigravity", (".agents", "rules"), "yigraf.md"),
    "kilo": AmbientRuleHost("kilo", (".kilocode", "rules"), "yigraf.md"),
    "cursor": AmbientRuleHost(
        "cursor", (".cursor", "rules"), "yigraf.mdc",
        frontmatter="---\ndescription: yigraf — pull governing intent, plan, and prior decisions\nalwaysApply: true\n---\n\n"),
    "windsurf": AmbientRuleHost(
        "windsurf", (".windsurf", "rules"), "yigraf.md",
        frontmatter="---\ntrigger: always_on\ndescription: yigraf — pull governing intent, plan, and prior decisions\n---\n\n"),
    "kiro": AmbientRuleHost("kiro", (".kiro", "steering"), "yigraf.md"),
    "gemini": AmbientRuleHost("gemini", (), "GEMINI.md", shared=True),
    "copilot": AmbientRuleHost("copilot", (".github",), "copilot-instructions.md", shared=True),
}


@dataclass
class AmbientRuleResult:
    host: str
    rule_path: Path
    agents_path: Path
    mcp_command: str  # the command a host launches for the MCP server (for the printed config snippet)


def install_ambient_rule(root: Path, host: str) -> AmbientRuleResult:
    """Wire a Tier-A host: write its always-on rule (pointing at the yigraf MCP tools) + the AGENTS block.

    One shape for every ambient-rule host — only the rule file's location, any always-on frontmatter,
    and whether yigraf *owns* that file differ, all carried by ``_TIER_A_HOSTS[host]``. Hosts with a
    dedicated rules dir (Antigravity, Kilo, Cursor, Windsurf, Kiro) get a wholly-owned rule file;
    hosts whose native context file is a shared document (Gemini CLI's `GEMINI.md`, Copilot's
    `.github/copilot-instructions.md`) get a fenced section instead, so the user's own instructions
    survive. Both files are committed/shareable. The MCP server is the data channel; the caller prints
    the ``mcpServers`` snippet for the user to add via the host's own MCP editor (global paths are
    version-specific, so we don't auto-write them).
    """
    spec = _TIER_A_HOSTS[host]
    root = Path(root).resolve()
    rule_path = root.joinpath(*spec.rules_dir) / spec.filename
    if spec.shared:
        _write_fenced_section(rule_path, f"{_AGENTS_START}\n{_AMBIENT_MCP_RULE.strip()}\n{_AGENTS_END}")
    else:
        rule_path.parent.mkdir(parents=True, exist_ok=True)
        rule_path.write_text(spec.frontmatter + _AMBIENT_MCP_RULE, encoding="utf-8")
    agents_path = _write_agents_block(root / "AGENTS.md")
    mcp_command = f'"{sys.executable}" -m yigraf mcp --repo "{root}"'
    return AmbientRuleResult(host=host, rule_path=rule_path, agents_path=agents_path,
                             mcp_command=mcp_command)


def install_antigravity(root: Path) -> AmbientRuleResult:
    """Wire yigraf for the Antigravity IDE (Tier A — no hooks): an always-on rule + the AGENTS block.

    A thin alias over :func:`install_ambient_rule` kept for the standalone ``install-antigravity``
    command and back-compat (mem:020). Writes ``.agents/rules/yigraf.md`` + refreshes the AGENTS block.
    """
    return install_ambient_rule(root, "antigravity")


# --------------------------------------------------------------------------------------------------
# The push-fidelity matrix (int:host-push-adapters, task #1) — the source of truth for what tier a host
# lands in and why. Push fidelity is a gradient, not a has-hook boolean (mem:045): Tier E = event-scoped
# (an edit/session lifecycle hook fires and yigraf injects the file's governing intent + drift), Tier A
# = ambient-rule (always-on rule + MCP, no edit lifecycle — coarser: "call context", not "the file you
# just touched drifted"), Tier P = pull-only (MCP alone). yigraf delivers the highest tier a host's OWN
# native seams allow, via a thin adapter — never a forked agent or a maintained plugin runtime.
# docs/hosts.md renders this table for humans; this structure is what the installer consults.
# --------------------------------------------------------------------------------------------------

TIER_EVENT = "E"    # event-scoped: edit/session lifecycle hook
TIER_AMBIENT = "A"  # ambient-rule: always-on rules + MCP, no edit lifecycle
TIER_PULL = "P"     # pull-only: MCP alone


@dataclass(frozen=True)
class HostFidelity:
    """One row of the push-fidelity matrix. ``tier`` is what yigraf delivers today; ``ceiling`` is the
    highest its native seams could reach WITHOUT a forked agent or a maintained editor-extension plugin
    runtime. They differ only when a real, unwired seam exists. For the VS Code family they're equal at
    A: the sole higher seam is an authored editor extension shelling to yigraf on save — a plugin runtime
    the intent excludes (task #4) — so a save event is NOT a native host seam we count."""
    name: str
    seam: str                  # the native extension point yigraf rides
    edit_lifecycle_hook: bool  # does the host fire an edit/save event yigraf can hook? (⇒ Tier E)
    tier: str                  # current delivered tier
    ceiling: str               # highest tier the host's native seams allow (no plugin runtime)
    installer: str             # the CLI subcommand that wires it


HOST_FIDELITY: tuple[HostFidelity, ...] = (
    HostFidelity("claude", "PostToolUse + SessionStart hooks", True, TIER_EVENT, TIER_EVENT,
                 "install-claude-hooks"),
    HostFidelity("codex", ".codex/hooks.json (mirrors Claude Code's contract)", True, TIER_EVENT,
                 TIER_EVENT, "install-codex-hooks"),
    HostFidelity("antigravity", ".agents/rules/ (no hook system — verified)", False, TIER_AMBIENT,
                 TIER_AMBIENT, "install-antigravity"),
    HostFidelity("kilo", ".kilocode/rules/", False, TIER_AMBIENT, TIER_AMBIENT, "install-kilo"),
    HostFidelity("cursor", ".cursor/rules/*.mdc", False, TIER_AMBIENT, TIER_AMBIENT, "install-cursor"),
    HostFidelity("windsurf", ".windsurf/rules/", False, TIER_AMBIENT, TIER_AMBIENT, "install-windsurf"),
    HostFidelity("kiro", ".kiro/steering/", False, TIER_AMBIENT, TIER_AMBIENT, "install-kiro"),
    HostFidelity("gemini", "GEMINI.md (shared context file)", False, TIER_AMBIENT, TIER_AMBIENT,
                 "install-gemini"),
    HostFidelity("copilot", ".github/copilot-instructions.md (shared context file)", False,
                 TIER_AMBIENT, TIER_AMBIENT, "install-copilot"),
)

#: The Tier-E push-hook hosts, in install order (their installers wire lifecycle hooks, not a rule).
EVENT_HOSTS: tuple[str, ...] = tuple(h.name for h in HOST_FIDELITY if h.tier == TIER_EVENT)
#: The Tier-A ambient-rule hosts, in install order (wired via :func:`install_ambient_rule`).
AMBIENT_HOSTS: tuple[str, ...] = tuple(h.name for h in HOST_FIDELITY if h.tier == TIER_AMBIENT)
#: Every host `yigraf install --host X` can target natively (anything else → the universal MCP floor).
SUPPORTED_HOSTS: tuple[str, ...] = tuple(h.name for h in HOST_FIDELITY)


# --------------------------------------------------------------------------------------------------
# Host auto-detection (M-multi, extended for the VS Code family): which natively-supported host(s) are
# present, so `yigraf install` can wire the right channel without asking — falling back to MCP for
# anything else. Preserves the mem:021 zero-config auto-detect + mem:016 MCP-universal floor.
# --------------------------------------------------------------------------------------------------

#: A host name → the repo-local marker dirs that signal "configured for this repo".
_HOST_MARKERS = {
    "claude": (".claude",),
    "codex": (".codex",),
    "antigravity": (".agents",),
    "kilo": (".kilocode",),
    "cursor": (".cursor",),
    "windsurf": (".windsurf",),
    "kiro": (".kiro",),
    "gemini": (".gemini", "GEMINI.md"),
    "copilot": (),  # explicit-only — see below
}
#: A host name → the home-dir marker dirs that signal "installed on this machine".
#: Antigravity ships *under* ``~/.gemini`` (mcp_config lives at ``~/.gemini/antigravity/``), so a bare
#: ``~/.gemini`` is Gemini CLI, NOT Antigravity — matching it for antigravity mis-wired every Gemini CLI
#: user with an ``.agents/rules/`` dir their host never reads. Antigravity's home marker is therefore the
#: narrow ``.gemini/antigravity`` (or its own ``~/.antigravity``); the broad ``~/.gemini`` belongs to
#: gemini. The reverse overlap is harmless and deliberate: an Antigravity user also has ``~/.gemini``, so
#: both get wired — which is exactly the documented wire-all-detected behaviour (mem:643ef324c28df1e3).
#:
#: Copilot has NO safe marker: ``.github/`` exists in nearly every repo, and Copilot's VS Code extension
#: dir is version-globbed. Auto-detecting it would false-positive on almost every repository, so it is
#: reachable only via an explicit ``--host copilot`` / ``install-copilot`` (empty tuples never match).
_HOST_HOME_MARKERS = {
    "claude": (".claude",),
    "codex": (".codex",),
    "antigravity": (".antigravity", ".gemini/antigravity"),
    "kilo": (".kilocode",),
    "cursor": (".cursor",),
    "windsurf": (".codeium", ".windsurf"),  # Windsurf (Codeium) keeps global state under ~/.codeium
    "kiro": (".kiro",),
    "gemini": (".gemini",),
    "copilot": (),  # explicit-only — see above
}


def detect_hosts(root: Path, home: Path | None = None) -> list[str]:
    """The natively-supported hosts present, by config markers — repo-local or in the home dir.

    Repo markers mean "configured for this repo"; home markers mean "installed on this machine". Either
    counts. ``home`` is injectable for testing. Returns names in install order (claude, codex,
    antigravity, then the VS Code family kilo, cursor, windsurf); empty ⇒ `yigraf install` falls back to
    the universal MCP server.
    """
    root = Path(root)
    home = Path(home) if home is not None else Path.home()
    found = []
    for host in SUPPORTED_HOSTS:
        repo_hit = any((root / m).exists() for m in _HOST_MARKERS[host])
        home_hit = any((home / m).exists() for m in _HOST_HOME_MARKERS[host])
        if repo_hit or home_hit:
            found.append(host)
    return found
