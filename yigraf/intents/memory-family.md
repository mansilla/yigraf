---
family: intent
id: int:memory-family
status: active
type: requirement
---
## Requirement
yigraf SHALL let an agent capture the reasoning behind a change as a durable memory node and re-surface it when the code it concerns changes.

## Scenarios
- Given a decision captured with --concerns <sym>, When that symbol's body later changes, Then yigraf surfaces a re-verify reconcile on the next touch.
- Given a superseded decision, When context is queried, Then the active decision out-ranks it but the superseded one stays available.

## Design (how)
Memory is one .md per node (memory/<seq>-<slug>.md); concerns reuses the implements drift machinery; capture is agent-asserted (no distillation backstop in M7).
