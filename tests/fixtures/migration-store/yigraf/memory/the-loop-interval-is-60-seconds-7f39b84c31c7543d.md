---
attestation: agent
concerns:
- anchor: e09e2e7cd121e1572b8797af83107e9a4ebb8e7dd0859ab9ca025471ec9e11c3
  anchor_algo: file-sha256-v1
  sym: file:deploy.yml
family: memory
grounding: inferred
id: mem:7f39b84c31c7543d
maturity: working
provenance:
  source: cli
serves: []
status: active
supersedes:
- mem:9895cab51c29f373
type: decision
---
## The loop interval is 60 seconds and is read from deploy.yml rather than compiled in

**Why:** The interval had two owners once the deployment config existed, and a value in two places disagrees the first time either moves.
