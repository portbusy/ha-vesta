"""Ultimate Robust & Self-Healing Climate Pro."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_NAME,
    UnitOfTemperature,
    STATE_ON,
    STATE_OFF,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import location

from .const import (
    DOMAIN,
    CONF_HEATER_ENTITIES,
    CONF_SENSOR,
    CONF_WINDOW_SENSOR,
    CONF_PRESENCE_SENSORS,
    CONF_SCHEDULE,
    CONF_WEATHER,
    CONF_OVERRIDE_SWITCH,
    CONF_VACATION_STATE,
    CONF_COMFORT_TEMP,
    CONF_ECO_TEMP,
    CONF_AWAY_TEMP,
    CONF_AVG_SPEED,
    CONF_OVERRIDE_COMFORT,
    CONF_OVERRIDE_AWAY,
    CONF_OVERRIDE_SPEED,
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
)

_LOGGER = logging.getLogger(__name__)

# Constants
ANTI_FROST_TEMP = 5.0
MANUAL_OVERRIDE_TIMEOUT_HRS = 4
MAX_HEATING_RATE = 0.5  # °C/min max (safety clamp)
MIN_HEATING_RATE = 0.005 # °C/min min (safety clamp)
LEARNING_ALPHA = 0.05

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Vesta climate platform."""
    data = entry.data
    async_add_entities([SmartClimatePro(hass, data)])

