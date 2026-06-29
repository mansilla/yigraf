---
family: intent
id: int:mcp-server
status: proposed
type: requirement
---
## Requirement
yigraf SHALL run as an MCP server exposing the full agent loop — read tools (context, status) and write tools (link, remember, note_constraint, supersede) — so any MCP-capable host can both pull the governing slice and capture links/decisions back, without host-specific hooks.

## Scenarios
- Given an MCP host (Codex/Antigravity/Cursor/Claude Code) configured to launch `yigraf mcp`, When the agent calls the context tool with a topic, Then it receives the same token-budgeted slice the CLI `yigraf context` returns.
- Given a built repo, When the agent calls the link or remember tool, Then the link/decision is written and anchored exactly as the CLI verb would, and an unresolved locator comes back as exit-0 "did you mean" guidance, not an error.
- Given the optional [mcp] extra is not installed, When `yigraf mcp` runs, Then it prints an install hint and exits non-zero (never a stack trace).

## Design (how)
In-process FastMCP server. Read tools (context, status) mirror the CLI via run_context/run_status, holding the graph+embedding model warm across calls (mem:017). Write tools (link/remember/note_constraint/supersede) shell out to the matching CLI verb so they reuse its dedup guard, anchoring, and guidance verbatim — they can't drift from the CLI (mem:018). Optional [mcp] extra imported lazily (graceful guidance if absent), mirroring mem:005. The bet: this one MCP surface is yigraf's whole cross-vendor integration — it reaches hosts with no lifecycle hook (e.g. the Antigravity IDE).
