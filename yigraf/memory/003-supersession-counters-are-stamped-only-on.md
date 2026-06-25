---
concerns:
- anchor: 12b62b7096cfcc56ca643c20b217b9902da9a167846d2115800c5bb3b2e05469
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/memory.py#recompute_counters
family: memory
id: mem:003
maturity: working
provenance:
  source: cli
serves:
- int:memory-family
status: active
supersedes: []
type: decision
---
## supersession counters are stamped only on memory nodes, not every node

**Why:** only memory carries supersedes edges, so stamping superseded_in:0 on every structure node would bloat graph.json; retrieval reads the counter with a 0 default

**Rejected:** recompute on all nodes for uniformity — needless graph.json bloat (345 nodes × 2 zero counters)