class SmartClimatePro(ClimateEntity, RestoreEntity):
    """The Ultimate Room Controller with Hardware Failure Detection & Frost Guard."""

    def __init__(self, hass: HomeAssistant, data: dict):
        self.hass = hass
        self._data = data
        self._name = data[CONF_NAME]
        self._heaters = data[CONF_HEATER_ENTITIES]
        self._sensor_id = data[CONF_SENSOR]
        self._window_sensor_id = data.get(CONF_WINDOW_SENSOR)

        # State
        self._cur_temp, self._outdoor_temp = None, None
        self._target_temp = 21.0
        self._hvac_mode = HVACMode.HEAT
        self._preset_mode = MODE_SMART_SCHEDULE
        self._window_open = False
        self._vacation_active, self._force_return = False, False
        self._nearest_distance = 0.0
        self._heating_power = 0.0
        self._heating_rate, self._cooling_rate = 0.05, 0.02
        self._daily_usage_seconds = 0
        self._last_learning_temp = None
        self._last_learning_time = None
        
        # Safety & Fail-safe state
        self._last_heater_state = None
        self._manual_start_time = None
        self._hardware_failure = False
        self._stuck_check_time = None
        self._stuck_check_temp = None
        self._event_listeners = []

    @property
    def extra_state_attributes(self) -> dict:
        return {
            ATTR_HEATING_POWER: round(self._heating_power, 1),
            ATTR_HEATING_RATE: round(self._heating_rate, 4),
            ATTR_COOLING_RATE: round(self._cooling_rate, 4),
            ATTR_DAILY_USAGE: round(self._daily_usage_seconds / 60, 1),
            ATTR_NEAREST_DISTANCE: round(self._nearest_distance, 0),
            "hardware_failure_warning": self._hardware_failure,
            "manual_timeout_remaining_min": self._get_manual_timeout(),
        }

    def _get_manual_timeout(self) -> int:
        if self._preset_mode != MODE_MANUAL or not self._manual_start_time: return 0
        elapsed = (time.time() - self._manual_start_time) / 60
        return max(0, int((MANUAL_OVERRIDE_TIMEOUT_HRS * 60) - elapsed))

    async def _async_tick(self, _):
        """Robust Heartbeat with Fail-Safe checks."""
        await self._update_state()
        
        # 1. Manual Timeout Guard: Back to schedule after X hours
        if self._preset_mode == MODE_MANUAL and self._get_manual_timeout() == 0:
            _LOGGER.info("Manual override timeout for %s. Returning to schedule.", self._name)
            self._preset_mode = MODE_SMART_SCHEDULE

        # 2. Safety Check: Sensor failure
        if self._cur_temp is None:
            _LOGGER.error("Emergency: Sensor %s is offline!", self._sensor_id)
            await self._set_heaters((datetime.now().minute % 10) == 0) # Minimal pulse
            return

        # 3. Frost Guard (Priority over Window Open)
        frost_risk = self._cur_temp < ANTI_FROST_TEMP
        
        # 4. Control Logic
        if self._hvac_mode == HVACMode.HEAT:
            if self._window_open and not frost_risk:
                await self._set_heaters(False)
            else:
                # Normal or Frost-Forced Heating
                target = self.target_temperature if not frost_risk else (ANTI_FROST_TEMP + 1.0)
                await self._set_heaters(self._cur_temp < (target - 0.2))
        else:
            await self._set_heaters(False)

        # 5. Hardware Failure Detection
        self._check_hardware_performance()
        
        # 6. Learning
        if not (self._vacation_active or self._force_return or self._nearest_distance > 500 or self._hardware_failure):
            self._update_learning()
            
        self.async_write_ha_state()

    def _check_hardware_performance(self):
        """Detect if heaters are on but room is not warming up."""
        if self._heating_power > 90 and not self._window_open:
            now = time.time()
            if self._stuck_check_time is None:
                self._stuck_check_time, self._stuck_check_temp = now, self._cur_temp
                return
            
            # Check every 45 minutes of continuous high power
            if (now - self._stuck_check_time) > 2700:
                expected_rise = self._heating_rate * 45 * 0.5 # Expect at least 50% of learned rate
                actual_rise = self._cur_temp - self._stuck_check_temp
                
                if actual_rise < 0.1 and actual_rise < expected_rise:
                    _LOGGER.error("Hardware Failure Warning for %s: Power at 100%% but temp not rising!", self._name)
                    self._hardware_failure = True
                else:
                    self._hardware_failure = False
                
                self._stuck_check_time, self._stuck_check_temp = now, self._cur_temp
        else:
            self._stuck_check_time, self._stuck_check_temp = None, None

    def _update_learning(self):
        """Learns with sanity clamping."""
        now = time.time()
        if self._cur_temp is None or self._last_learning_temp is None:
            self._last_learning_temp, self._last_learning_time = self._cur_temp, now
            return
        dt = (now - self._last_learning_time) / 60
        if dt < 15: return
        
        rate = abs((self._cur_temp - self._last_learning_temp) / dt)
        # Clamping: ignore impossible values
        if rate < MIN_HEATING_RATE or rate > MAX_HEATING_RATE: return

        if self._heating_power > 90:
            self._heating_rate = (self._heating_rate * (1-LEARNING_ALPHA)) + (rate * LEARNING_ALPHA)
        elif self._heating_power < 10:
            self._cooling_rate = (self._cooling_rate * (1-LEARNING_ALPHA)) + (rate * LEARNING_ALPHA)
            
        self._last_learning_temp, self._last_learning_time = self._cur_temp, now

    async def _set_heaters(self, on: bool):
        if on: self._daily_usage_seconds += 60
        if self._last_heater_state == on: return
        self._last_heater_state = on
        for eid in self._heaters:
            await self.hass.services.async_call("homeassistant", "turn_on" if on else "turn_off", {"entity_id": eid})

    # Standard HA Boilerplate & Dynamic Properties
    @property
    def comfort_temp(self) -> float:
        """Return the target comfort temperature."""
        if self._data.get(CONF_OVERRIDE_COMFORT):
            return float(self._data.get(CONF_COMFORT_TEMP, 21.0))
        return float(self._get_global(CONF_COMFORT_TEMP, 21.0))

    @property
    def eco_temp(self) -> float:
        """Return the eco temperature."""
        return float(self._get_global(CONF_ECO_TEMP, 18.0))

    @property
    def away_temp(self) -> float:
        """Return the away temperature."""
        if self._data.get(CONF_OVERRIDE_AWAY):
            return float(self._data.get(CONF_AWAY_TEMP, 15.0))
        return float(self._get_global(CONF_AWAY_TEMP, 15.0))

    @property
    def target_temperature(self) -> float:
        if self._vacation_active: return ANTI_FROST_TEMP
        if self._force_return: return self.comfort_temp
        if self._preset_mode == MODE_MANUAL: return self._target_temp
        
        base = self._target_temp
        if self._outdoor_temp is not None and self._outdoor_temp < 5:
            base += (5 - self._outdoor_temp) * 0.1
            
        if self._preset_mode == MODE_AWAY and self._cur_temp:
            if (self._nearest_distance / 1000) / (self._get_global(CONF_AVG_SPEED, 50.0) / 60) <= (base - self._cur_temp) / self._heating_rate:
                return base
            return self.away_temp if self._nearest_distance > 15000 else self.eco_temp
        return base

    async def _update_state(self):
        """Update internal state based on global settings, schedule and presence."""
        g = self.hass.data[DOMAIN].get("global")
        if not g:
            return

        # 1. Vacation Mode (Global)
        vacation_status = g.data.get(CONF_VACATION_STATE, "off")
        self._vacation_active = (vacation_status == "on")

        # 2. Schedule Logic
        if self._preset_mode != MODE_MANUAL:
            sched_id = self._data.get(CONF_SCHEDULE) if self._data.get(CONF_OVERRIDE_SCHEDULE) else g.data.get(CONF_SCHEDULE)
            if sched_id and (s_state := self.hass.states.get(sched_id)):
                # If schedule is ON, target is comfort, else eco
                self._target_temp = self.comfort_temp if s_state.state == STATE_ON else self.eco_temp

        # 3. Presence & Geofencing
        presence_ids = self._data.get(CONF_PRESENCE_SENSORS) if self._data.get(CONF_OVERRIDE_PRESENCE) else g.data.get(CONF_PRESENCE_SENSORS)
        if presence_ids:
            any_home = False
            min_dist = 999999.0
            for pid in presence_ids:
                if (p_state := self.hass.states.get(pid)):
                    if p_state.state == "home":
                        any_home = True
                        min_dist = 0.0
                        break
                    # Calculate distance if tracker has coordinates
                    lat = p_state.attributes.get(ATTR_LATITUDE)
                    lon = p_state.attributes.get(ATTR_LONGITUDE)
                    if lat and lon and self.hass.config.latitude and self.hass.config.longitude:
                        dist = location.distance(lat, lon, self.hass.config.latitude, self.hass.config.longitude)
                        if dist < min_dist: min_dist = dist
            
            self._nearest_distance = min_dist
            if any_home:
                if self._preset_mode == MODE_AWAY:
                    self._preset_mode = MODE_SMART_SCHEDULE
            elif self._preset_mode != MODE_MANUAL:
                self._preset_mode = MODE_AWAY

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if self not in self.hass.data[DOMAIN]["rooms"]: self.hass.data[DOMAIN]["rooms"].append(self)
        
        old = await self.async_get_last_state()
        if old:
            self._heating_rate = old.attributes.get(ATTR_HEATING_RATE, self._heating_rate)
            self._cooling_rate = old.attributes.get(ATTR_COOLING_RATE, self._cooling_rate)
            self._daily_usage_seconds = old.attributes.get(ATTR_DAILY_USAGE, 0) * 60
            if old.state not in ("unknown", "unavailable") and self._cur_temp is None:
                try:
                    self._cur_temp = float(old.attributes.get("current_temperature") or old.state)
                except (ValueError, TypeError):
                    pass

        if self._sensor_id and (state := self.hass.states.get(self._sensor_id)):
            if state.state not in ("unknown", "unavailable"):
                try:
                    self._cur_temp = float(state.state)
                except ValueError:
                    pass

        self.async_on_remove(async_track_time_interval(self.hass, self._async_tick, timedelta(minutes=1)))
        self._setup_listeners()
        # Initial update
        self.hass.async_create_task(self._async_tick(None))

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        if self in self.hass.data[DOMAIN]["rooms"]:
            self.hass.data[DOMAIN]["rooms"].remove(self)
        await super().async_will_remove_from_hass()

    def _setup_listeners(self):
        for listener in self._event_listeners: listener()
        self._event_listeners = []
        
        # Temp Sensor
        if self._sensor_id:
            self._event_listeners.append(async_track_state_change_event(self.hass, [self._sensor_id], self._on_sensor))
        
        # Window Sensor
        if self._window_sensor_id:
            self._event_listeners.append(async_track_state_change_event(self.hass, [self._window_sensor_id], self._on_window))

        # Heater Entities
        if self._heaters:
            self._event_listeners.append(async_track_state_change_event(self.hass, self._heaters, self._on_heater_change))

    @callback
    def _on_heater_change(self, event):
        """Update internal state if a heater is changed externally."""
        s = event.data.get("new_state")
        if s:
            self._last_heater_state = (s.state == STATE_ON)
            self.async_write_ha_state()

    @callback
    def _on_sensor(self, event):
        s = event.data.get("new_state")
        if s and s.state not in ("unknown", "unavailable"): self._cur_temp = float(s.state)
    @callback
    def _on_window(self, event):
        s = event.data.get("new_state")
        if s: 
            self._window_open = (s.state == STATE_ON)
            self.hass.async_create_task(self._async_tick(None))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (t := kwargs.get(ATTR_TEMPERATURE)): 
            self._target_temp, self._preset_mode = t, MODE_MANUAL
            self._manual_start_time = time.time()
            await self._async_tick(None)

    def _get_global(self, key: str, default: Any) -> Any:
        g = self.hass.data[DOMAIN].get("global")
        return g.data.get(key, default) if g else default

    @property
    def name(self) -> str: return self._name

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{DOMAIN}_{self._name.lower().replace(' ', '_')}_{self._sensor_id}"

    @property
    def temperature_unit(self) -> str: return UnitOfTemperature.CELSIUS
    @property
    def current_temperature(self) -> float | None: return self._cur_temp
    @property
    def hvac_mode(self) -> HVACMode: return self._hvac_mode
    @property
    def hvac_modes(self) -> list[HVACMode]: return [HVACMode.HEAT, HVACMode.OFF]
    @property
    def preset_mode(self) -> str | None: return self._preset_mode
    @property
    def preset_modes(self) -> list[str]: return [MODE_SMART_SCHEDULE, MODE_MANUAL, MODE_AWAY, MODE_VACATION]
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._hvac_mode = hvac_mode
        await self._async_tick(None)
    async def async_set_preset_mode(self, m: str) -> None:
        self._preset_mode = m
        if m == MODE_MANUAL: self._manual_start_time = time.time()
        await self._async_tick(None)
