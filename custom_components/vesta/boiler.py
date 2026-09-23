"""Serialize and reconcile central boiler commands."""
from __future__ import annotations

import asyncio
import logging

from .temperature import finite_float, native_target

_LOGGER = logging.getLogger(__name__)


class BoilerCoordinator:
    """Control the boiler from the current aggregate room demand."""

    def __init__(self, hass, boiler_entity_id: str, offset: float) -> None:
        self._hass = hass
        self._boiler_id = boiler_entity_id
        self._offset = finite_float(offset, 5.0)
        self._last_boiler_on = None
        self._last_flow_temp = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def async_update(self, rooms: list) -> None:
        """Re-read demand inside the lock; cache only completed service calls."""
        async with self._lock:
            active = [] if self._closed else [room for room in rooms if room.boiler_demand]
            desired_on = bool(active)
            state = self._hass.states.get(self._boiler_id)
            if state is not None and state.state in ("unavailable", "unknown"):
                self._last_boiler_on = None
                self._last_flow_temp = None
                return
            domain = self._boiler_id.split(".")[0]
            thermostat = domain == "climate"
            actual_on = None
            if state is not None:
                actual_on = (
                    state.state == "heat" if thermostat
                    else state.state not in ("off", "unknown", "unavailable")
                )
            changed = self._last_boiler_on != desired_on or (
                actual_on is not None and actual_on != desired_on
            )
            try:
                flow = None
                if thermostat and desired_on:
                    target = max(
                        finite_float(room.boiler_target_temperature, 21.0)
                        for room in active
                    )
                    flow = native_target(
                        min(80.0, max(5.0, target + self._offset)), state,
                        maximum=80.0, hass=self._hass,
                    )
                actual_target = finite_float(state.attributes.get("temperature")) if state else None
                temp_changed = thermostat and desired_on and (
                    self._last_flow_temp != flow
                    or (actual_target is not None and abs(actual_target - flow) > 0.01)
                )
                if changed:
                    if thermostat:
                        await self._hass.services.async_call(
                            "climate", "set_hvac_mode",
                            {"entity_id": self._boiler_id, "hvac_mode": "heat" if desired_on else "off"},
                            blocking=True,
                        )
                    else:
                        await self._hass.services.async_call(
                            "homeassistant", "turn_on" if desired_on else "turn_off",
                            {"entity_id": self._boiler_id}, blocking=True,
                        )
                if thermostat and desired_on and (changed or temp_changed):
                    await self._hass.services.async_call(
                        "climate", "set_temperature",
                        {"entity_id": self._boiler_id, "temperature": flow}, blocking=True,
                    )
            except Exception:
                self._last_boiler_on = None
                self._last_flow_temp = None
                _LOGGER.exception("Error updating boiler %s; will retry", self._boiler_id)
                return
            self._last_boiler_on = desired_on
            self._last_flow_temp = flow

    async def async_shutdown(self):
        """Stop the boiler and reject heat demand from any queued updates."""
        self._closed = True
        await self.async_update([])
