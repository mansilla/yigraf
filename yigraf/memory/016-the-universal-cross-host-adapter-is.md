---
concerns:
- anchor: f694de595271703de9b5665affaff0b4711842d3b30ceb46bd694c928eb7f29c
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/mcp_server.py#build_server
family: memory
id: mem:016
maturity: working
provenance:
  source: cli
serves:
- int:mcp-server
status: active
supersedes: []
type: decision
---
## The universal cross-host adapter is an MCP server, not per-host native integrations — one implementation reaches Codex, Antigravity, Cursor, Windsurf, and Claude Code

**Why:** verified host research: the Antigravity IDE has NO lifecycle-hook/context-injection system (Google staff confirmed), while every target host speaks MCP. A push-hook-per-host strategy would leave Antigravity with nothing; MCP is the one channel they all share, so it's the portable floor. Push hooks remain the stronger per-host channel where they exist (Claude Code, Codex).

**Rejected:** per-host native adapters only — Antigravity has no push hook, so it would get no yigraf at all; and N bespoke integrations vs one MCP server
