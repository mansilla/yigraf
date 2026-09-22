"""A toy thermostat controller, existing to give the fixture real symbols to anchor to."""


def target_temperature(setpoint_c: float, occupancy: bool) -> float:
    """The temperature to aim for, in degrees Celsius."""
    return setpoint_c if occupancy else setpoint_c - 3.0


def duty_cycle(error_c: float, gain: float = 0.25) -> float:
    """Fraction of the interval to run the boiler, clamped to [0, 1]."""
    return max(0.0, min(1.0, error_c * gain))


class Schedule:
    """A weekly setpoint schedule."""

    def setpoint_at(self, hour: int) -> float:
        """The scheduled setpoint for an hour of the day, in degrees Celsius."""
        return 20.5 if 7 <= hour < 22 else 17.0
