"""The Vesta integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, CONF_ENTRY_TYPE, ENTRY_TYPE_GLOBAL

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["climate"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Vesta component."""
    hass.data.setdefault(DOMAIN, {"global": None, "rooms": []})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Vesta entry."""
    hass.data.setdefault(DOMAIN, {"global": None, "rooms": []})

    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
        hass.data[DOMAIN]["global"] = entry
        for room in hass.data[DOMAIN]["rooms"]:
            if hasattr(room, "async_write_ha_state"):
                room.async_write_ha_state()
        return True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entry."""
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
        hass.data[DOMAIN]["global"] = None
        return True

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)