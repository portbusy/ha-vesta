"""The Vesta integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_ENTRY_TYPE, ENTRY_TYPE_GLOBAL

PLATFORMS: list[str] = ["climate"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Vesta entry."""
    hass.data.setdefault(DOMAIN, {"global": None, "rooms": []})
    
    # If this is the global settings entry
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
        hass.data[DOMAIN]["global"] = entry
        # Notify rooms to update their state if global settings changed
        for room in hass.data[DOMAIN]["rooms"]:
            room.async_write_ha_state()
        return True

    # If this is a room entry
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entry."""
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
        hass.data[DOMAIN]["global"] = None
        return True
        
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
