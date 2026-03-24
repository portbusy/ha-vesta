"""Config flow for Vesta climate controller."""
from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
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


def _temp_selector(
    min_val: float = 5.0, max_val: float = 35.0, step: float = 0.5
) -> selector.NumberSelector:
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


# --- Helper to get global config entry ---


def _get_global_entry(hass) -> config_entries.ConfigEntry | None:
    """Return the existing global config entry, if any."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
            return entry
    return None


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
    if overrides.get(CONF_OVERRIDE_PRESENCE) and not overrides.get(
        CONF_PRESENCE_SENSORS
    ):
        errors[CONF_PRESENCE_SENSORS] = "missing_presence_sensors"
    if overrides.get(CONF_OVERRIDE_SCHEDULE) and not overrides.get(CONF_SCHEDULE):
        errors[CONF_SCHEDULE] = "missing_schedule_entity"
    if overrides.get(CONF_OVERRIDE_WEATHER) and not overrides.get(CONF_WEATHER):
        errors[CONF_WEATHER] = "missing_weather_entity"


def _overrides_schema(
    defaults: dict[str, Any] | None = None,
    global_data: dict[str, Any] | None = None,
) -> section:
    """Build the overrides section schema with optional defaults.

    If defaults are not provided for entity fields, fall back to global_data
    so that override entity selectors show the global value as placeholder.
    """
    d = defaults or {}
    g = global_data or {}

    # For entity fields: use room override first, then global, then empty
    def _entity_default(key, fallback=None):
        val = d.get(key) or g.get(key) or fallback
        return val

    sched_default = _entity_default(CONF_SCHEDULE)
    weather_default = _entity_default(CONF_WEATHER)

    schema_dict: dict = {
        vol.Required(
            CONF_OVERRIDE_PRESENCE,
            default=d.get(CONF_OVERRIDE_PRESENCE, False),
        ): selector.BooleanSelector(),
        vol.Optional(
            CONF_PRESENCE_SENSORS,
            default=_entity_default(CONF_PRESENCE_SENSORS, []),
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="person", multiple=True)
        ),
        vol.Required(
            CONF_OVERRIDE_SCHEDULE,
            default=d.get(CONF_OVERRIDE_SCHEDULE, False),
        ): selector.BooleanSelector(),
    }

    # Only set default if we have a valid entity id (avoids None validation error)
    if sched_default:
        schema_dict[vol.Optional(CONF_SCHEDULE, default=sched_default)] = (
            selector.EntitySelector(
                selector.EntitySelectorConfig(domain="schedule")
            )
        )
    else:
        schema_dict[vol.Optional(CONF_SCHEDULE)] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="schedule")
        )

    schema_dict[vol.Required(
        CONF_OVERRIDE_WEATHER,
        default=d.get(CONF_OVERRIDE_WEATHER, False),
    )] = selector.BooleanSelector()

    if weather_default:
        schema_dict[vol.Optional(CONF_WEATHER, default=weather_default)] = (
            selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            )
        )
    else:
        schema_dict[vol.Optional(CONF_WEATHER)] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="weather")
        )

    schema_dict.update({
        vol.Required(
            CONF_OVERRIDE_COMFORT,
            default=d.get(CONF_OVERRIDE_COMFORT, False),
        ): selector.BooleanSelector(),
        vol.Optional(
            CONF_COMFORT_TEMP,
            default=d.get(CONF_COMFORT_TEMP) or g.get(CONF_COMFORT_TEMP, 21.0),
        ): _temp_selector(),
        vol.Required(
            CONF_OVERRIDE_AWAY,
            default=d.get(CONF_OVERRIDE_AWAY, False),
        ): selector.BooleanSelector(),
        vol.Optional(
            CONF_AWAY_TEMP,
            default=d.get(CONF_AWAY_TEMP) or g.get(CONF_AWAY_TEMP, 15.0),
        ): _temp_selector(),
    })

    return section(vol.Schema(schema_dict), {"collapsed": True})


# --- Auto-discovery from area ---


def _discover_entities_for_area(hass, area_id: str) -> dict[str, Any]:
    """Find heaters, temp sensors, and window sensors in an area.

    Returns both the default values (entity IDs) and the full option lists
    for SelectSelector so the user only sees entities from the area.

    Checks both the entity's own area_id AND its device's area_id, because
    most entities inherit the area from their device rather than having it
    set directly on the entity entry.
    """
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    entities = []
    for entry in entity_reg.entities.values():
        if entry.disabled:
            continue
        if entry.area_id == area_id:
            entities.append(entry)
        elif entry.device_id:
            device = device_reg.async_get(entry.device_id)
            if device and device.area_id == area_id:
                entities.append(entry)

    heater_ids: list[str] = []
    temp_ids: list[str] = []
    temp_default: str | None = None
    window_ids: list[str] = []
    window_default: str | None = None

    for entry in entities:
        if entry.disabled:
            continue
        domain = entry.domain

        if domain in ("climate", "switch", "water_heater"):
            heater_ids.append(entry.entity_id)

        # device_class stores only manual overrides; fall back to original_device_class
        effective_dc = entry.device_class or entry.original_device_class
        if domain == "sensor" and effective_dc == "temperature":
            temp_ids.append(entry.entity_id)
            if temp_default is None:
                temp_default = entry.entity_id

        if domain == "binary_sensor" and effective_dc == "window":
            window_ids.append(entry.entity_id)
            if window_default is None:
                window_default = entry.entity_id

    return {
        CONF_SENSOR: temp_default,
        CONF_WINDOW_SENSOR: window_default,
        "heater_ids": heater_ids,
        "temp_ids": temp_ids,
        "window_ids": window_ids,
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
        """Handle the initial step.

        - If no global entry exists: show both options, default to Global
        - If global already configured: skip straight to area (room) setup
        """
        global_entry = _get_global_entry(self.hass)

        # If global already exists, skip the choice and go directly to room
        if global_entry is not None:
            if user_input is not None:
                return await self.async_step_area()
            # Skip user step entirely — go straight to area selection
            return await self.async_step_area()

        # No global yet — show both options with "Global" as default
        if user_input is not None:
            if user_input[CONF_ENTRY_TYPE] == ENTRY_TYPE_GLOBAL:
                return await self.async_step_global()
            return await self.async_step_area()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENTRY_TYPE, default=ENTRY_TYPE_GLOBAL
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=ENTRY_TYPE_GLOBAL,
                                    label="Configure Global Defaults",
                                ),
                                selector.SelectOptionDict(
                                    value=ENTRY_TYPE_ROOM,
                                    label="Add a new Room",
                                ),
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
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
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_COMFORT_TEMP, default=21.0): _temp_selector(),
                    vol.Required(CONF_ECO_TEMP, default=18.0): _temp_selector(),
                    vol.Required(CONF_AWAY_TEMP, default=15.0): _temp_selector(),
                    vol.Required(
                        CONF_AVG_SPEED, default=50.0
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=10,
                            max=200,
                            step=5,
                            unit_of_measurement="km/h",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(CONF_PRESENCE_SENSORS): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="person", multiple=True
                        )
                    ),
                    vol.Optional(CONF_SCHEDULE): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="schedule")
                    ),
                    vol.Optional(CONF_WEATHER): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="weather")
                    ),
                    vol.Optional(CONF_OVERRIDE_SWITCH): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=["input_boolean", "switch"]
                        )
                    ),
                    vol.Optional(
                        CONF_VACATION_STATE, default=False
                    ): selector.BooleanSelector(),
                }
            ),
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
                self._discovered = _discover_entities_for_area(
                    self.hass, self._area_id
                )
            return await self.async_step_room()

        return self.async_show_form(
            step_id="area",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_AREA): selector.AreaSelector(),
                }
            ),
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
                title = flat_data[CONF_NAME]
                return self.async_create_entry(title=title, data=flat_data)

        # Get global data for defaults in overrides
        global_entry = _get_global_entry(self.hass)
        global_data = dict(global_entry.data) if global_entry else {}

        # Use discovered defaults from area, or empty
        d = self._discovered
        default_name = (
            f"Vesta {self._area_name}" if self._area_name else DEFAULT_NAME
        )
        has_area = bool(self._area_id)

        schema: dict = {
            vol.Required(CONF_NAME, default=default_name): str,
        }

        if has_area:
            heater_ids = d.get("heater_ids", [])
            temp_ids = d.get("temp_ids", [])
            window_ids = d.get("window_ids", [])

            # Heaters: area-filtered EntitySelector, no pre-selection
            if heater_ids:
                schema[vol.Required(CONF_HEATER_ENTITIES)] = selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        include_entities=heater_ids,
                        multiple=True,
                    )
                )
            else:
                schema[vol.Required(CONF_HEATER_ENTITIES)] = selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["climate", "switch", "water_heater"],
                        multiple=True,
                    )
                )

            # Temp sensor: area-filtered, auto-select first found
            temp_kwargs = {}
            if d.get(CONF_SENSOR):
                temp_kwargs["default"] = d[CONF_SENSOR]
            if temp_ids:
                schema[vol.Required(CONF_SENSOR, **temp_kwargs)] = selector.EntitySelector(
                    selector.EntitySelectorConfig(include_entities=temp_ids)
                )
            else:
                schema[vol.Required(CONF_SENSOR, **temp_kwargs)] = selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="temperature"
                    )
                )

            # Window sensor: area-filtered, optional
            win_default = d.get(CONF_WINDOW_SENSOR)
            win_key = (
                vol.Optional(CONF_WINDOW_SENSOR, default=win_default)
                if win_default
                else vol.Optional(CONF_WINDOW_SENSOR)
            )
            if window_ids:
                schema[win_key] = selector.EntitySelector(
                    selector.EntitySelectorConfig(include_entities=window_ids)
                )
            else:
                schema[win_key] = selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="binary_sensor", device_class="window"
                    )
                )
        else:
            # --- No area: use standard EntitySelector (shows all entities) ---
            schema[vol.Required(CONF_HEATER_ENTITIES)] = (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["climate", "switch", "water_heater"],
                        multiple=True,
                    )
                )
            )
            schema[vol.Required(CONF_SENSOR)] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class="temperature"
                )
            )
            schema[vol.Optional(CONF_WINDOW_SENSOR)] = (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="binary_sensor", device_class="window"
                    )
                )
            )

        # Overrides section — pass global data so entity selectors show global defaults
        schema[vol.Required("overrides")] = _overrides_schema(
            global_data=global_data
        )

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
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            return self.async_create_entry(title="", data={})

        current = self.config_entry.data

        # Build schema — avoid default=None for entity selectors
        schema_dict: dict = {
            vol.Required(
                CONF_COMFORT_TEMP,
                default=current.get(CONF_COMFORT_TEMP, 21.0),
            ): _temp_selector(),
            vol.Required(
                CONF_ECO_TEMP, default=current.get(CONF_ECO_TEMP, 18.0)
            ): _temp_selector(),
            vol.Required(
                CONF_AWAY_TEMP, default=current.get(CONF_AWAY_TEMP, 15.0)
            ): _temp_selector(),
            vol.Required(
                CONF_AVG_SPEED, default=current.get(CONF_AVG_SPEED, 50.0)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10,
                    max=200,
                    step=5,
                    unit_of_measurement="km/h",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
        }

        # Entity selectors — only set default if we have a valid value
        presence = current.get(CONF_PRESENCE_SENSORS)
        if presence:
            schema_dict[
                vol.Optional(CONF_PRESENCE_SENSORS, default=presence)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="person", multiple=True)
            )
        else:
            schema_dict[vol.Optional(CONF_PRESENCE_SENSORS)] = (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="person", multiple=True
                    )
                )
            )

        schedule = current.get(CONF_SCHEDULE)
        if schedule:
            schema_dict[
                vol.Optional(CONF_SCHEDULE, default=schedule)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="schedule")
            )
        else:
            schema_dict[vol.Optional(CONF_SCHEDULE)] = (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="schedule")
                )
            )

        weather = current.get(CONF_WEATHER)
        if weather:
            schema_dict[
                vol.Optional(CONF_WEATHER, default=weather)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            )
        else:
            schema_dict[vol.Optional(CONF_WEATHER)] = (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="weather")
                )
            )

        override_sw = current.get(CONF_OVERRIDE_SWITCH)
        if override_sw:
            schema_dict[
                vol.Optional(CONF_OVERRIDE_SWITCH, default=override_sw)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["input_boolean", "switch"]
                )
            )
        else:
            schema_dict[vol.Optional(CONF_OVERRIDE_SWITCH)] = (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["input_boolean", "switch"]
                    )
                )
            )

        schema_dict[
            vol.Optional(
                CONF_VACATION_STATE,
                default=current.get(CONF_VACATION_STATE, False),
            )
        ] = selector.BooleanSelector()

        return self.async_show_form(
            step_id="global",
            data_schema=vol.Schema(schema_dict),
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
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )
                return self.async_create_entry(title="", data={})

        current = self.config_entry.data
        area_id = current.get(CONF_AREA)

        # Get global data for override defaults
        global_entry = _get_global_entry(self.hass)
        global_data = dict(global_entry.data) if global_entry else {}

        schema_dict: dict = {
            vol.Required(
                CONF_NAME, default=current.get(CONF_NAME, DEFAULT_NAME)
            ): str,
        }

        if area_id:
            d = _discover_entities_for_area(self.hass, area_id)

            # Merge saved entities into the discovered lists so that entities
            # moved out of the area remain selectable and pass validation.
            heater_ids = list(
                dict.fromkeys(
                    d.get("heater_ids", []) + current.get(CONF_HEATER_ENTITIES, [])
                )
            )
            saved_sensor = current.get(CONF_SENSOR)
            temp_ids = list(
                dict.fromkeys(
                    d.get("temp_ids", []) + ([saved_sensor] if saved_sensor else [])
                )
            )
            saved_window = current.get(CONF_WINDOW_SENSOR)
            window_ids = list(
                dict.fromkeys(
                    d.get("window_ids", []) + ([saved_window] if saved_window else [])
                )
            )

            if heater_ids:
                schema_dict[
                    vol.Required(
                        CONF_HEATER_ENTITIES,
                        default=current.get(CONF_HEATER_ENTITIES, []),
                    )
                ] = selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        include_entities=heater_ids,
                        multiple=True,
                    )
                )
            else:
                schema_dict[
                    vol.Required(
                        CONF_HEATER_ENTITIES,
                        default=current.get(CONF_HEATER_ENTITIES, []),
                    )
                ] = selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["climate", "switch", "water_heater"],
                        multiple=True,
                    )
                )

            sensor = saved_sensor or d.get(CONF_SENSOR)
            if temp_ids:
                schema_dict[
                    vol.Required(CONF_SENSOR, **({"default": sensor} if sensor else {}))
                ] = selector.EntitySelector(
                    selector.EntitySelectorConfig(include_entities=temp_ids)
                )
            else:
                schema_dict[
                    vol.Required(CONF_SENSOR, **({"default": sensor} if sensor else {}))
                ] = selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="temperature"
                    )
                )

            if window_ids:
                schema_dict[
                    vol.Optional(
                        CONF_WINDOW_SENSOR,
                        **({"default": saved_window} if saved_window else {}),
                    )
                ] = selector.EntitySelector(
                    selector.EntitySelectorConfig(include_entities=window_ids)
                )
            else:
                schema_dict[
                    vol.Optional(
                        CONF_WINDOW_SENSOR,
                        **({"default": saved_window} if saved_window else {}),
                    )
                ] = selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="binary_sensor", device_class="window"
                    )
                )
        else:
            # No area stored — fall back to open EntitySelector
            schema_dict[
                vol.Required(
                    CONF_HEATER_ENTITIES,
                    default=current.get(CONF_HEATER_ENTITIES, []),
                )
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["climate", "switch", "water_heater"], multiple=True
                )
            )
            sensor = current.get(CONF_SENSOR)
            schema_dict[
                vol.Required(CONF_SENSOR, **({"default": sensor} if sensor else {}))
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class="temperature"
                )
            )
            window = current.get(CONF_WINDOW_SENSOR)
            if window:
                schema_dict[
                    vol.Optional(CONF_WINDOW_SENSOR, default=window)
                ] = selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="binary_sensor", device_class="window"
                    )
                )
            else:
                schema_dict[vol.Optional(CONF_WINDOW_SENSOR)] = selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="binary_sensor", device_class="window"
                    )
                )

        # Pass both room-level overrides and global data as fallback
        schema_dict[vol.Required("overrides")] = _overrides_schema(
            defaults=dict(current), global_data=global_data
        )

        return self.async_show_form(
            step_id="room",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )
