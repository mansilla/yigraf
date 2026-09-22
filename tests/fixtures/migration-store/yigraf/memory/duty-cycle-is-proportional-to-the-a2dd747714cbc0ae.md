---
attestation: agent
concerns:
- anchor: 1bc82f9bd68c62d83b1385347d2c7db9f1450ede908463343cf9d4b2cebb7c8f
  anchor_algo: astnorm-v1
  sym: sym:src/thermostat/control.py#duty_cycle
family: memory
grounding: inferred
id: mem:a2dd747714cbc0ae
maturity: working
provenance:
  source: cli
serves:
- int:comfort-band
status: active
supersedes: []
type: decision
---
## Duty cycle is proportional to the error with a fixed gain of 0.25

**Why:** The bench rig settled inside the comfort band with proportional action alone, so the integral term would have been untested authority rather than needed control.

**Rejected:** A PI controller — it removes a steady-state offset this plant does not have, and its wind-up needs a clamp nobody had measured.
