---
concerns:
- anchor: 609f477abc7f3b31e72ae016815ad13bfd7cc2473d3016c35e56d150ec851df3
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/retrieval.py#_capture_gaps
family: memory
id: mem:011
maturity: working
provenance:
  source: cli
serves:
- int:enforceable-link
status: active
supersedes: []
type: decision
---
## Capture-gap legibility: surface done tasks with no implements link, advisory not gating

**Why:** yigraf's read path is push (hooks inject) but its write path is pull (link/remember are opt-in), so an undisciplined agent silently starves the graph; making the decay legible in context+SessionStart lets the agent self-correct, while staying advisory (like R9c reconcile) honors fail-open/silence-as-feature

**Rejected:** auto-writing memory/links on edit (pollutes the graph, breaks files-are-truth quality); or hard-gating done-without-link in the drift CLI (too aggressive — a done task needn't always declare a symbol)
