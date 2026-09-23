"""The Vesta integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_BOILER_ENTITY,
    CONF_BOILER_OFFSET,
    CONF_ENTRY_TYPE,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
)
from .boiler import BoilerCoordinator
from .store import ScheduleStore
from .api import async_setup_api
from .panel import async_setup_panel
from .temperature import finite_float

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["climate", "sensor"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Must match ConfigFlow.VERSION in config_flow.py
_CURRENT_VERSION = 8


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
    if config_entry.version > _CURRENT_VERSION:
        _LOGGER.error("Cannot downgrade Vesta config version %s", config_entry.version)
        return False
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

    # v7 → v8: old migrations put "entity" on every room, although the
    # runtime inherited the global source unless override_schedule was set.
    # Preserve that behaviour before making explicit entity assignments work.
    if v < 8 and not is_global and data.get(CONF_SCHEDULE_SOURCE) == SCHEDULE_SOURCE_ENTITY:
        if not data.get("override_schedule"):
            data.pop(CONF_SCHEDULE_SOURCE, None)

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
        entry.async_on_unload(
            entry.add_update_listener(_async_global_options_updated)
        )
        await _async_global_options_updated(hass, entry)
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
    boiler_id = entry.data.get(CONF_BOILER_ENTITY)
    old = hass.data[DOMAIN].get("boiler_coordinator")
    if old and old._boiler_id != boiler_id:
        await old.async_shutdown()
        old = None
    if boiler_id:
        offset = finite_float(entry.data.get(CONF_BOILER_OFFSET), 5.0)
        if old:
            old._offset = offset
        hass.data[DOMAIN]["boiler_coordinator"] = old or BoilerCoordinator(hass, boiler_id, offset)
    else:
        hass.data[DOMAIN]["boiler_coordinator"] = None

    for room in hass.data[DOMAIN].get("rooms", []):
        if hasattr(room, "_setup_listeners"):
            room._setup_listeners()
        if hasattr(room, "_async_tick"):
            await room._async_tick(None)


async def _async_room_options_updated(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload a room entry when its config changes so new entities/sensors take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entry."""
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
        coordinator = hass.data[DOMAIN].get("boiler_coordinator")
        if coordinator:
            await coordinator.async_shutdown()
        hass.data[DOMAIN]["global"] = None
        hass.data[DOMAIN]["boiler_coordinator"] = None
        return True

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
