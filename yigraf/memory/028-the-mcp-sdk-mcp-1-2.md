---
concerns:
- anchor: fc0e73f1453ef4f7a4646f4d6dde677162894337304a88ca726d57cf0d6f2a14
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/mcp_server.py#run
family: memory
id: mem:028
maturity: working
provenance:
  source: cli
serves:
- int:mcp-server
status: active
supersedes: []
type: decision
---
## the MCP SDK (mcp>=1.2) is a core dependency, not an extra

**Why:** it's a single small pure-Python package and the universal pull channel every host speaks, so gating it behind a [mcp] extra only produced silent 'no MCP' installs; unlike embeddings (mem:005) there's no torch-weight argument to keep it optional

**Rejected:** ship mcp as an optional [mcp] extra with an install-hint fallback in yigraf mcp — the pre-existing design, now removed
