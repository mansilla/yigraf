---
concerns:
- anchor: 0f9367e1084fbb8254e51e7c38f4a72d82bdab2759e1500e0423681e277964ca
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/status.py#compute_status
family: memory
id: mem:012
maturity: working
provenance:
  source: cli
serves:
- int:status-surface
status: active
supersedes: []
type: decision
---
## Human-facing graph stats ride a separate ambient channel (the statusline), never the agent's hook injection

**Why:** the status surface targets the human principal, but the PostToolUse injection spends the AGENT's context/token budget — folding vanity stats there would violate design-law #2/#4 (output is for the agent's context; silence is a feature). A statusline is a separate UI region that costs the agent zero tokens, so it informs the user without taxing the agent's attention.

**Rejected:** fold a stats banner into the PostToolUse additionalContext — clutters the agent's context to inform the human, nags on routine edits
