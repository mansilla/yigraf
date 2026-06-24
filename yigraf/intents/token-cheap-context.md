---
family: intent
id: int:token-cheap-context
status: proposed
type: requirement
---
## Requirement
yigraf SHALL answer a query with a token-budgeted slice of the graph rendered as locators and signatures, not source.

## Scenarios
- Given a query, When context is retrieved, Then the implementing symbols appear as signatures and the output stays under budget.
