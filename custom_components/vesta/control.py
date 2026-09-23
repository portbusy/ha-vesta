"""One control decision shared by actuators, boiler demand and UI state."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ControlDecision:
    target: float | None
    climate_active: bool
    heat_demand: bool
    reason: str


def decide_control(
    *, temperature: float | None, target: float, enabled: bool,
    window_open: bool, emergency: bool, heating_season: bool,
    offmode: str, vacation: bool, failsafe_pulse: bool,
) -> ControlDecision:
    """Apply the documented heating priorities without mutating entity state."""
    if emergency:
        return ControlDecision(35.0, True, True, "emergency_heat")
    if temperature is None:
        return ControlDecision(
            5.0 if failsafe_pulse else None, failsafe_pulse,
            failsafe_pulse, "sensor_failsafe",
        )
    if temperature < 5.0:
        return ControlDecision(5.0, True, True, "frost_protection")
    if not heating_season:
        if offmode == "open":
            return ControlDecision(5.0 if vacation else 35.0, True, False, "heating_season_off")
        if offmode == "frost":
            return ControlDecision(7.0, True, temperature < 7.8, "off_season_frost")
        return ControlDecision(None, False, False, "heating_season_off")
    if not enabled:
        return ControlDecision(target, False, False, "hvac_off")
    if window_open:
        return ControlDecision(target, False, False, "window_open")
    return ControlDecision(target, True, temperature < target - 0.2, "normal")
