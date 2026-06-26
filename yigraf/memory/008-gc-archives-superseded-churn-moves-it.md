---
concerns:
- anchor: 345dc85647e0255006c27566975147e536fa1046ab83b24a7c85560dee0c83d9
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/counters.py#classify_gc
family: memory
id: mem:008
maturity: working
provenance:
  source: cli
serves:
- int:memory-maturity
status: active
supersedes: []
type: decision
---
## GC archives superseded churn (moves it to memory/archive/), never deletes and never gates on usage

**Why:** R3: history must stay auditable, so churn (superseded_in>0 ∧ refs_in=0) is moved out of the active glob rather than removed; usage is machine-local sidecar state, not authoritative, so GC must not depend on it

**Rejected:** delete churn files and/or gate on usage — irreversible, and gating on local-only telemetry would make GC non-deterministic across machines
