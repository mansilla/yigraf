---
concerns:
- anchor: c89cd8aa3c0f2ccb315be135c9f7389b09cd58b3094c5d3638fb47863d1687a6
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/counters.py#apply_maturity
family: memory
id: mem:006
maturity: working
provenance:
  source: cli
serves:
- int:memory-maturity
status: active
supersedes: []
type: decision
---
## v0 counters are local + recomputable (Model D): maturity is git-derived, telemetry lives in a gitignored sidecar, GC archives; the shared committed-counter model is deferred to v1/Enterprise

**Why:** DESIGN R1/R2/R3 scope v0 to local state so graph.json stays fully recomputable (no query-time writes, trivial merges, CI-reproducible); the accumulated/shared/merge-reconciled counter model (Model G) needs a cloud service + API for teams to share artifacts, which is v1 Enterprise paid-plan work

**Rejected:** Model G in v0 — committing usage/survival to graph.json means every query dirties git and needs a counter-reconciling merge driver; premature without the cloud sharing service
