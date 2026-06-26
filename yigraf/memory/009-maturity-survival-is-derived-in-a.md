---
concerns:
- anchor: a63c7f8f20cf0f98747c769a7a85ccdcd60bcb8a4b82f610340674ab52728ba7
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/counters.py#apply_maturity
family: memory
id: mem:009
maturity: working
provenance:
  source: cli
serves:
- int:memory-maturity
status: active
supersedes: []
type: decision
---
## maturity survival is derived in a flat, HEAD-cached handful of git calls (not per-node) — preserving R2 semantics

**Why:** the per-node fan-out (~2N git calls, on the hot PostToolUse path) was a 🔴 perf caveat; _survival_map batches all paths into 2 calls (one topo-order log for commit order + one batched --diff-filter=A --name-status for intros) and the result is memoized by HEAD in the structure cache, since an edit never moves HEAD — so the hook path is 1 rev-parse and 0 walks. Survival stays byte-identical so graph.json is still recomputable

**Rejected:** exact per-intro rev-list --count (keeps O(N) git calls on every HEAD change); skipping maturity in the hook path (would make maturity stale between commits). The topo-order distance under-counts merged side branches but only ever matures a node *slower* than strict intro..HEAD — conservative, and exact on linear history
