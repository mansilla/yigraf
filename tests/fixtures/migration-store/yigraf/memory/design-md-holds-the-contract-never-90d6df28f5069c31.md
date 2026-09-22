---
attestation: agent
concerns:
- anchor: null
  anchor_algo: governs-v1
  sym: file:docs/design.md
family: memory
grounding: inferred
id: mem:90d6df28f5069c31
maturity: working
promotable: true
provenance:
  source: cli
serves: []
status: active
supersedes: []
type: constraint
---
## design.md holds the contract, never the measurements

**Why:** A document that mixes a contract with observations makes a reader guess which half is still true; the numbers live in MEASUREMENTS.md where they can carry a date.
