# yigraf across AI coding hosts — the push-fidelity matrix

yigraf's value reaches a host through two kinds of channel: **pull** (the agent asks — the MCP server,
universal) and **push** (yigraf injects at the moment of action). Push is not a has-hook boolean; it's a
**fidelity gradient**, and yigraf delivers the **highest tier a host's OWN native seams allow**, via a
thin adapter — never a forked agent, never a maintained editor-extension plugin runtime.

| Tier | What it delivers | Seam it needs |
|------|------------------|---------------|
| **E — event-scoped** | On edit, inject the governing intent + **drift for the file you just touched** | An edit/session **lifecycle hook** |
| **A — ambient-rule** | An always-on rule telling the agent to **pull `context`** before editing (coarser: not file-specific, not drift-aware) | An **always-on rules** mechanism + MCP |
| **P — pull-only** | The agent pulls `context`/`status` on its own initiative | **MCP** alone |

**MCP is the universal floor** — every target host speaks it, so Tier P is always available. Tiers A and
E layer native push on top where the host's seams reach that far.

## The matrix (source of truth)

This table is mirrored by the `HOST_FIDELITY` structure in `src/yigraf/hooks.py` — that structure is what
the installer actually consults, so the two cannot drift. `Tier` is what yigraf delivers today; `Ceiling`
is the highest tier the host's native seams could reach **without a plugin runtime** (see the probe note).

| Host | Native seam | Edit-lifecycle hook? | Tier | Ceiling | Wire it |
|------|-------------|:--------------------:|:----:|:-------:|---------|
| **Claude Code** | PostToolUse + SessionStart hooks | ✅ | **E** | E | `yigraf install-claude-hooks` |
| **Codex CLI** | `.codex/hooks.json` (mirrors Claude Code) | ✅ | **E** | E | `yigraf install-codex-hooks` |
| **Antigravity IDE** | `.agents/rules/` (no hook system — verified) | ❌ | **A** | A | `yigraf install-antigravity` |
| **Kilo Code** | `.kilocode/rules/` | ❌ | **A** | A | `yigraf install-kilo` |
| **Cursor** | `.cursor/rules/*.mdc` | ❌ | **A** | A | `yigraf install-cursor` |
| **Windsurf** | `.windsurf/rules/` | ❌ | **A** | A | `yigraf install-windsurf` |
| **any other MCP host** | MCP | ❌ | **P** | P | point at `yigraf mcp` (`docs/mcp.md`) |

The Tier-A hosts (Antigravity + the VS Code family) share **one adapter shape** — an always-on rule
(`_AMBIENT_MCP_RULE`) pointing the agent at the MCP tools, plus the printed `mcpServers` config. They
differ *only* in where the rule file lives and whether that host's rule format needs frontmatter to be
recognized as always-on: Cursor `.mdc` needs `alwaysApply: true`; Windsurf needs `trigger: always_on`;
Antigravity/Kilo apply every file in their rules dir, so no frontmatter. (Those frontmatter keys are
host-version-sensitive; if a host renames them the rule degrades to on-demand — it never breaks.)

## One command: `yigraf install`

```bash
yigraf install                       # auto-detect the host(s) and wire the right tier for each
yigraf install --host cursor         # or target one: claude|codex|antigravity|kilo|cursor|windsurf|mcp
```

`auto` detects a host by its config markers — a **repo-local** dir (`.claude`/`.codex`/`.agents`/
`.kilocode`/`.cursor`/`.windsurf`) **or** a **home** dir (`~/.claude`, `~/.codex`, `~/.gemini`,
`~/.kilocode`, `~/.cursor`, `~/.codeium`) — and wires each detected one at its tier. If **none** is found
— or you pass an unsupported `--host` (e.g. `mcp`, or an editor with no rules/hook seam) — it falls back
to the universal **MCP** server config (Tier P), which any MCP host accepts.

## Tier E — the push hosts (Claude Code, Codex)

Codex's hook system mirrors Claude Code's (same stdin fields `tool_name`/`tool_input`/`cwd`, same
`hookSpecificOutput.additionalContext` output), so yigraf reuses the **exact same handlers** (`yigraf hook
session-start` / `post-tool-use`); only the install target differs. Both bake this clone's absolute
interpreter (PATH-independent), so the wiring file is machine-specific — a `.gitignore` keeps it out of
git and teammates re-run the command. **SessionStart** (re-inject the active plan + intents — the "memory
survives a reset" win) is the reliable part; **PostToolUse-on-edit** is best-effort on Codex (its
`apply_patch` carries the path *inside* the patch, and the edit-tool name varies by version — fail-open).

## Tier A — the ambient-rule hosts (Antigravity + VS Code family)

These hosts expose an always-on rules mechanism + MCP but **no edit-lifecycle hook**, so push tops out at
an always-on rule that instructs the agent to pull `context` before editing (and `link`/`remember` after).
The installer writes the rule + the committed AGENTS.md block, then **prints** the `mcpServers` snippet
for the user to add via the host's own MCP editor — yigraf never auto-writes a host's *global* config
(those paths are version-specific, and a global/outward change is the user's to make deliberately).

```bash
yigraf install-antigravity   # .agents/rules/yigraf.md
yigraf install-kilo          # .kilocode/rules/yigraf.md
yigraf install-cursor        # .cursor/rules/yigraf.mdc   (frontmatter: alwaysApply: true)
yigraf install-windsurf      # .windsurf/rules/yigraf.md  (frontmatter: trigger: always_on)
```

## Probe: can a VS Code-family host reach Tier E?

**No — not without a plugin runtime, which is out of scope.** The VS Code *extension API* does expose
edit/save lifecycle points (`workspace.onDidSaveTextDocument`, `onWillSaveTextDocument`), but reaching
them means **authoring and maintaining a published editor extension** that shells out to yigraf on save —
a plugin runtime the intent explicitly excludes. Crucially, that save event fires for the *human's* editor
buffer, not the *agent's* edit loop; the agent loops in Kilo/Cursor/Windsurf write files through their own
machinery, and none of them expose a hook into *that* loop (only rules + MCP). So the native seam of the
**host's agent** caps these at Tier A, and their `Ceiling` is A. If any of them ships an agent-edit
lifecycle hook, promoting it to E is a thin adapter over the shared handlers — the matrix will record it.

## Spec watch — why not push over MCP?

MCP is Tier P by design: **initiator-is-client**, with no server-initiated context primitive. The two
candidates are rejected as push channels:

- **sampling** — the server borrows the client's model, spending the *agent's* tokens on the server's
  inference (wrong direction).
- **elicitation** — the server interrupts the *user* for structured input (violates design-law #4,
  "silence is a feature").

Neither is ambient context-injection into the agent loop the way a PostToolUse hook is. So the
higher-fidelity push story rides host-native seams (Tier E/A), and MCP stays pull. **Revisit if** the MCP
spec ever ships a real server-initiated context/notification primitive — that would let Tier-P/Tier-A
hosts be promoted to event-scoped push over the universal channel, lifting every MCP host at once.
