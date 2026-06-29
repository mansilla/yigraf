---
concerns:
- anchor: 2a16bd439cd34517e13f849f1be8bb3c15acb6355dc488a9598a9d238ced7de0
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/drift.py#compute_drift
- anchor: e716cbe43024eaa7324bd553b48116ef692ad82ae9c0205465f80cddb018a9d4
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/drift.py#resolve_renames
family: memory
id: mem:001
maturity: working
provenance:
  source: cli
serves:
- int:memory-family
status: active
supersedes: []
type: decision
---
## concerns reuses the implements drift machinery via one relation table, not a parallel code path

**Why:** the two drift-bearing relations differ only in source family + dangling-attr name; folding them into _DRIFT_RELATIONS means rename re-anchoring, the SHA cache, and soft/hard detection are written once

**Rejected:** a separate compute_concerns_drift/resolve_concerns path — duplicated logic that would drift from the implements path over time
