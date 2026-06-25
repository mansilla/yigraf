---
family: intent
id: int:memory-maturity
status: proposed
type: requirement
---
## Requirement
yigraf SHALL earn a memory's certainty behaviorally — promoting it from working to settled after it survives K boundaries un-superseded — and SHALL garbage-collect pure churn while retaining referenced rejected alternatives.

## Scenarios
- Given a memory un-superseded across K commit boundaries, When the graph is rebuilt, Then it is settled and ranks higher.
- Given a superseded memory with no refs and no usage, When GC runs, Then it is deleted; if it was referenced, Then it is kept as a rejected-alternative.

## Design (how)
survival/usage/last_seen are authoritative in graph.json and preserved across rebuilds (edge-derived counters recomputed, runtime counters kept); a union-merge driver reconciles branches (max survival / latest last_seen).
