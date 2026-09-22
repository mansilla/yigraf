---
attestation: agent
concerns:
- anchor: 673c38a2e857fe0cbac4994f21216a97493b4844636325574fd5bf3b370d55aa
  anchor_algo: astnorm-v1
  sym: sym:src/thermostat/control.py#target_temperature
family: memory
grounding: inferred
id: mem:0de10abc25538fa3
maturity: working
provenance:
  source: cli
serves: []
status: active
supersedes: []
type: decision
---
## Occupancy is read from the PIR sensor

**Why:** The PIR is the only occupancy signal wired to the controller.
