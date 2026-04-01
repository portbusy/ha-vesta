"""The Vesta integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, CONF_ENTRY_TYPE, ENTRY_TYPE_GLOBAL, CONF_BOILER_ENTITY, CONF_BOILER_OFFSET
from .store import ScheduleStore
from .api import async_setup_api
from .panel import async_setup_panel

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["climate", "sensor"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Must match ConfigFlow.VERSION in config_flow.py
_CURRENT_VERSION = 7


class BoilerCoordinator:
    """Controls a central boiler based on aggregate room heating demand.

    At the end of each room tick, the room calls async_update() with the
    full list of room entities. The coordinator looks at every room's
    current heating state and decides whether to turn the boiler on or off
    (and, for climate boiler entities, what flow temperature to request).

    Approach B: Vesta owns the boiler entity directly and issues service
    calls rather than relying on an external automation.
    """

    def __init__(
        self, hass: HomeAssistant, boiler_entity_id: str, offset: float
    ) -> None:
        self._hass = hass
        self._boiler_id = boiler_entity_id
        self._offset = offset
        self._last_boiler_on: bool | None = None
        self._last_flow_temp: float | None = None

    async def async_update(self, rooms: list) -> None:
        """Update boiler state based on current heating demand across all rooms."""
        active_setpoints: list[float] = []
        any_heating = False

        for room in rooms:
            # Use the per-entity state dict that climate.py maintains
            heater_states = getattr(room, "_heater_states", {})
            if any(heater_states.values()):
                any_heating = True
                target = getattr(room, "_target_temp", None)
                if target is None:
                    target = room.comfort_temp
                active_setpoints.append(float(target))

        domain = self._boiler_id.split(".")[0]

        if domain == "climate":
            if any_heating:
                flow_temp = min(max(active_setpoints) + self._offset, 80.0)
            else:
                flow_temp = None

            boiler_on = any_heating
            boiler_changed = self._last_boiler_on != boiler_on
            temp_changed = boiler_on and flow_temp != self._last_flow_temp

            if boiler_changed or temp_changed:
                try:
                    if boiler_on:
                        await self._hass.services.async_call(
                            "climate",
                            "set_hvac_mode",
                            {"entity_id": self._boiler_id, "hvac_mode": "heat"},
                        )
                        await self._hass.services.async_call(
                            "climate",
                            "set_temperature",
                            {"entity_id": self._boiler_id, "temperature": flow_temp},
                        )
                    else:
                        await self._hass.services.async_call(
                            "climate",
                            "set_hvac_mode",
                            {"entity_id": self._boiler_id, "hvac_mode": "off"},
                        )
                except Exception:
                    _LOGGER.exception("Error updating boiler %s", self._boiler_id)
                    return  # Don't update internal state on failure
                self._last_boiler_on = boiler_on
                self._last_flow_temp = flow_temp if boiler_on else None
        else:
            # Switch or input_boolean: simple on/off
            if self._last_boiler_on != any_heating:
                try:
                    await self._hass.services.async_call(
                        "homeassistant",
                        "turn_on" if any_heating else "turn_off",
                        {"entity_id": self._boiler_id},
                    )
                except Exception:
                    _LOGGER.exception("Error updating boiler %s", self._boiler_id)
                    return
                self._last_boiler_on = any_heating


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entries from older schema versions to the current one."""
    from .const import (
        ENTRY_TYPE_GLOBAL,
        CONF_ENTRY_TYPE,
        CONF_VACATION_ENTITY,
        CONF_VACATION_STATE,
        CONF_HEATING_SEASON_ENTITY,
        CONF_HEATING_SEASON_ACTIVE,
        CONF_HEATING_SEASON_OFFMODE,
        CONF_BOILER_ENTITY,
        CONF_BOILER_OFFSET,
        CONF_SCHEDULE_SOURCE,
        CONF_VESTA_SCHEDULE_ID,
        CONF_MANUAL_OVERRIDE_MODE,
        CONF_MANUAL_OVERRIDE_HOURS,
        CONF_AVG_SPEED,
        CONF_WINDOW_DELAY,
        SEASON_OFFMODE_OPEN,
        MANUAL_OVERRIDE_TIMER,
        SCHEDULE_SOURCE_ENTITY,
    )
    _LOGGER.debug(
        "Migrating Vesta config entry from version %s to %s",
        config_entry.version,
        _CURRENT_VERSION,
    )
    data = dict(config_entry.data)
    is_global = data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL
    v = config_entry.version

    # v1 → v2: vacation entity support added
    if v < 2:
        data.setdefault(CONF_VACATION_STATE, False)
        data.setdefault(CONF_VACATION_ENTITY, None)

    # v2 → v3: heating season support added
    if v < 3:
        data.setdefault(CONF_HEATING_SEASON_ACTIVE, True)
        data.setdefault(CONF_HEATING_SEASON_ENTITY, None)
        data.setdefault(CONF_HEATING_SEASON_OFFMODE, SEASON_OFFMODE_OPEN)

    # v3 → v4: boiler coordinator support added
    if v < 4 and is_global:
        data.setdefault(CONF_BOILER_ENTITY, None)
        data.setdefault(CONF_BOILER_OFFSET, 5.0)

    # v4 → v5: Vesta native schedule source added
    if v < 5:
        data.setdefault(CONF_SCHEDULE_SOURCE, SCHEDULE_SOURCE_ENTITY)
        data.setdefault(CONF_VESTA_SCHEDULE_ID, None)

    # v5 → v6: manual override mode options added
    if v < 6 and is_global:
        data.setdefault(CONF_MANUAL_OVERRIDE_MODE, MANUAL_OVERRIDE_TIMER)
        data.setdefault(CONF_MANUAL_OVERRIDE_HOURS, 2.0)
        data.setdefault(CONF_AVG_SPEED, 50.0)

    # v6 → v7: window delay added per-room
    if v < 7 and not is_global:
        data.setdefault(CONF_WINDOW_DELAY, 0)

    hass.config_entries.async_update_entry(
        config_entry, data=data, version=_CURRENT_VERSION
    )
    _LOGGER.info(
        "Successfully migrated Vesta config entry '%s' from v%s to v%s",
        config_entry.title,
        v,
        _CURRENT_VERSION,
    )
    return True


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Vesta component."""
    hass.data.setdefault(
        DOMAIN,
        {
            "global": None,
            "rooms": [],
            "climate_entities_by_entry": {},
            "boiler_coordinator": None,
            "schedule_store": None,
        },
    )

    # Initialize persistent schedule store
    store = ScheduleStore(hass)
    await store.async_load()
    hass.data[DOMAIN]["schedule_store"] = store

    # Register WebSocket API and sidebar panel
    async_setup_api(hass)
    await async_setup_panel(hass)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Vesta entry."""
    hass.data.setdefault(
        DOMAIN,
        {
            "global": None,
            "rooms": [],
            "climate_entities_by_entry": {},
            "boiler_coordinator": None,
            "schedule_store": None,
        },
    )
    hass.data[DOMAIN].setdefault("climate_entities_by_entry", {})
    hass.data[DOMAIN].setdefault("boiler_coordinator", None)
    hass.data[DOMAIN].setdefault("schedule_store", None)

    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
        hass.data[DOMAIN]["global"] = entry
        boiler_id = entry.data.get(CONF_BOILER_ENTITY)
        if boiler_id:
            offset = float(entry.data.get(CONF_BOILER_OFFSET, 5.0))
            hass.data[DOMAIN]["boiler_coordinator"] = BoilerCoordinator(
                hass, boiler_id, offset
            )
        entry.async_on_unload(
            entry.add_update_listener(_async_global_options_updated)
        )
        for room in hass.data[DOMAIN]["rooms"]:
            if hasattr(room, "async_write_ha_state"):
                room.async_write_ha_state()
            if hasattr(room, "_async_tick"):
                hass.async_create_task(room._async_tick(None))
        return True

    # Climate must be set up before sensor so that sensor.py can find the entity.
    await hass.config_entries.async_forward_entry_setups(entry, ["climate"])
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    entry.async_on_unload(
        entry.add_update_listener(_async_room_options_updated)
    )
    return True


async def _async_global_options_updated(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Refresh event listeners on all room entities when global config changes."""
    # Recreate the boiler coordinator in case boiler entity or offset changed
    boiler_id = entry.data.get(CONF_BOILER_ENTITY)
    if boiler_id:
        offset = float(entry.data.get(CONF_BOILER_OFFSET, 5.0))
        hass.data[DOMAIN]["boiler_coordinator"] = BoilerCoordinator(
            hass, boiler_id, offset
        )
    else:
        hass.data[DOMAIN]["boiler_coordinator"] = None

    for room in hass.data[DOMAIN].get("rooms", []):
        if hasattr(room, "_setup_listeners"):
            room._setup_listeners()


async def _async_room_options_updated(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload a room entry when its config changes so new entities/sensors take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entry."""
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
        hass.data[DOMAIN]["global"] = None
        hass.data[DOMAIN]["boiler_coordinator"] = None
        return True

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
