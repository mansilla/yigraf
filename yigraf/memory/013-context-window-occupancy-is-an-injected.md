---
concerns:
- anchor: 0f9367e1084fbb8254e51e7c38f4a72d82bdab2759e1500e0423681e277964ca
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/status.py#compute_status
family: memory
id: mem:013
maturity: working
provenance:
  source: cli
serves:
- int:status-surface
status: active
supersedes: []
type: decision
---
## Context-window occupancy is an injected, host-supplied datum (--ctx-used/--ctx-limit); the status core never reads a transcript or host API

**Why:** no host hands a CLI its context-window usage (mirrors mem:005 for embeddings), so reading it can't live in the host-agnostic core without coupling yigraf to one host's transcript format. Making it an optional injected param keeps compute_status pure and lets a per-host adapter fill it; a host that can't supply it just omits the ctx segment and the rest still renders.

**Rejected:** read transcript_path in the core to compute context usage — couples the agnostic core to Claude Code's internal JSONL format (fragile across versions)
