---
attestation: agent
concerns:
- anchor: 673c38a2e857fe0cbac4994f21216a97493b4844636325574fd5bf3b370d55aa
  anchor_algo: astnorm-v1
  sym: sym:src/thermostat/control.py#target_temperature
family: memory
grounding: inferred
id: mem:97d8860a4b8b0996
maturity: working
provenance:
  source: cli
serves: []
status: active
supersedes: []
type: decision
---
## Occupancy comes from the motion sensor on the ceiling

**Why:** The ceiling sensor is what the installer fitted, and nothing else reports presence.
