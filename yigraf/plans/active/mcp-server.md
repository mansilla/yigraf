---
edges:
  task:mcp-server/1:
    implements:
    - anchor: 7844ed2d117974b6d706a91c93885d0d277fa064fda8ad847008aac05a6d1c3e
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/mcp_server.py#run
    - anchor: cf9e4deafdad0b3e765f4048719aaee63f85d8a28a53daa887096432feaf25a4
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
    - anchor: a0d5fedb1e74f4564871e4e87beeec458af0b0943a1b1927549d4946edf72dee
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/mcp_server.py#_run_cli
    - anchor: 6ccc49a02dba51c0aadeae647685f048f5c5a4d269a4f417c01bc062b49037dc
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/mcp_server.py#run_link
    - anchor: 97f7e00f280345e928deaa5275f38ca53264848ce70e72ba630f119a8c53be86
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/mcp_server.py#run_remember
    tracks: int:mcp-server
family: plan
id: plan:mcp-server
---
# MCP server

## Tasks
- [ ] {#1} yigraf mcp: in-process FastMCP stdio server exposing context+status as tools (the universal pull channel); optional [mcp] extra; per-host config docs
