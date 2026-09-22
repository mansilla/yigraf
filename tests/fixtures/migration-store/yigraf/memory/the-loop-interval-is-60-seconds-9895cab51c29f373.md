---
attestation: agent
concerns:
- anchor: e09e2e7cd121e1572b8797af83107e9a4ebb8e7dd0859ab9ca025471ec9e11c3
  anchor_algo: file-sha256-v1
  sym: file:deploy.yml
family: memory
grounding: inferred
id: mem:9895cab51c29f373
maturity: working
provenance:
  source: cli
serves: []
status: superseded
superseded_by: mem:7f39b84c31c7543d
supersedes:
- mem:eb71714ab5349e2f
type: decision
---
## The loop interval is 60 seconds

**Why:** At 30 seconds the boiler short-cycled; the plant's thermal time constant is minutes, so a faster loop bought nothing and cost relay wear.
