---
concerns:
- anchor: a0d5fedb1e74f4564871e4e87beeec458af0b0943a1b1927549d4946edf72dee
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/mcp_server.py#_run_cli
family: memory
id: mem:018
maturity: working
provenance:
  source: cli
serves:
- int:mcp-server
status: active
supersedes: []
type: decision
---
## MCP write tools shell out to the matching CLI verb (subprocess); only read tools run in-process

**Why:** writes are rare and already rebuild the graph, so the per-call process cost is negligible — and shelling out reuses the CLI's dedup guard, anchoring, and exit-0 'did you mean' guidance verbatim, so the MCP write path can't drift from the CLI's. Reads stay in-process for warmth (mem:017). _run_cli returns stdout (the agent-facing text) and folds in stderr only on failure, so model-load progress never pollutes a result.

**Rejected:** extract the cli capture orchestration into shared pure functions for in-process writes — more refactor + duplicated guidance-vs-raise logic, and risks re-drifting anchored links, for a path that runs rarely
