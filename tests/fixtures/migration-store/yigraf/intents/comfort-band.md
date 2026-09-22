---
family: intent
id: int:comfort-band
status: proposed
type: requirement
---
## Requirement
The controller SHALL hold the occupied setpoint within one degree Celsius

## Scenarios
- Given an occupied room at 18C and a setpoint of 20.5C, When the loop runs, Then the boiler duty cycle is positive

## Design (how)
A proportional term only; integral action was not needed at this authority.
