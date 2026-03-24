"""Ultimate Robust & Self-Healing Climate Pro."""
from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timedelta, date
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_NAME,
    UnitOfTemperature,
    STATE_ON,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util, location

from .const import (
    DOMAIN,
    CONF_HEATER_ENTITIES,
    CONF_SENSOR,
    CONF_WINDOW_SENSOR,
    CONF_PRESENCE_SENSORS,
    CONF_SCHEDULE,
    CONF_WEATHER,
    CONF_VACATION_STATE,
    CONF_COMFORT_TEMP,
    CONF_ECO_TEMP,
    CONF_AWAY_TEMP,
    CONF_AVG_SPEED,
    CONF_OVERRIDE_COMFORT,
    CONF_OVERRIDE_AWAY,
    CONF_OVERRIDE_PRESENCE,
    CONF_OVERRIDE_WEATHER,
    CONF_OVERRIDE_SCHEDULE,
    MODE_SMART_SCHEDULE,
    MODE_MANUAL,
    MODE_AWAY,
    MODE_VACATION,
    ATTR_HEATING_POWER,
    ATTR_HEATING_RATE,
    ATTR_COOLING_RATE,
    ATTR_DAILY_USAGE,
    ATTR_NEAREST_DISTANCE,
    ATTR_VACATION_MODE,
    ATTR_OUTDOOR_TEMP,
)

_LOGGER = logging.getLogger(__name__)

