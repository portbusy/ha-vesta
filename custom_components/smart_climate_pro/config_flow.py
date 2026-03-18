"""Config flow for Global and Room-based Climate Pro (Presence/Weather)."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_ENTRY_TYPE,
    ENTRY_TYPE_GLOBAL,
    ENTRY_TYPE_ROOM,
    CONF_HEATER_ENTITIES,
    CONF_SENSOR,
    CONF_WINDOW_SENSOR,
    CONF_PRESENCE_SENSORS,
    CONF_SCHEDULE,
    CONF_WEATHER,
    CONF_OVERRIDE_SWITCH,
    CONF_VACATION_STATE,
    CONF_NAME,
    CONF_COMFORT_TEMP,
    CONF_ECO_TEMP,
    CONF_AWAY_TEMP,
    CONF_AVG_SPEED,
    CONF_OVERRIDE_COMFORT,
    CONF_OVERRIDE_AWAY,
    CONF_OVERRIDE_PRESENCE,
    CONF_OVERRIDE_WEATHER,
    CONF_OVERRIDE_SCHEDULE,
    DEFAULT_NAME,
)

class SmartClimateProConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Config Flow for Global and Rooms."""

    VERSION = 6

    async def async_step_user(self, user_input=None):
        """First step: choose between adding a room or setting global defaults."""
        global_exists = any(entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL 
                           for entry in self._async_current_entries())

        options = ["room", "global"]
        return self.async_show_menu(step_id="user", menu_options=options)

    async def async_step_global(self, user_input=None):
        """Setup/Update global home settings."""
        if user_input is not None:
            user_input[CONF_ENTRY_TYPE] = ENTRY_TYPE_GLOBAL
            user_input[CONF_NAME] = "Global Home Settings"
            return self.async_create_entry(title="Home Settings", data=user_input)

        return self.async_show_form(
            step_id="global",
            data_schema=vol.Schema({
                vol.Required(CONF_COMFORT_TEMP, default=21.0): vol.Coerce(float),
                vol.Required(CONF_ECO_TEMP, default=18.0): vol.Coerce(float),
                vol.Required(CONF_AWAY_TEMP, default=15.0): vol.Coerce(float),
                vol.Required(CONF_AVG_SPEED, default=50.0): vol.Coerce(float),
                vol.Optional(CONF_PRESENCE_SENSORS): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="person", multiple=True)
                ),
                vol.Optional(CONF_SCHEDULE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="schedule")
                ),
                vol.Optional(CONF_WEATHER): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="weather")
                ),
                vol.Optional(CONF_OVERRIDE_SWITCH): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["input_boolean", "switch"])
                ),
                vol.Optional(CONF_VACATION_STATE, default="on"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=["on", "off"])
                ),
            }),
        )

    async def async_step_room(self, user_input=None):
        """Setup a specific room."""
        if user_input is not None:
            user_input[CONF_ENTRY_TYPE] = ENTRY_TYPE_ROOM
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        return self.async_show_form(
            step_id="room",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_HEATER_ENTITIES): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["climate", "switch"], multiple=True)
                ),
                vol.Required(CONF_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(CONF_WINDOW_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor", device_class="window")
                ),
                
                # Presence Override
                vol.Required(CONF_OVERRIDE_PRESENCE, default=False): bool,
                vol.Optional(CONF_PRESENCE_SENSORS): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="person", multiple=True)
                ),

                # Schedule Override
                vol.Required(CONF_OVERRIDE_SCHEDULE, default=False): bool,
                vol.Optional(CONF_SCHEDULE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="schedule")
                ),

                # Weather Override
                vol.Required(CONF_OVERRIDE_WEATHER, default=False): bool,
                vol.Optional(CONF_WEATHER): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="weather")
                ),

                # Temp Override
                vol.Required(CONF_OVERRIDE_COMFORT, default=False): bool,
                vol.Optional(CONF_COMFORT_TEMP, default=21.0): vol.Coerce(float),
                
                vol.Required(CONF_OVERRIDE_AWAY, default=False): bool,
                vol.Optional(CONF_AWAY_TEMP, default=15.0): vol.Coerce(float),
            }),
        )
