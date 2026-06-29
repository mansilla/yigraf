---
family: intent
id: int:mcp-server
status: proposed
type: requirement
---
## Requirement
yigraf SHALL run as an MCP server exposing the graph (context, status) as tools, so any MCP-capable host can pull the governing slice without host-specific hooks.

## Scenarios
- Given an MCP host (Codex/Antigravity/Cursor/Claude Code) configured to launch `yigraf mcp`, When the agent calls the context tool with a topic, Then it receives the same token-budgeted slice the CLI `yigraf context` returns.
- Given the optional [mcp] extra is not installed, When `yigraf mcp` runs, Then it prints an install hint and exits non-zero (never a stack trace).

## Design (how)
In-process FastMCP server (warm graph+model across calls); read tools context+status mirror the CLI verbs via run_context/run_status; optional [mcp] extra imported lazily (graceful guidance if absent), mirroring mem:005. The pull channel reaches hosts without lifecycle hooks (e.g. Antigravity IDE); capture verbs are a planned follow-up.
