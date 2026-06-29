---
concerns:
- anchor: 33cb81e451fad4c7ffe411bc6aaa88b5482640b77059cfee32214b419210efd3
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/mcp_server.py#run_context
family: memory
id: mem:017
maturity: working
provenance:
  source: cli
serves:
- int:mcp-server
status: active
supersedes: []
type: decision
---
## The MCP server runs in-process (warm graph + embedding model across calls), not a per-tool-call CLI subprocess

**Why:** an MCP server is long-lived for the session, so holding the structure graph and the bge-small model warm means the 2nd+ context call skips the cold build/model-load; a subprocess-proxy would re-pay that ~1-2s every call. Cost: ~10 lines of context orchestration duplicated from cli.context (acceptable for an adapter).

**Rejected:** subprocess-proxy (each MCP tool shells out to the yigraf CLI) — DRY and zero-refactor, but cold build+model load on every single tool call
