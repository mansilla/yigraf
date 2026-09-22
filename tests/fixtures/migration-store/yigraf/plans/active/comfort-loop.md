---
edges:
  task:comfort-loop/1:
    implements:
    - anchor: 673c38a2e857fe0cbac4994f21216a97493b4844636325574fd5bf3b370d55aa
      anchor_algo: astnorm-v1
      sym: sym:src/thermostat/control.py#target_temperature
    tracks: int:comfort-band
  task:comfort-loop/2:
    implements:
    - anchor: 1bc82f9bd68c62d83b1385347d2c7db9f1450ede908463343cf9d4b2cebb7c8f
      anchor_algo: astnorm-v1
      sym: sym:src/thermostat/control.py#duty_cycle
  task:comfort-loop/3:
    implements:
    - anchor: e796dd786640a4226d2bdab556ed032854d8833c869b99b167c20e725f03e507
      anchor_algo: astnorm-v1
      sym: sym:src/thermostat/control.py#Schedule.setpoint_at
family: plan
id: plan:comfort-loop
---
# Close the comfort band

## Tasks
- [x] {#1} Compute the target temperature from setpoint and occupancy
- [ ] {#2} Convert the error to a boiler duty cycle
- [x] {#3} Read the schedule for the current hour
