---
family: intent
id: int:drift-detection
status: proposed
type: requirement
---
## Requirement
yigraf SHALL flag a linked symbol whose body changed since anchoring, and SHALL NOT flag a pure rename.

## Scenarios
- Given a linked symbol's body is edited, When drift is checked, Then soft drift is reported.
- Given a linked symbol is purely renamed, When drift is checked, Then it auto-re-anchors with no drift.
