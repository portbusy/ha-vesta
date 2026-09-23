"""Finite temperature values and conversions at the device boundary."""
from __future__ import annotations

import math

from homeassistant.const import UnitOfTemperature
from homeassistant.util.unit_conversion import TemperatureConverter


def finite_float(value, default=None):
    """Return a finite number, excluding booleans and unavailable values."""
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def temperature_unit(state, hass=None, *, climate=False):
    """Climate states/services use HA's configured unit, not the device unit."""
    if climate or (state and getattr(state, "entity_id", "").startswith("climate.")):
        units = getattr(getattr(hass, "config", None), "units", None)
        if units is not None:
            return units.temperature_unit
    attrs = state.attributes if state else {}
    return attrs.get(
        "temperature_unit", attrs.get("unit_of_measurement", UnitOfTemperature.CELSIUS)
    )


def as_celsius(state, attribute=None, *, hass=None):
    """Read an available sensor, weather or climate temperature in Celsius."""
    if state is None or state.state in ("unknown", "unavailable"):
        return None
    value = finite_float(state.attributes.get(attribute) if attribute else state.state)
    if value is None:
        return None
    try:
        return TemperatureConverter.convert(
            value, temperature_unit(state, hass), UnitOfTemperature.CELSIUS
        )
    except ValueError:
        return None


def native_target(celsius, state, *, maximum=35.0, hass=None):
    """Convert a Celsius setpoint to climate service units and capabilities."""
    unit = temperature_unit(state, hass, climate=True)
    def convert(value):
        return TemperatureConverter.convert(value, UnitOfTemperature.CELSIUS, unit)

    attrs = state.attributes if state else {}
    lower = finite_float(attrs.get("min_temp"), convert(5.0))
    upper = finite_float(attrs.get("max_temp"), convert(maximum))
    if lower > upper:
        raise ValueError("Device minimum temperature exceeds its maximum")
    value = min(upper, max(lower, convert(celsius)))
    step = finite_float(attrs.get("target_temp_step"))
    if step is not None and step > 0:
        value = round(value / step) * step
    return round(min(upper, max(lower, value)), 6)
