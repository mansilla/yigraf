---
concerns:
- anchor: 98ccdb837c62f5c40c442659e66bb66a3823cc9fad2cdf55f09894511bac35af
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/cli.py#install_cmd
family: memory
id: mem:030
maturity: working
provenance:
  source: cli
serves:
- int:multi-host
status: active
supersedes:
- mem:027
type: decision
---
## yigraf install wires full power by default and is agent-driven: the generic host-independent channel (post-commit rebuild + graph.json merge driver + AGENTS.md + MCP pull server) AND semantic recall (fastembed, core) all ship unconditionally; detected hosts layer native push hooks on top; only the torch embeddings backend stays opt-in. 'yigraf install --plan[--json]' prints the capability menu first so the human chooses before anything is applied

**Why:** extends mem:027 after semantic recall became core (mem:029): 'full power by default' now includes semantic recall, so the only opt-in left is the torch backend; added --plan so an agent can probe, present the menu, and apply only what the human picks

**Rejected:** re-anchor mem:027 unchanged: its 'only the embeddings backend stays opt-in' clause is now false
