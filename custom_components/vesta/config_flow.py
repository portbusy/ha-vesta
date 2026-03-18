"""Config flow for Vesta climate controller."""
from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import (
    area_registry as ar,
    entity_registry as er,
    selector,
)

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
    CONF_AREA,
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

# --- Temp selector builder ---

def _temp_selector(min_val: float = 5.0, max_val: float = 35.0, step: float = 0.5) -> selector.NumberSelector:
    """Create a temperature NumberSelector."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=min_val,
            max=max_val,
            step=step,
            unit_of_measurement="°C",
            mode=selector.NumberSelectorMode.SLIDER,
        )
    )


# --- Override helpers ---

def _flatten_overrides(user_input: dict[str, Any]) -> dict[str, Any]:
    """Flatten the nested 'overrides' section into top-level keys."""
    flat = dict(user_input)
    overrides = flat.pop("overrides", None) or {}
    flat.update(overrides)
    return flat


def _validate_overrides(user_input: dict[str, Any], errors: dict[str, str]) -> None:
    """Validate that if an override is enabled, the corresponding entity is provided."""
    overrides = user_input.get("overrides") or {}
    if overrides.get(CONF_OVERRIDE_PRESENCE) and not overrides.get(CONF_PRESENCE_SENSORS):
        errors[CONF_PRESENCE_SENSORS] = "missing_presence_sensors"
    if overrides.get(CONF_OVERRIDE_SCHEDULE) and not overrides.get(CONF_SCHEDULE):
        errors[CONF_SCHEDULE] = "missing_schedule_entity"
    if overrides.get(CONF_OVERRIDE_WEATHER) and not overrides.get(CONF_WEATHER):
        errors[CONF_WEATHER] = "missing_weather_entity"


def _overrides_schema(defaults: dict[str, Any] | None = None) -> section:
    """Build the overrides section schema with optional defaults."""
    d = defaults or {}
    return section(
        vol.Schema({
            vol.Required(CONF_OVERRIDE_PRESENCE, default=d.get(CONF_OVERRIDE_PRESENCE, False)): selector.BooleanSelector(),
            vol.Optional(CONF_PRESENCE_SENSORS, default=d.get(CONF_PRESENCE_SENSORS, [])): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="person", multiple=True)
            ),
            vol.Required(CONF_OVERRIDE_SCHEDULE, default=d.get(CONF_OVERRIDE_SCHEDULE, False)): selector.BooleanSelector(),
            vol.Optional(CONF_SCHEDULE, default=d.get(CONF_SCHEDULE)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="schedule")
            ),
            vol.Required(CONF_OVERRIDE_WEATHER, default=d.get(CONF_OVERRIDE_WEATHER, False)): selector.BooleanSelector(),
            vol.Optional(CONF_WEATHER, default=d.get(CONF_WEATHER)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            vol.Required(CONF_OVERRIDE_COMFORT, default=d.get(CONF_OVERRIDE_COMFORT, False)): selector.BooleanSelector(),
            vol.Optional(CONF_COMFORT_TEMP, default=d.get(CONF_COMFORT_TEMP, 21.0)): _temp_selector(),
            vol.Required(CONF_OVERRIDE_AWAY, default=d.get(CONF_OVERRIDE_AWAY, False)): selector.BooleanSelector(),
            vol.Optional(CONF_AWAY_TEMP, default=d.get(CONF_AWAY_TEMP, 15.0)): _temp_selector(),
        }),
        {"collapsed": True},
    )


# --- Auto-discovery from area ---

def _discover_entities_for_area(hass, area_id: str) -> dict[str, Any]:
    """Find heaters, temp sensors, and window sensors in an area."""
    registry = er.async_get(hass)
    entities = er.async_entries_for_area(registry, area_id)

    heaters = []
    temp_sensor = None
    window_sensor = None

    for entry in entities:
        if entry.disabled:
            continue
        domain = entry.domain

        # Heaters: climate, switch, or water_heater entities
        if domain in ("climate", "switch", "water_heater"):
            heaters.append(entry.entity_id)

        # Temperature sensor
        if domain == "sensor" and entry.device_class == "temperature" and temp_sensor is None:
            temp_sensor = entry.entity_id

        # Window sensor
        if domain == "binary_sensor" and entry.device_class == "window" and window_sensor is None:
            window_sensor = entry.entity_id

    return {
        CONF_HEATER_ENTITIES: heaters,
        CONF_SENSOR: temp_sensor,
        CONF_WINDOW_SENSOR: window_sensor,
    }


class SmartClimateProConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Vesta."""

    VERSION = 7

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._area_id: str | None = None
        self._area_name: str | None = None
        self._discovered: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        if user_input is not None:
            if user_input[CONF_ENTRY_TYPE] == ENTRY_TYPE_GLOBAL:
                return await self.async_step_global()
            return await self.async_step_area()

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
                vol.Required(CONF_COMFORT_TEMP, default=21.0): _temp_selector(),
                vol.Required(CONF_ECO_TEMP, default=18.0): _temp_selector(),
                vol.Required(CONF_AWAY_TEMP, default=15.0): _temp_selector(),
                vol.Required(CONF_AVG_SPEED, default=50.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10, max=200, step=5,
                        unit_of_measurement="km/h",
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
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
                vol.Optional(CONF_VACATION_STATE, default=False): selector.BooleanSelector(),
            }),
        )

    async def async_step_area(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1 for room: let the user select an HA area to auto-discover entities."""
        if user_input is not None:
            self._area_id = user_input.get(CONF_AREA)
            if self._area_id:
                # Get area name from area registry
                area_reg = ar.async_get(self.hass)
                area = area_reg.async_get_area(self._area_id)
                self._area_name = area.name if area else self._area_id
                # Auto-discover entities
                self._discovered = _discover_entities_for_area(self.hass, self._area_id)
            return await self.async_step_room()

        return self.async_show_form(
            step_id="area",
            data_schema=vol.Schema({
                vol.Optional(CONF_AREA): selector.AreaSelector(),
            }),
        )

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle room settings, pre-populated from area discovery."""
        errors: dict[str, str] = {}
        if user_input is not None:
            _validate_overrides(user_input, errors)
            if not errors:
                flat_data = _flatten_overrides(user_input)
                flat_data[CONF_ENTRY_TYPE] = ENTRY_TYPE_ROOM
                if self._area_id:
                    flat_data[CONF_AREA] = self._area_id
                return self.async_create_entry(title=flat_data[CONF_NAME], data=flat_data)

        # Use discovered defaults from area, or empty
        d = self._discovered
        default_name = self._area_name or DEFAULT_NAME
        default_heaters = d.get(CONF_HEATER_ENTITIES, [])
        default_sensor = d.get(CONF_SENSOR)
        default_window = d.get(CONF_WINDOW_SENSOR)

        schema = {
            vol.Required(CONF_NAME, default=default_name): str,
        }

        # Heaters: pre-populate with discovered, but always required
        if default_heaters:
            schema[vol.Required(CONF_HEATER_ENTITIES, default=default_heaters)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["climate", "switch", "water_heater"], multiple=True)
            )
        else:
            schema[vol.Required(CONF_HEATER_ENTITIES)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["climate", "switch", "water_heater"], multiple=True)
            )

        # Temp sensor
        if default_sensor:
            schema[vol.Required(CONF_SENSOR, default=default_sensor)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            )
        else:
            schema[vol.Required(CONF_SENSOR)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            )

        # Window sensor
        if default_window:
            schema[vol.Optional(CONF_WINDOW_SENSOR, default=default_window)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", device_class="window")
            )
        else:
            schema[vol.Optional(CONF_WINDOW_SENSOR)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", device_class="window")
            )

        # Overrides section
        schema[vol.Required("overrides")] = _overrides_schema()

        return self.async_show_form(
            step_id="room",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SmartClimateProOptionsFlow:
        """Get the options flow."""
        return SmartClimateProOptionsFlow()


class SmartClimateProOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Vesta."""

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
            new_data = {**self.config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return self.async_create_entry(title="", data={})

        current = self.config_entry.data
        return self.async_show_form(
            step_id="global",
            data_schema=vol.Schema({
                vol.Required(CONF_COMFORT_TEMP, default=current.get(CONF_COMFORT_TEMP, 21.0)): _temp_selector(),
                vol.Required(CONF_ECO_TEMP, default=current.get(CONF_ECO_TEMP, 18.0)): _temp_selector(),
                vol.Required(CONF_AWAY_TEMP, default=current.get(CONF_AWAY_TEMP, 15.0)): _temp_selector(),
                vol.Required(CONF_AVG_SPEED, default=current.get(CONF_AVG_SPEED, 50.0)): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10, max=200, step=5,
                        unit_of_measurement="km/h",
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
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
                vol.Optional(CONF_VACATION_STATE, default=current.get(CONF_VACATION_STATE, False)): selector.BooleanSelector(),
            }),
        )

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Update room settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            _validate_overrides(user_input, errors)
            if not errors:
                flat_data = _flatten_overrides(user_input)
                new_data = {**self.config_entry.data, **flat_data}
                self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
                return self.async_create_entry(title="", data={})

        current = self.config_entry.data
        return self.async_show_form(
            step_id="room",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=current.get(CONF_NAME, DEFAULT_NAME)): str,
                vol.Required(CONF_HEATER_ENTITIES, default=current.get(CONF_HEATER_ENTITIES, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["climate", "switch", "water_heater"], multiple=True)
                ),
                vol.Required(CONF_SENSOR, default=current.get(CONF_SENSOR)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(CONF_WINDOW_SENSOR, default=current.get(CONF_WINDOW_SENSOR)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor", device_class="window")
                ),
                vol.Required("overrides"): _overrides_schema(defaults=dict(current)),
            }),
            errors=errors,
        )
