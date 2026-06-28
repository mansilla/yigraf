---
concerns:
- anchor: f5a663baac8b107cb92340a7e8b84339013edebc995f6b2f8a0fae23e39a4903
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/status.py#_freshness
family: memory
id: mem:014
maturity: working
provenance:
  source: cli
serves:
- int:status-surface
status: active
supersedes: []
type: decision
---
## Freshness is derived by comparing the rebuilt graph to committed graph.json (canonical JSON), not by stamping a build-HEAD

**Why:** write_graph is deterministic (sort_keys=True), so a byte-equal canonical projection is an exact freshness signal with nothing written anywhere. Stamping the build-HEAD into graph.json would make every query/edit dirty git and write volatile state into the committed projection — violating R6/mem:006 (files are truth; graph.json is a recomputable projection).

**Rejected:** stamp the build-HEAD into graph.json and compare against current HEAD — writes volatile state into the committed projection (R6 violation)
