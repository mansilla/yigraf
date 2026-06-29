---
family: intent
id: int:multi-host
status: proposed
type: requirement
---
## Requirement
yigraf SHALL integrate with any AI coding host via the MCP server (universal pull), complemented by native push hooks where the host provides them (Claude Code, Codex) and an always-on rule where it does not (Antigravity).

## Scenarios
- Given Codex (whose hook contract mirrors Claude Code's), When yigraf install-codex-hooks runs, Then SessionStart + PostToolUse are wired to the SAME handlers and an apply_patch edit surfaces governing context.
- Given the Antigravity IDE (no hook system), When yigraf install-antigravity runs, Then an always-on .agents/rules file points the agent at the MCP tools and the MCP-server config snippet is printed.

## Design (how)
Push hooks ride a shared, host-agnostic handler (_edited_file generalizes edit detection across Edit/Write/apply_patch; relative paths anchored to root); installers differ only in the config target. MCP (int:mcp-server) is the floor for hosts with no hooks. Per-host custom hooks are explicitly NOT pursued beyond where the host already exposes one.
