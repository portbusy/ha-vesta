"""The Vesta integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, CONF_ENTRY_TYPE, ENTRY_TYPE_GLOBAL

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["climate", "sensor"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Must match ConfigFlow.VERSION in config_flow.py
_CURRENT_VERSION = 7


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entries from older schema versions to the current one."""
    _LOGGER.debug(
        "Migrating Vesta config entry from version %s to %s",
        config_entry.version,
        _CURRENT_VERSION,
    )
    hass.config_entries.async_update_entry(config_entry, version=_CURRENT_VERSION)
    return True


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Vesta component."""
    hass.data.setdefault(DOMAIN, {"global": None, "rooms": [], "climate_entities_by_entry": {}})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Vesta entry."""
    hass.data.setdefault(DOMAIN, {"global": None, "rooms": [], "climate_entities_by_entry": {}})
    hass.data[DOMAIN].setdefault("climate_entities_by_entry", {})

    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
        hass.data[DOMAIN]["global"] = entry
        entry.async_on_unload(
            entry.add_update_listener(_async_global_options_updated)
        )
        for room in hass.data[DOMAIN]["rooms"]:
            if hasattr(room, "async_write_ha_state"):
                room.async_write_ha_state()
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
        return True

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
