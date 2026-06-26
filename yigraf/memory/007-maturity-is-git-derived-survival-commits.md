---
concerns:
- anchor: 50db74c6f4eb553a5608542f6c76460c3908c28a86afc0c1467dcb857184dc00
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/counters.py#survival_of
family: memory
id: mem:007
maturity: working
provenance:
  source: cli
serves:
- int:memory-maturity
status: active
supersedes: []
type: decision
---
## maturity is git-derived: survival = commits since the memory artifact was introduced, recomputed each build, not a stored counter

**Why:** R2 wants maturity branch-cadence-independent and identical on every clone/CI; deriving it from git history (intro commit .. HEAD) makes it recomputable and merge-safe, so no per-session survival counter is stored or reconciled

**Rejected:** a stored survival counter bumped per build/commit — accumulates, diverges across machines, and needs a merge driver to reconcile
