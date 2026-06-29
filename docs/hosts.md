# yigraf across AI coding hosts

yigraf's value reaches a host through two kinds of channel: **pull** (the agent asks — the MCP server,
universal) and **push** (yigraf injects at the moment of action — native lifecycle hooks, where the
host has them). The strategy: **MCP is the floor everywhere; native push hooks are a thin complement
where a host supports them.**

| Host | Pull (MCP) | Push (hooks) | Instructions | Wire it |
|------|-----------|--------------|--------------|---------|
| **Claude Code** | ✅ `yigraf mcp` (optional) | ✅ PostToolUse + SessionStart | SKILL.md + AGENTS.md | `yigraf install-claude-hooks` |
| **Codex CLI** | ✅ `yigraf mcp` | ✅ SessionStart (+ best-effort PostToolUse) | AGENTS.md | `yigraf install-codex-hooks` |
| **Antigravity IDE** | ✅ `yigraf mcp` | ❌ none (no hook system) | `.agents/rules/` + AGENTS.md | `yigraf install-antigravity` |
| **Cursor / Windsurf / other MCP** | ✅ `yigraf mcp` | — | AGENTS.md | see `docs/mcp.md` |

Push is the stronger channel (it surfaces governing intent/drift without the agent having to ask), but
not every host offers it — see the per-host notes. The MCP server (`docs/mcp.md`) carries the rest.

## One command: `yigraf install`

```bash
yigraf install                       # auto-detect the host(s) and wire the right channel for each
yigraf install --host codex          # or target one explicitly: claude | codex | antigravity | mcp
```

`auto` detects Claude Code / Codex / Antigravity by their config markers (a repo-local `.claude`/`.codex`/
`.agents`, or `~/.claude` / `~/.codex` / `~/.gemini` on the machine) and runs each one's installer. If
**none** of the three is found — or you pass an unsupported `--host` (e.g. `mcp`, `cursor`) — it falls
back to the universal **MCP** server config, which any MCP host accepts. The per-host installers below
are still available directly.

## Codex CLI — a near-free push complement

Codex's hook system mirrors Claude Code's: same stdin fields (`tool_name`, `tool_input`, `cwd`) and the
same `hookSpecificOutput.additionalContext` output. So yigraf reuses the **exact same handlers**
(`yigraf hook session-start` / `post-tool-use`); only the install target differs.

```bash
yigraf install-codex-hooks         # writes .codex/hooks.json + the AGENTS.md block
```

- Writes `.codex/hooks.json` registering **SessionStart** (re-inject the active plan + intents — the
  "memory survives a reset" win) and **PostToolUse** (inject governing intent/drift on edits).
- Bakes this clone's absolute interpreter (PATH-independent), so the file is machine-specific — a
  `.codex/.gitignore` keeps it out of git; teammates re-run the command. (Same model as Claude Code.)
- Codex loads project-local `.codex/` hooks only for a **trusted** project — trust it once.
- **Caveat:** Codex edits via `apply_patch`, whose file path lives *inside* the patch; yigraf parses the
  `*** Update File: <path>` line. The exact edit-tool name varies by Codex version, so PostToolUse-on-edit
  is **best-effort and fail-open** (silent if it doesn't match) — SessionStart is the reliable part.
  Verify the edit-tool name on your version if per-edit injection matters.

## Antigravity IDE — no hooks, so an always-on rule + MCP

The Antigravity IDE has **no lifecycle-hook system** (so no push channel). yigraf integrates via the
MCP server (pull) plus an always-on rule that tells the agent to use it.

```bash
yigraf install-antigravity         # writes .agents/rules/yigraf.md + the AGENTS.md block, prints MCP config
```

- Writes `.agents/rules/yigraf.md` — an always-on rule pointing the agent at the yigraf MCP tools
  (`context` before editing; `link`/`remember` after). Committed/shareable.
- Prints the `mcpServers` entry to add via Antigravity's MCP editor (Agent panel → MCP Servers → raw
  config), in `~/.gemini/antigravity/mcp_config.json` *or* `~/.gemini/config/mcp_config.json` (the path
  is version-specific, so yigraf prints it rather than auto-writing a global config).
- Needs the optional `[mcp]` extra (`uv pip install -e '.[mcp]'`).

## Why not a custom hook per host?

Only where the host already exposes one (Claude Code, Codex) — there it's a thin install over shared
handlers. Where a host has none (Antigravity, and most IDEs), MCP is the integration; inventing a hook
isn't possible. So MCP is the bet, and push hooks ride along as a complement, never a requirement.
