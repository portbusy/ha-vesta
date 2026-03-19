"""The Vesta integration."""
from __future__ import annotations

import json
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN, CONF_ENTRY_TYPE, ENTRY_TYPE_GLOBAL, CONF_SCHEDULE_SLOTS

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["climate"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]
WEEKENDS = ["saturday", "sunday"]
ALL_DAYS = WEEKDAYS + WEEKENDS


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Vesta component (register frontend card)."""
    hass.data.setdefault(DOMAIN, {"global": None, "rooms": []})

    # Register the Lovelace card JS from our www folder
    await hass.http.async_register_static_paths([
        StaticPathConfig(
            url_path="/local/vesta/vesta-schedule-card.js",
            path=hass.config.path(
                "custom_components/vesta/www/vesta-schedule-card.js"
            ),
            cache_headers=False,
        )
    ])

    # Register as a Lovelace resource
    # Users still need to add the resource in Lovelace config, but we log
    # the path for convenience
    _LOGGER.info(
        "Vesta schedule card available at /local/vesta/vesta-schedule-card.js"
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Vesta entry."""
    hass.data.setdefault(DOMAIN, {"global": None, "rooms": []})

    # If this is the global settings entry
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
        hass.data[DOMAIN]["global"] = entry
        # Notify rooms to update their state if global settings changed
        for room in hass.data[DOMAIN]["rooms"]:
            if hasattr(room, "async_write_ha_state"):
                room.async_write_ha_state()
        # Register services once
        await _async_register_services(hass)
        return True

    # If this is a room entry
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Register services (idempotent)
    await _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entry."""
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
        hass.data[DOMAIN]["global"] = None
        return True

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register vesta.set_schedule and vesta.clear_schedule services."""
    if hass.services.has_service(DOMAIN, "set_schedule"):
        return  # Already registered

    async def _handle_set_schedule(call: ServiceCall) -> None:
        """Handle vesta.set_schedule."""
        entity_ids = call.data.get("entity_id", [])
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]
        day = call.data["day"]
        blocks_raw = call.data["blocks"]

        # Parse blocks
        try:
            blocks = json.loads(blocks_raw) if isinstance(blocks_raw, str) else blocks_raw
        except (json.JSONDecodeError, TypeError) as exc:
            _LOGGER.error("Invalid blocks JSON: %s", exc)
            return

        # Validate blocks
        if not isinstance(blocks, list):
            _LOGGER.error("Blocks must be a list")
            return
        for b in blocks:
            if "start" not in b or "temp" not in b:
                _LOGGER.error("Each block must have 'start' and 'temp': %s", b)
                return

        # Sort blocks by start time
        blocks.sort(key=lambda b: b["start"])

        # Determine which days to update
        if day == "weekdays":
            days = WEEKDAYS
        elif day == "weekends":
            days = WEEKENDS
        elif day == "all":
            days = ALL_DAYS
        else:
            days = [day]

        # Find matching rooms and update their schedule
        for room in hass.data[DOMAIN].get("rooms", []):
            if room.entity_id not in entity_ids:
                continue
            entry = room._entry
            new_data = dict(entry.data)
            schedule = dict(new_data.get(CONF_SCHEDULE_SLOTS, {}))
            for d in days:
                schedule[d] = blocks
            new_data[CONF_SCHEDULE_SLOTS] = schedule
            hass.config_entries.async_update_entry(entry, data=new_data)
            room.async_write_ha_state()
            _LOGGER.info("Schedule updated for %s: %s = %s", room.entity_id, days, blocks)

    async def _handle_clear_schedule(call: ServiceCall) -> None:
        """Handle vesta.clear_schedule."""
        entity_ids = call.data.get("entity_id", [])
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]
        day = call.data["day"]

        days = ALL_DAYS if day == "all" else [day]

        for room in hass.data[DOMAIN].get("rooms", []):
            if room.entity_id not in entity_ids:
                continue
            entry = room._entry
            new_data = dict(entry.data)
            schedule = dict(new_data.get(CONF_SCHEDULE_SLOTS, {}))
            for d in days:
                schedule.pop(d, None)
            new_data[CONF_SCHEDULE_SLOTS] = schedule
            hass.config_entries.async_update_entry(entry, data=new_data)
            room.async_write_ha_state()
            _LOGGER.info("Schedule cleared for %s: %s", room.entity_id, days)

    hass.services.async_register(
        DOMAIN,
        "set_schedule",
        _handle_set_schedule,
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_ids,
                vol.Required("day"): str,
                vol.Required("blocks"): str,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "clear_schedule",
        _handle_clear_schedule,
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_ids,
                vol.Required("day"): str,
            }
        ),
    )
