"""Config flow for Vesta climate controller."""
from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

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
    """Handle a config flow for Vesta."""

    VERSION = 6

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        if user_input is not None:
            if user_input[CONF_ENTRY_TYPE] == ENTRY_TYPE_GLOBAL:
                return await self.async_step_global()
            return await self.async_step_room()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ENTRY_TYPE, default=ENTRY_TYPE_ROOM): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=ENTRY_TYPE_ROOM, label="Add a new Room"),
                            selector.SelectOptionDict(value=ENTRY_TYPE_GLOBAL, label="Configure Global Defaults"),
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }),
        )

    async def async_step_global(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle global settings."""
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
                    selector.SelectSelectorConfig(
                        options=["on", "off"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
        )

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle room settings."""
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
                vol.Required(CONF_OVERRIDE_PRESENCE, default=False): selector.BooleanSelector(),
                vol.Optional(CONF_PRESENCE_SENSORS): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="person", multiple=True)
                ),
                vol.Required(CONF_OVERRIDE_SCHEDULE, default=False): selector.BooleanSelector(),
                vol.Optional(CONF_SCHEDULE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="schedule")
                ),
                vol.Required(CONF_OVERRIDE_WEATHER, default=False): selector.BooleanSelector(),
                vol.Optional(CONF_WEATHER): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="weather")
                ),
                vol.Required(CONF_OVERRIDE_COMFORT, default=False): selector.BooleanSelector(),
                vol.Optional(CONF_COMFORT_TEMP, default=21.0): vol.Coerce(float),
                vol.Required(CONF_OVERRIDE_AWAY, default=False): selector.BooleanSelector(),
                vol.Optional(CONF_AWAY_TEMP, default=15.0): vol.Coerce(float),
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SmartClimateProOptionsFlow:
        """Get the options flow."""
        return SmartClimateProOptionsFlow(config_entry)


class SmartClimateProOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Vesta."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        entry_type = self.config_entry.data.get(CONF_ENTRY_TYPE)

        if entry_type == ENTRY_TYPE_GLOBAL:
            return await self.async_step_global(user_input)
        return await self.async_step_room(user_input)

    async def async_step_global(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Update global settings."""
        if user_input is not None:
            # We update the entry data directly as Vesta uses it
            new_data = {**self.config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return self.async_create_entry(title="", data={})

        current = self.config_entry.data
        return self.async_show_form(
            step_id="global",
            data_schema=vol.Schema({
                vol.Required(CONF_COMFORT_TEMP, default=current.get(CONF_COMFORT_TEMP, 21.0)): vol.Coerce(float),
                vol.Required(CONF_ECO_TEMP, default=current.get(CONF_ECO_TEMP, 18.0)): vol.Coerce(float),
                vol.Required(CONF_AWAY_TEMP, default=current.get(CONF_AWAY_TEMP, 15.0)): vol.Coerce(float),
                vol.Required(CONF_AVG_SPEED, default=current.get(CONF_AVG_SPEED, 50.0)): vol.Coerce(float),
                vol.Optional(CONF_PRESENCE_SENSORS, default=current.get(CONF_PRESENCE_SENSORS, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="person", multiple=True)
                ),
                vol.Optional(CONF_SCHEDULE, default=current.get(CONF_SCHEDULE)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="schedule")
                ),
                vol.Optional(CONF_WEATHER, default=current.get(CONF_WEATHER)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="weather")
                ),
                vol.Optional(CONF_OVERRIDE_SWITCH, default=current.get(CONF_OVERRIDE_SWITCH)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["input_boolean", "switch"])
                ),
                vol.Optional(CONF_VACATION_STATE, default=current.get(CONF_VACATION_STATE, "on")): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["on", "off"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
        )

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Update room settings."""
        if user_input is not None:
            new_data = {**self.config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return self.async_create_entry(title="", data={})

        current = self.config_entry.data
        return self.async_show_form(
            step_id="room",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=current.get(CONF_NAME, DEFAULT_NAME)): str,
                vol.Required(CONF_HEATER_ENTITIES, default=current.get(CONF_HEATER_ENTITIES, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["climate", "switch"], multiple=True)
                ),
                vol.Required(CONF_SENSOR, default=current.get(CONF_SENSOR)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(CONF_WINDOW_SENSOR, default=current.get(CONF_WINDOW_SENSOR)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor", device_class="window")
                ),
                vol.Required(CONF_OVERRIDE_PRESENCE, default=current.get(CONF_OVERRIDE_PRESENCE, False)): selector.BooleanSelector(),
                vol.Optional(CONF_PRESENCE_SENSORS, default=current.get(CONF_PRESENCE_SENSORS, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="person", multiple=True)
                ),
                vol.Required(CONF_OVERRIDE_SCHEDULE, default=current.get(CONF_OVERRIDE_SCHEDULE, False)): selector.BooleanSelector(),
                vol.Optional(CONF_SCHEDULE, default=current.get(CONF_SCHEDULE)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="schedule")
                ),
                vol.Required(CONF_OVERRIDE_WEATHER, default=current.get(CONF_OVERRIDE_WEATHER, False)): selector.BooleanSelector(),
                vol.Optional(CONF_WEATHER, default=current.get(CONF_WEATHER)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="weather")
                ),
                vol.Required(CONF_OVERRIDE_COMFORT, default=current.get(CONF_OVERRIDE_COMFORT, False)): selector.BooleanSelector(),
                vol.Optional(CONF_COMFORT_TEMP, default=current.get(CONF_COMFORT_TEMP, 21.0)): vol.Coerce(float),
                vol.Required(CONF_OVERRIDE_AWAY, default=current.get(CONF_OVERRIDE_AWAY, False)): selector.BooleanSelector(),
                vol.Optional(CONF_AWAY_TEMP, default=current.get(CONF_AWAY_TEMP, 15.0)): vol.Coerce(float),
            }),
        )