# Constants
ANTI_FROST_TEMP = 5.0
MANUAL_OVERRIDE_TIMEOUT_HRS = 4
MAX_HEATING_RATE = 0.5  # °C/min max (safety clamp)
MIN_HEATING_RATE = 0.005  # °C/min min (safety clamp)
LEARNING_ALPHA = 0.05
DUTY_CYCLE_WINDOW = 10  # Track last N ticks for heating power %


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Vesta climate platform."""
    data = entry.data
    async_add_entities([SmartClimatePro(hass, entry, data)])


class SmartClimatePro(ClimateEntity, RestoreEntity):
    """The Ultimate Room Controller with Hardware Failure Detection & Frost Guard."""

    _attr_has_entity_name = True
    _attr_translation_key = "smart_climate_pro"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = [MODE_SMART_SCHEDULE, MODE_MANUAL, MODE_AWAY, MODE_VACATION]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, data: dict):
        self.hass = hass
        self._entry = entry
        self._data = data
        self._name = data[CONF_NAME]
        self._heaters = data[CONF_HEATER_ENTITIES]
        self._sensor_id = data[CONF_SENSOR]
        self._window_sensor_id = data.get(CONF_WINDOW_SENSOR)

        # State
        self._cur_temp: float | None = None
        self._outdoor_temp: float | None = None
        self._target_temp: float | None = None
        self._hvac_mode = HVACMode.HEAT
        self._preset_mode = MODE_SMART_SCHEDULE
        self._window_open = False
        self._vacation_active = False
        self._force_return = False
        self._nearest_distance = 0.0

        # Duty cycle tracking
        self._duty_history: deque[bool] = deque(maxlen=DUTY_CYCLE_WINDOW)
        self._heating_power = 0.0

        # Learning
        self._heating_rate = 0.05
        self._cooling_rate = 0.02
        self._last_learning_temp: float | None = None
        self._last_learning_time: float | None = None

        # Daily usage tracking
        self._daily_usage_seconds = 0
        self._last_usage_reset_date: date | None = None

        # Safety & Fail-safe state
        self._last_heater_state: bool | None = None
        self._manual_start_time: float | None = None
        self._hardware_failure = False
        self._stuck_check_time: float | None = None
        self._stuck_check_temp: float | None = None
        self._event_listeners: list = []

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to link entity to the config entry."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._name,
            manufacturer="Vesta",
            model="Smart Climate Controller",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def unique_id(self) -> str:
        """Return a unique ID based on config entry ID."""
        return f"{DOMAIN}_{self._entry.entry_id}"

    @property
    def name(self) -> str | None:
        """Return the name of the entity."""
        return None  # Uses device name since _attr_has_entity_name = True

    @property
    def extra_state_attributes(self) -> dict:
        return {
            ATTR_HEATING_POWER: round(self._heating_power, 1),
            ATTR_HEATING_RATE: round(self._heating_rate, 4),
            ATTR_COOLING_RATE: round(self._cooling_rate, 4),
            ATTR_DAILY_USAGE: round(self._daily_usage_seconds / 60, 1),
            ATTR_NEAREST_DISTANCE: round(self._nearest_distance, 0),
            ATTR_VACATION_MODE: self._vacation_active,
            ATTR_OUTDOOR_TEMP: self._outdoor_temp,
            "hardware_failure_warning": self._hardware_failure,
            "manual_timeout_remaining_min": self._get_manual_timeout(),
            "preset_mode": self._preset_mode,
            "target_temp": self._target_temp,
            "manual_start_time": self._manual_start_time,
        }

    def _get_manual_timeout(self) -> int:
        if self._preset_mode != MODE_MANUAL or not self._manual_start_time:
            return 0
        elapsed = (time.time() - self._manual_start_time) / 60
        return max(0, int((MANUAL_OVERRIDE_TIMEOUT_HRS * 60) - elapsed))

    def _update_heating_power(self, heater_on: bool) -> None:
        """Track duty cycle to compute heating power percentage."""
        self._duty_history.append(heater_on)
        if self._duty_history:
            self._heating_power = (
                sum(self._duty_history) / len(self._duty_history)
            ) * 100.0

    def _check_daily_reset(self) -> None:
        """Reset daily usage counter at midnight."""
        today = dt_util.now().date()
        if self._last_usage_reset_date != today:
            self._daily_usage_seconds = 0
            self._last_usage_reset_date = today

    async def _async_tick(self, now):
        """Robust Heartbeat with Fail-Safe checks."""
        # now is a datetime when called by the scheduler, None for manual triggers
        scheduled = now is not None

        # 0. Daily usage reset check
        self._check_daily_reset()

        await self._update_state()
        self._update_force_return()

        # 1. Manual Timeout Guard: Back to schedule after X hours
        if self._preset_mode == MODE_MANUAL and self._get_manual_timeout() == 0:
            _LOGGER.info(
                "Manual override timeout for %s. Returning to schedule.",
                self._name,
            )
            self._preset_mode = MODE_SMART_SCHEDULE
            self._force_return = False

        # 2. Safety Check: Sensor failure
        if self._cur_temp is None:
            _LOGGER.error("Emergency: Sensor %s is offline!", self._sensor_id)
            heater_on = (dt_util.now().minute % 10) == 0  # Minimal pulse
            if scheduled and heater_on:
                self._daily_usage_seconds += 60
            await self._set_heaters(heater_on)
            self._update_heating_power(heater_on)
            return

        # 3. Frost Guard (Priority over Window Open)
        frost_risk = self._cur_temp < ANTI_FROST_TEMP

        # 4. Compute effective target (pure read, no side effects)
        effective_target = self._compute_effective_target()

        # 5. Control Logic
        # Frost protection is unconditional: overrides hvac_mode=OFF and open windows
        heater_on = False
        if frost_risk:
            heater_on = self._cur_temp < (ANTI_FROST_TEMP + 0.8)
        elif self._hvac_mode == HVACMode.HEAT and not self._window_open:
            heater_on = self._cur_temp < (effective_target - 0.2)

        # Count usage only on scheduled ticks, not manual triggers
        if scheduled and heater_on:
            self._daily_usage_seconds += 60
        await self._set_heaters(heater_on)

        # 6. Update duty cycle
        self._update_heating_power(heater_on)

        # 7. Hardware Failure Detection
        self._check_hardware_performance()

        # 8. Learning
        if not (
            self._vacation_active
            or self._force_return
            or self._nearest_distance > 500
            or self._hardware_failure
        ):
            self._update_learning()

        self.async_write_ha_state()

    def _update_force_return(self) -> None:
        """Set _force_return if pre-heating should start for imminent arrival.

        Called only from _async_tick so state mutation stays out of properties.
        """
        if self._preset_mode != MODE_AWAY or self._force_return or self._cur_temp is None:
            return
        base = self._target_temp or self.comfort_temp
        if self._outdoor_temp is not None and self._outdoor_temp < 5:
            base += (5 - self._outdoor_temp) * 0.1
        avg_speed = max(self._get_global(CONF_AVG_SPEED, 50.0), 1.0)
        h_rate = max(self._heating_rate, MIN_HEATING_RATE)
        travel_time_min = (self._nearest_distance / 1000) / (avg_speed / 60)
        temp_deficit = base - self._cur_temp
        if temp_deficit > 0:
            heat_time_min = temp_deficit / h_rate
            if travel_time_min <= heat_time_min:
                self._force_return = True

    def _compute_effective_target(self) -> float:
        """Compute the effective target temperature (pure, no side-effects)."""
        if self._vacation_active or self._preset_mode == MODE_VACATION:
            return ANTI_FROST_TEMP
        if self._force_return:
            return self.comfort_temp
        if self._preset_mode == MODE_MANUAL:
            return self._target_temp or self.comfort_temp

        base = self._target_temp or self.comfort_temp

        # Weather compensation: boost when it's very cold outside
        if self._outdoor_temp is not None and self._outdoor_temp < 5:
            base += (5 - self._outdoor_temp) * 0.1

        if self._preset_mode == MODE_AWAY:
            return (
                self.away_temp if self._nearest_distance > 15000 else self.eco_temp
            )
        return base

    def _check_hardware_performance(self):
        """Detect if heaters are on but room is not warming up."""
        if self._heating_power > 90 and not self._window_open:
            now = time.time()
            if self._stuck_check_time is None:
                self._stuck_check_time = now
                self._stuck_check_temp = self._cur_temp
                return

            # Check every 45 minutes of continuous high power
            if (now - self._stuck_check_time) > 2700:
                expected_rise = self._heating_rate * 45 * 0.5
                actual_rise = (self._cur_temp or 0) - (self._stuck_check_temp or 0)

                if actual_rise < 0.1 and actual_rise < expected_rise:
                    _LOGGER.error(
                        "Hardware Failure Warning for %s: Power at 100%% but temp not rising!",
                        self._name,
                    )
                    self._hardware_failure = True
                else:
                    self._hardware_failure = False

                self._stuck_check_time = now
                self._stuck_check_temp = self._cur_temp
        else:
            self._stuck_check_time = None
            self._stuck_check_temp = None

    def _update_learning(self):
        """Learns with sanity clamping."""
        now = time.time()
        if self._cur_temp is None or self._last_learning_temp is None:
            self._last_learning_temp = self._cur_temp
            self._last_learning_time = now
            return
        dt = (now - (self._last_learning_time or now)) / 60
        if dt < 15:
            return

        rate = abs((self._cur_temp - self._last_learning_temp) / max(dt, 0.1))
        # Clamping: ignore impossible values
        if rate < MIN_HEATING_RATE or rate > MAX_HEATING_RATE:
            return

        if self._heating_power > 90:
            self._heating_rate = (self._heating_rate * (1 - LEARNING_ALPHA)) + (
                rate * LEARNING_ALPHA
            )
        elif self._heating_power < 10:
            self._cooling_rate = (self._cooling_rate * (1 - LEARNING_ALPHA)) + (
                rate * LEARNING_ALPHA
            )

        self._last_learning_temp = self._cur_temp
        self._last_learning_time = now

    async def _set_heaters(self, on: bool):
        if self._last_heater_state == on:
            return
        self._last_heater_state = on
        for eid in self._heaters:
            await self.hass.services.async_call(
                "homeassistant",
                "turn_on" if on else "turn_off",
                {"entity_id": eid},
            )

    # Standard HA Boilerplate & Dynamic Properties
    @property
    def comfort_temp(self) -> float:
        """Return the target comfort temperature."""
        if self._entry.data.get(CONF_OVERRIDE_COMFORT):
            return float(self._entry.data.get(CONF_COMFORT_TEMP, 21.0))
        return float(self._get_global(CONF_COMFORT_TEMP, 21.0))

    @property
    def eco_temp(self) -> float:
        """Return the eco temperature."""
        return float(self._get_global(CONF_ECO_TEMP, 18.0))

    @property
    def away_temp(self) -> float:
        """Return the away temperature."""
        if self._entry.data.get(CONF_OVERRIDE_AWAY):
            return float(self._entry.data.get(CONF_AWAY_TEMP, 15.0))
        return float(self._get_global(CONF_AWAY_TEMP, 15.0))

    @property
    def min_temp(self) -> float:
        return ANTI_FROST_TEMP

    @property
    def max_temp(self) -> float:
        return 35.0

    @property
    def target_temperature(self) -> float:
        """Return the target temperature (pure read-only, no side-effects)."""
        return self._compute_effective_target()

    # HA Schedule entity built-in attributes — not part of block additional data
    _SCHED_HA_ATTRS = frozenset(
        {"next_event", "editable", "icon", "friendly_name", "restored"}
    )

    def _get_current_schedule_block_data(self, schedule_entity_id: str) -> dict:
        """Return additional data for the currently active schedule block.

        HA exposes the current block's additional data directly as state
        attributes on the schedule entity (alongside next_event, editable,
        friendly_name). We just filter out the built-in HA attributes.
        """
        state = self.hass.states.get(schedule_entity_id)
        if not state:
            return {}
        block_data = {
            k: v
            for k, v in state.attributes.items()
            if k not in self._SCHED_HA_ATTRS
        }
        # Normalise boolean mode values: unquoted 'off'/'on' in YAML are stored
        # as Python booleans by HA; map them back to strings.
        if isinstance(block_data.get("mode"), bool):
            block_data["mode"] = "off" if not block_data["mode"] else "on"
        return block_data

    def _parse_schedule_block_data(self, block_data: dict | None) -> float | None:
        """Estrae la temperatura dai dati aggiuntivi del blocco.

        Esempi di JSON validi nel campo 'Dati aggiuntivi':
        - {"temp": 22.5}        → 22.5°C diretta
        - {"mode": "comfort"}   → comfort_temp
        - {"mode": "eco"}       → eco_temp
        - {"mode": "away"}      → away_temp
        - {"mode": "frost"}     → ANTI_FROST_TEMP
        - {}  o assente         → fallback a on/off
        """
        if not block_data:
            return None

        # Campo temp diretto
        if "temp" in block_data:
            try:
                return float(block_data["temp"])
            except (ValueError, TypeError):
                pass

        # Campo mode
        mode = str(block_data.get("mode", "")).lower().strip()
        mode_map = {
            "comfort": self.comfort_temp,
            "eco": self.eco_temp,
            "away": self.away_temp,
            "frost": ANTI_FROST_TEMP,
        }
        if mode in mode_map:
            return mode_map[mode]

        return None

    async def _update_state(self):
        """Update internal state based on global settings, schedule, presence and weather."""
        g = self.hass.data[DOMAIN].get("global")
        if not g:
            if self._target_temp is None:
                self._target_temp = 21.0
            return

        # Initialize target_temp from global comfort on first run
        if self._target_temp is None:
            self._target_temp = self.comfort_temp

        # 1. Vacation Mode (Global)
        vacation_status = g.data.get(CONF_VACATION_STATE, False)
        if isinstance(vacation_status, str):
            self._vacation_active = vacation_status == "on"
        else:
            self._vacation_active = bool(vacation_status)

        # 2. Schedule Logic: HA schedule entity
        if self._preset_mode != MODE_MANUAL:
            sched_id = (
                self._entry.data.get(CONF_SCHEDULE)
                if self._entry.data.get(CONF_OVERRIDE_SCHEDULE)
                else g.data.get(CONF_SCHEDULE)
            )
            if sched_id and (s_state := self.hass.states.get(sched_id)):
                block_data = self._get_current_schedule_block_data(sched_id)

                # Controlla se il blocco richiede spegnimento
                mode = str((block_data or {}).get("mode", "")).lower().strip()
                if mode == "off":
                    self._hvac_mode = HVACMode.OFF
                else:
                    # Riattiva se era stato spento dallo schedule
                    if self._hvac_mode == HVACMode.OFF and self._preset_mode != MODE_MANUAL:
                        self._hvac_mode = HVACMode.HEAT

                    parsed_temp = self._parse_schedule_block_data(block_data)
                    if parsed_temp is not None:
                        self._target_temp = parsed_temp
                    else:
                        # Fallback classico: on = comfort, off = eco
                        self._target_temp = (
                            self.comfort_temp
                            if s_state.state == STATE_ON
                            else self.eco_temp
                        )

        # 3. Presence & Geofencing
        presence_ids = (
            self._entry.data.get(CONF_PRESENCE_SENSORS)
            if self._entry.data.get(CONF_OVERRIDE_PRESENCE)
            else g.data.get(CONF_PRESENCE_SENSORS)
        )
        if presence_ids:
            any_home = False
            min_dist = 999999.0
            for pid in presence_ids:
                if p_state := self.hass.states.get(pid):
                    if p_state.state == "home":
                        any_home = True
                        min_dist = 0.0
                        break
                    lat = p_state.attributes.get(ATTR_LATITUDE)
                    lon = p_state.attributes.get(ATTR_LONGITUDE)
                    if (
                        lat is not None
                        and lon is not None
                        and self.hass.config.latitude is not None
                        and self.hass.config.longitude is not None
                    ):
                        dist = location.distance(
                            lat,
                            lon,
                            self.hass.config.latitude,
                            self.hass.config.longitude,
                        )
                        if dist < min_dist:
                            min_dist = dist

            self._nearest_distance = min_dist
            if any_home:
                if self._preset_mode == MODE_AWAY:
                    self._preset_mode = MODE_SMART_SCHEDULE
                self._force_return = False
            elif self._preset_mode not in (MODE_MANUAL, MODE_VACATION):
                self._preset_mode = MODE_AWAY
                self._force_return = False

        # 4. Weather / Outdoor Temperature
        weather_id = (
            self._entry.data.get(CONF_WEATHER)
            if self._entry.data.get(CONF_OVERRIDE_WEATHER)
            else g.data.get(CONF_WEATHER)
        )
        if weather_id:
            if w_state := self.hass.states.get(weather_id):
                temp = w_state.attributes.get("temperature")
                if temp is not None:
                    try:
                        self._outdoor_temp = float(temp)
                    except (ValueError, TypeError):
                        pass

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if self not in self.hass.data[DOMAIN]["rooms"]:
            self.hass.data[DOMAIN]["rooms"].append(self)

        old = await self.async_get_last_state()
        if old:
            self._heating_rate = old.attributes.get(
                ATTR_HEATING_RATE, self._heating_rate
            )
            self._cooling_rate = old.attributes.get(
                ATTR_COOLING_RATE, self._cooling_rate
            )
            self._daily_usage_seconds = (
                old.attributes.get(ATTR_DAILY_USAGE, 0) * 60
            )

            if old.state in (HVACMode.HEAT, HVACMode.OFF):
                self._hvac_mode = HVACMode(old.state)

            restored_preset = old.attributes.get("preset_mode")
            if restored_preset in self._attr_preset_modes:
                self._preset_mode = restored_preset

            restored_target = old.attributes.get("target_temp")
            if restored_target is not None:
                try:
                    self._target_temp = float(restored_target)
                except (ValueError, TypeError):
                    pass

            restored_manual_time = old.attributes.get("manual_start_time")
            if (
                restored_manual_time is not None
                and self._preset_mode == MODE_MANUAL
            ):
                try:
                    self._manual_start_time = float(restored_manual_time)
                except (ValueError, TypeError):
                    pass

            if (
                old.state not in ("unknown", "unavailable")
                and self._cur_temp is None
            ):
                try:
                    self._cur_temp = float(
                        old.attributes.get("current_temperature") or old.state
                    )
                except (ValueError, TypeError):
                    pass

        if self._sensor_id and (
            state := self.hass.states.get(self._sensor_id)
        ):
            if state.state not in ("unknown", "unavailable"):
                try:
                    self._cur_temp = float(state.state)
                except ValueError:
                    pass

        # Initialise heater state from reality to avoid a spurious turn_off at startup
        if self._heaters:
            self._last_heater_state = any(
                (s := self.hass.states.get(eid)) is not None and s.state == STATE_ON
                for eid in self._heaters
            )

        self._last_usage_reset_date = dt_util.now().date()

        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_tick, timedelta(minutes=1)
            )
        )
        self._setup_listeners()
        self.hass.async_create_task(self._async_tick(None))

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        for listener in self._event_listeners:
            listener()
        self._event_listeners = []
        if self in self.hass.data[DOMAIN]["rooms"]:
            self.hass.data[DOMAIN]["rooms"].remove(self)
        await super().async_will_remove_from_hass()

    def _setup_listeners(self):
        for listener in self._event_listeners:
            listener()
        self._event_listeners = []

        if self._sensor_id:
            self._event_listeners.append(
                async_track_state_change_event(
                    self.hass, [self._sensor_id], self._on_sensor
                )
            )

        if self._window_sensor_id:
            self._event_listeners.append(
                async_track_state_change_event(
                    self.hass, [self._window_sensor_id], self._on_window
                )
            )

        if self._heaters:
            self._event_listeners.append(
                async_track_state_change_event(
                    self.hass, self._heaters, self._on_heater_change
                )
            )

        g = self.hass.data[DOMAIN].get("global")
        weather_id = self._entry.data.get(CONF_WEATHER) if self._entry.data.get(
            CONF_OVERRIDE_WEATHER
        ) else (g.data.get(CONF_WEATHER) if g else None)
        if weather_id:
            self._event_listeners.append(
                async_track_state_change_event(
                    self.hass, [weather_id], self._on_weather
                )
            )

        sched_id = (
            self._entry.data.get(CONF_SCHEDULE)
            if self._entry.data.get(CONF_OVERRIDE_SCHEDULE)
            else (g.data.get(CONF_SCHEDULE) if g else None)
        )
        if sched_id:
            self._event_listeners.append(
                async_track_state_change_event(
                    self.hass, [sched_id], self._on_schedule
                )
            )

        presence_ids = (
            self._entry.data.get(CONF_PRESENCE_SENSORS)
            if self._entry.data.get(CONF_OVERRIDE_PRESENCE)
            else (g.data.get(CONF_PRESENCE_SENSORS) if g else None)
        )
        if presence_ids:
            self._event_listeners.append(
                async_track_state_change_event(
                    self.hass, presence_ids, self._on_presence
                )
            )

    @callback
    def _on_presence(self, event):
        """React immediately when a person's state changes (home/away/GPS update)."""
        self.hass.async_create_task(self._async_tick(None))

    @callback
    def _on_schedule(self, event):
        """React immediately when the schedule entity changes state (ON/OFF)."""
        self.hass.async_create_task(self._async_tick(None))

    @callback
    def _on_heater_change(self, event):
        """Update internal state if a heater is changed externally."""
        s = event.data.get("new_state")
        if s:
            self._last_heater_state = s.state == STATE_ON
            self.async_write_ha_state()

    @callback
    def _on_sensor(self, event):
        s = event.data.get("new_state")
        if s and s.state not in ("unknown", "unavailable"):
            try:
                self._cur_temp = float(s.state)
                self.async_write_ha_state()
            except (ValueError, TypeError):
                pass

    @callback
    def _on_window(self, event):
        s = event.data.get("new_state")
        if s:
            self._window_open = s.state == STATE_ON
            self.hass.async_create_task(self._async_tick(None))

    @callback
    def _on_weather(self, event):
        """Update outdoor temperature from weather entity."""
        s = event.data.get("new_state")
        if s:
            temp = s.attributes.get("temperature")
            if temp is not None:
                try:
                    self._outdoor_temp = float(temp)
                except (ValueError, TypeError):
                    pass

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if t := kwargs.get(ATTR_TEMPERATURE):
            self._target_temp = t
            self._preset_mode = MODE_MANUAL
            self._force_return = False
            self._manual_start_time = time.time()
            await self._async_tick(None)

    def _get_global(self, key: str, default: Any) -> Any:
        g = self.hass.data[DOMAIN].get("global")
        return g.data.get(key, default) if g else default

    @property
    def current_temperature(self) -> float | None:
        return self._cur_temp

    @property
    def hvac_mode(self) -> HVACMode:
        return self._hvac_mode

    @property
    def preset_mode(self) -> str | None:
        return self._preset_mode

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._hvac_mode = hvac_mode
        await self._async_tick(None)

    async def async_set_preset_mode(self, m: str) -> None:
        self._preset_mode = m
        self._force_return = False
        if m == MODE_MANUAL:
            self._manual_start_time = time.time()
        await self._async_tick(None)