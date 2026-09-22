# Thermostat design

## Control loop

The loop runs once a minute and is deliberately slow.

## Safety

A failed sensor read must hold the last duty cycle rather than falling to zero.
