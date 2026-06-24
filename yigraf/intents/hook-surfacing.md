---
family: intent
id: int:hook-surfacing
status: proposed
type: requirement
---
## Requirement
yigraf SHALL surface governing intent and drift when a governed file is edited, and stay silent otherwise.

## Scenarios
- Given an edit to a governed, drifted file, When PostToolUse fires, Then the reconcile message is injected.
- Given an edit to unrelated code, When PostToolUse fires, Then nothing is injected.
