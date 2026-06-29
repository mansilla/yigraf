---
edges:
  task:mcp-server/1:
    implements:
    - anchor: 7844ed2d117974b6d706a91c93885d0d277fa064fda8ad847008aac05a6d1c3e
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/mcp_server.py#run
    - anchor: f694de595271703de9b5665affaff0b4711842d3b30ceb46bd694c928eb7f29c
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/mcp_server.py#build_server
    - anchor: 33cb81e451fad4c7ffe411bc6aaa88b5482640b77059cfee32214b419210efd3
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/mcp_server.py#run_context
    - anchor: e6d45f46ba88f333a9097b76867de8ad5055fc260f4b3aeaab0f0aebd5de940e
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/mcp_server.py#run_status
    - anchor: c5f13769d427357d97c895c5902838e56d33b9618091f5390e08117588e2994b
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/cli.py#mcp_cmd
    tracks: int:mcp-server
family: plan
id: plan:mcp-server
---
# MCP server

## Tasks
- [ ] {#1} yigraf mcp: in-process FastMCP stdio server exposing context+status as tools (the universal pull channel); optional [mcp] extra; per-host config docs
