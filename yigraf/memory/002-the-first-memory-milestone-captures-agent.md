---
concerns:
- anchor: 154d8d28e1cd5dfbafefdd4d0e4d53c3cc73e5f61807e60e3ae4fd4bdcb7c4f1
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/memory.py#project_into
family: memory
id: mem:002
maturity: working
provenance:
  source: cli
serves:
- int:memory-family
status: active
supersedes: []
type: decision
---
## the first memory milestone captures agent-asserted only; no pre-/clear distillation backstop

**Why:** memory-model §5 option A: cheapest, deterministic, EXTRACTED confidence, mirrors the v0 implements pattern we already trust; add distillation (option B) only once links prove valuable
