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
    HVACAction,
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
    CONF_WINDOW_DELAY,
    CONF_PRESENCE_SENSORS,
    CONF_SCHEDULE,
    CONF_WEATHER,
    CONF_OVERRIDE_SWITCH,
    CONF_VACATION_STATE,
    CONF_VACATION_ENTITY,
    CONF_COMFORT_TEMP,
    CONF_ECO_TEMP,
    CONF_AWAY_TEMP,
    CONF_AVG_SPEED,
    CONF_MANUAL_OVERRIDE_MODE,
    CONF_MANUAL_OVERRIDE_HOURS,
    MANUAL_OVERRIDE_TIMER,
    MANUAL_OVERRIDE_NEXT_SCHEDULE,
    MANUAL_OVERRIDE_NEXT_SCHEDULE_ON,
    MANUAL_OVERRIDE_ON_ARRIVAL,
    MANUAL_OVERRIDE_ON_DEPARTURE,
    MANUAL_OVERRIDE_PERMANENT,
    MANUAL_OVERRIDE_TIMER_OR_SCHEDULE,
    CONF_OVERRIDE_COMFORT,
    CONF_OVERRIDE_AWAY,
    CONF_OVERRIDE_PRESENCE,
    CONF_OVERRIDE_WEATHER,
    CONF_OVERRIDE_SCHEDULE,
    CONF_OVERRIDE_MANUAL_MODE,
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
    ATTR_EMERGENCY_HEAT,
    ATTR_OUTDOOR_TEMP,
    CONF_ENERGY_PRICE_KWH,
    CONF_ENERGY_ANNUAL_DATA,
    ATTR_SAVED_AWAY_H_TODAY,
    ATTR_SAVED_WINDOW_H_TODAY,
    ATTR_SAVED_ECO_H_TODAY,
    ATTR_SAVED_AWAY_H_MONTH,
    ATTR_SAVED_WINDOW_H_MONTH,
    ATTR_SAVED_ECO_H_MONTH,
    ATTR_ACTUAL_HEATING_H_MONTH,
    ATTR_SAVINGS_KWH_MONTH,
    ATTR_SAVINGS_EUR_MONTH,
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
    entity = SmartClimatePro(hass, entry, data)
    hass.data[DOMAIN].setdefault("climate_entities_by_entry", {})[entry.entry_id] = entity
    async_add_entities([entity])


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
        raw_sensor = data[CONF_SENSOR]
        self._sensor_ids: list[str] = (
            raw_sensor if isinstance(raw_sensor, list) else [raw_sensor]
        )
        self._sensor_readings: dict[str, float | None] = {
            sid: None for sid in self._sensor_ids
        }
        self._window_sensor_id = data.get(CONF_WINDOW_SENSOR)

        # State
        self._cur_temp: float | None = None
        self._outdoor_temp: float | None = None
        self._target_temp: float | None = None
        self._hvac_mode = HVACMode.HEAT
        self._preset_mode = MODE_SMART_SCHEDULE
        self._window_ajar = False
        self._window_ajar_since: float | None = None
        self._window_open = False
        self._vacation_active = False
        self._emergency_heat_active = False
        self._force_return = False
        self._nearest_distance = 0.0
        self._last_nearest_distance = 0.0
        self._was_any_home = False
        self._schedule_state_at_override: str | None = None

        # Duty cycle tracking
        self._duty_history: deque[float] = deque(maxlen=DUTY_CYCLE_WINDOW)
        self._heating_power = 0.0

        # Learning
        self._heating_rate = 0.05
        self._cooling_rate = 0.02
        self._last_learning_temp: float | None = None
        self._last_learning_time: float | None = None

        # Daily usage tracking
        self._daily_usage_seconds = 0
        self._last_usage_reset_date: date | None = None

        # Savings tracking — daily (reset at midnight)
        self._daily_away_s: int = 0
        self._daily_window_s: int = 0
        self._daily_eco_s: int = 0

        # Savings tracking — monthly (reset on 1st of month)
        self._monthly_actual_heating_s: int = 0
        self._monthly_away_s: int = 0
        self._monthly_window_s: int = 0
        self._monthly_eco_s: int = 0
        self._last_savings_reset_month: int | None = None

        # Heating Degree Hours saved per feature — accumulated at each tick using
        # the actual outdoor temperature at that moment (HDH method)
        self._monthly_hdh_away: float = 0.0
        self._monthly_hdh_window: float = 0.0
        self._monthly_hdh_eco: float = 0.0

        # Companion sensor entities (set by sensor platform after climate setup)
        self._companion_sensors: list = []
        self._savings_cache: dict = {}

        # Safety & Fail-safe state
        self._last_heater_state: bool | None = None   # switch/water_heater bang-bang
        self._last_climate_active: bool | None = None  # climate entity setpoint mode
        self._last_target_temp: float | None = None
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
        attrs: dict[str, Any] = {
            ATTR_HEATING_POWER: round(self._heating_power, 1),
            ATTR_HEATING_RATE: round(self._heating_rate, 4),
            ATTR_COOLING_RATE: round(self._cooling_rate, 4),
            ATTR_DAILY_USAGE: round(self._daily_usage_seconds / 60, 1),
            ATTR_NEAREST_DISTANCE: round(self._nearest_distance, 0),
            ATTR_VACATION_MODE: self._vacation_active,
            ATTR_EMERGENCY_HEAT: self._emergency_heat_active,
            ATTR_OUTDOOR_TEMP: self._outdoor_temp,
            "hardware_failure_warning": self._hardware_failure,
            "manual_timeout_remaining_min": self._get_manual_timeout(),
            "preset_mode": self._preset_mode,
            "target_temp": self._target_temp,
            "manual_start_time": self._manual_start_time,
            # Savings — daily
            ATTR_SAVED_AWAY_H_TODAY: round(self._daily_away_s / 3600, 2),
            ATTR_SAVED_WINDOW_H_TODAY: round(self._daily_window_s / 3600, 2),
            ATTR_SAVED_ECO_H_TODAY: round(self._daily_eco_s / 3600, 2),
            # Savings — monthly (also persisted for restore after restart)
            ATTR_SAVED_AWAY_H_MONTH: round(self._monthly_away_s / 3600, 2),
            ATTR_SAVED_WINDOW_H_MONTH: round(self._monthly_window_s / 3600, 2),
            ATTR_SAVED_ECO_H_MONTH: round(self._monthly_eco_s / 3600, 2),
            ATTR_ACTUAL_HEATING_H_MONTH: round(self._monthly_actual_heating_s / 3600, 2),
            # Internal state (used by RestoreEntity)
            "_schedule_state_at_override": self._schedule_state_at_override,
            # Internal monthly state (used by RestoreEntity)
            "_monthly_actual_heating_s": self._monthly_actual_heating_s,
            "_monthly_away_s": self._monthly_away_s,
            "_monthly_window_s": self._monthly_window_s,
            "_monthly_eco_s": self._monthly_eco_s,
            "_monthly_hdh_away": self._monthly_hdh_away,
            "_monthly_hdh_window": self._monthly_hdh_window,
            "_monthly_hdh_eco": self._monthly_hdh_eco,
            "_last_savings_reset_month": self._last_savings_reset_month,
        }
        attrs.update(self._compute_savings_est())
        return attrs

    def _get_manual_override_mode(self) -> str:
        """Return the effective manual override revert mode for this room."""
        if self._entry.data.get(CONF_OVERRIDE_MANUAL_MODE):
            return self._entry.data.get(CONF_MANUAL_OVERRIDE_MODE, MANUAL_OVERRIDE_TIMER)
        return self._get_global(CONF_MANUAL_OVERRIDE_MODE, MANUAL_OVERRIDE_TIMER)

    def _get_manual_override_hours(self) -> float:
        """Return the effective timer duration (hours) for this room."""
        if self._entry.data.get(CONF_OVERRIDE_MANUAL_MODE):
            h = self._entry.data.get(CONF_MANUAL_OVERRIDE_HOURS)
            if h is not None:
                return float(h)
        return float(self._get_global(CONF_MANUAL_OVERRIDE_HOURS, MANUAL_OVERRIDE_TIMEOUT_HRS))

    def _get_manual_timeout(self) -> int:
        """Return remaining minutes before manual mode reverts (timer modes only)."""
        if self._preset_mode != MODE_MANUAL or not self._manual_start_time:
            return 0
        mode = self._get_manual_override_mode()
        if mode not in (MANUAL_OVERRIDE_TIMER, MANUAL_OVERRIDE_TIMER_OR_SCHEDULE):
            return 0
        elapsed = (time.time() - self._manual_start_time) / 60
        return max(0, int((self._get_manual_override_hours() * 60) - elapsed))

    def _record_schedule_state_for_override(self) -> None:
        """Snapshot the current schedule state so schedule-based revert modes can detect transitions."""
        mode = self._get_manual_override_mode()
        if mode not in (
            MANUAL_OVERRIDE_NEXT_SCHEDULE,
            MANUAL_OVERRIDE_NEXT_SCHEDULE_ON,
            MANUAL_OVERRIDE_TIMER_OR_SCHEDULE,
        ):
            self._schedule_state_at_override = None
            return
        g = self.hass.data[DOMAIN].get("global")
        sched_id = (
            self._entry.data.get(CONF_SCHEDULE)
            if self._entry.data.get(CONF_OVERRIDE_SCHEDULE)
            else (g.data.get(CONF_SCHEDULE) if g else None)
        )
        if sched_id and (s := self.hass.states.get(sched_id)):
            self._schedule_state_at_override = s.state
        else:
            self._schedule_state_at_override = None

    def _handle_external_temp_override(self, temp: float) -> None:
        """Handle a temperature change made directly on a TRV or via an external app."""
        if self._vacation_active or self._emergency_heat_active:
            return
        self._target_temp = temp
        self._last_target_temp = temp  # prevent immediate re-trigger
        self._preset_mode = MODE_MANUAL
        self._force_return = False
        self._manual_start_time = time.time()
        self._record_schedule_state_for_override()
        _LOGGER.info(
            "External temperature override detected on %s: %.1f°C → switching to manual mode (%s)",
            self._name,
            temp,
            self._get_manual_override_mode(),
        )
        self.hass.async_create_task(self._async_tick(None))

    def _update_heating_power(self, power: float) -> None:
        """Track duty cycle to compute heating power percentage.

        power is a fraction [0.0-1.0]: 1.0 for switches fully on, or the
        estimated valve openness for TRV entities.
        """
        self._duty_history.append(power)
        if self._duty_history:
            self._heating_power = (
                sum(self._duty_history) / len(self._duty_history)
            ) * 100.0

    def _estimate_heater_power(
        self, switch_on: bool, climate_active: bool, target: float
    ) -> float:
        """Estimate combined heating power fraction [0.0-1.0] across all heaters.

        Switches contribute binary 0/1. Climate entities (TRVs) contribute a
        valve-openness fraction derived from their internal temperature sensor:
        fully open when ≥2°C below target, closed when at or above target.
        Falls back to binary climate_active when the TRV has no temperature data.
        """
        contributions: list[float] = []
        for eid in self._heaters:
            if eid.split(".")[0] == "climate":
                if not climate_active:
                    contributions.append(0.0)
                    continue
                state = self.hass.states.get(eid)
                trv_temp = state.attributes.get("current_temperature") if state else None
                if trv_temp is not None:
                    try:
                        fraction = min(1.0, max(0.0, (target - float(trv_temp)) / 2.0))
                        contributions.append(fraction)
                    except (ValueError, TypeError):
                        contributions.append(1.0)
                else:
                    contributions.append(1.0)
            else:
                contributions.append(1.0 if switch_on else 0.0)
        return sum(contributions) / len(contributions) if contributions else 0.0

    def _check_daily_reset(self) -> None:
        """Reset daily counters at midnight and monthly counters on the 1st."""
        now = dt_util.now()
        today = now.date()
        month = now.month

        if self._last_savings_reset_month != month:
            self._monthly_actual_heating_s = 0
            self._monthly_away_s = 0
            self._monthly_window_s = 0
            self._monthly_eco_s = 0
            self._monthly_hdh_away = 0.0
            self._monthly_hdh_window = 0.0
            self._monthly_hdh_eco = 0.0
            self._last_savings_reset_month = month

        if self._last_usage_reset_date != today:
            self._daily_usage_seconds = 0
            self._daily_away_s = 0
            self._daily_window_s = 0
            self._daily_eco_s = 0
            self._last_usage_reset_date = today

    def _compute_cur_temp(self) -> float | None:
        """Average configured sensor readings; fall back to TRV internal sensor."""
        values = [v for v in self._sensor_readings.values() if v is not None]
        if values:
            return sum(values) / len(values)
        # Fallback: read current_temperature attribute from any available climate heater
        for eid in self._heaters:
            if eid.split(".")[0] == "climate":
                state = self.hass.states.get(eid)
                if state:
                    temp = state.attributes.get("current_temperature")
                    if temp is not None:
                        try:
                            return float(temp)
                        except (ValueError, TypeError):
                            pass
        return None

    async def _async_tick(self, now):
        """Robust Heartbeat with Fail-Safe checks."""
        # now is a datetime when called by the scheduler, None for manual triggers
        scheduled = now is not None

        # 0. Daily usage reset check
        self._check_daily_reset()

        # Recompute cur_temp on every tick — also picks up TRV fallback when
        # configured sensors are offline
        self._cur_temp = self._compute_cur_temp()

        await self._update_state()
        self._update_force_return()

        # 1. Manual revert guard (timer modes)
        if self._preset_mode == MODE_MANUAL:
            ovr_mode = self._get_manual_override_mode()
            if ovr_mode in (MANUAL_OVERRIDE_TIMER, MANUAL_OVERRIDE_TIMER_OR_SCHEDULE):
                if self._get_manual_timeout() == 0:
                    _LOGGER.info(
                        "Manual override timed out for %s. Returning to schedule.",
                        self._name,
                    )
                    self._preset_mode = MODE_SMART_SCHEDULE
                    self._force_return = False
                    self._schedule_state_at_override = None

        # 2. Safety Check: Sensor failure
        if self._cur_temp is None:
            _LOGGER.error(
                "Emergency: All sensors offline for %s (configured: %s)",
                self._name,
                self._sensor_ids,
            )
            heater_on = (dt_util.now().minute % 10) == 0  # Minimal pulse
            if scheduled and heater_on:
                self._daily_usage_seconds += 60
            await self._set_heaters(
                switch_on=heater_on,
                climate_active=heater_on,
                target_temp=ANTI_FROST_TEMP if heater_on else None,
            )
            self._update_heating_power(1.0 if heater_on else 0.0)
            return

        # 3. Window delay: compute effective window_open from raw ajar state
        if self._window_ajar:
            delay_min = float(self._entry.data.get(CONF_WINDOW_DELAY, 0))
            if delay_min <= 0:
                self._window_open = True
            elif self._window_ajar_since is not None:
                elapsed_min = (time.time() - self._window_ajar_since) / 60
                self._window_open = elapsed_min >= delay_min
        else:
            self._window_open = False

        # 4. Frost Guard (Priority over Window Open)
        frost_risk = self._cur_temp < ANTI_FROST_TEMP

        # 5. Compute effective target (pure read, no side effects)
        effective_target = self._compute_effective_target()

        # 6. Control Logic
        if self._emergency_heat_active:
            # Emergency cold override: force all heaters to maximum regardless of
            # window state or hvac_mode. Activated via the global override switch.
            target = self.max_temp
            climate_active = True
            switch_on = True
        else:
            # Frost protection is unconditional: overrides hvac_mode=OFF and open windows
            target = ANTI_FROST_TEMP if frost_risk else effective_target

            # Climate entities (TRVs/AC): setpoint mode — Vesta decides whether heating
            # should be active and sends the target temperature; the device manages its
            # own valve/compressor internally.
            climate_active = frost_risk or (
                self._hvac_mode == HVACMode.HEAT and not self._window_open
            )

            # Switches and other simple heaters: bang-bang control — Vesta acts as the
            # thermostat and decides when to turn the device on or off.
            switch_on = False
            if frost_risk:
                switch_on = self._cur_temp < (ANTI_FROST_TEMP + 0.8)
            elif self._hvac_mode == HVACMode.HEAT and not self._window_open:
                switch_on = self._cur_temp < (effective_target - 0.2)

        # Count usage on scheduled ticks (use switch_on as the "actively heating" proxy)
        if scheduled:
            if switch_on:
                self._daily_usage_seconds += 60
                self._monthly_actual_heating_s += 60

            # Feature-specific savings tracking (time smart features kept temp lower)
            if not frost_risk and self._hvac_mode == HVACMode.HEAT:
                comfort = self.comfort_temp
                outdoor = self._outdoor_temp
                # HDH factor: how much of the base ΔT (comfort - outdoor) was saved
                # this tick. Integrated over time so the estimate reflects actual
                # outdoor conditions rather than a single snapshot at report time.
                if outdoor is not None and comfort > outdoor:
                    base_delta = max(1.0, comfort - outdoor)
                    hdh_away_tick = (comfort - self.away_temp) / base_delta / 60
                    hdh_window_tick = (comfort - ANTI_FROST_TEMP) / base_delta / 60
                else:
                    # Fraunhofer fallback ratios when outdoor temp is unavailable
                    hdh_away_tick = 0.23 / 60
                    hdh_window_tick = 1.0 / 60

                if self._preset_mode == MODE_AWAY:
                    self._daily_away_s += 60
                    self._monthly_away_s += 60
                    self._monthly_hdh_away += hdh_away_tick
                elif self._window_open:
                    self._daily_window_s += 60
                    self._monthly_window_s += 60
                    self._monthly_hdh_window += hdh_window_tick
                elif (
                    self._preset_mode == MODE_SMART_SCHEDULE
                    and effective_target < comfort
                ):
                    self._daily_eco_s += 60
                    self._monthly_eco_s += 60
                    # Scale eco HDH by how far below comfort the actual target is
                    if outdoor is not None and comfort > outdoor:
                        hdh_eco_tick = (comfort - effective_target) / base_delta / 60
                    else:
                        eco_ratio = (comfort - effective_target) / max(
                            1.0, comfort - self.eco_temp
                        )
                        hdh_eco_tick = 0.15 * eco_ratio / 60
                    self._monthly_hdh_eco += hdh_eco_tick

        await self._set_heaters(switch_on=switch_on, climate_active=climate_active, target_temp=target)

        # 7. Update duty cycle — use TRV internal sensor for valve-openness estimate
        self._update_heating_power(
            self._estimate_heater_power(switch_on, climate_active, target)
        )

        # 8. Hardware Failure Detection
        self._check_hardware_performance()

        # 9. Learning
        if not (
            self._vacation_active
            or self._emergency_heat_active
            or self._force_return
            or self._nearest_distance > 500
            or self._hardware_failure
        ):
            self._update_learning()

        self._savings_cache = self._compute_savings_est()
        self.async_write_ha_state()
        for sensor in self._companion_sensors:
            sensor.async_write_ha_state()

        # 10. Notify boiler coordinator so it can aggregate demand across all rooms
        coordinator = self.hass.data[DOMAIN].get("boiler_coordinator")
        if coordinator:
            await coordinator.async_update(self.hass.data[DOMAIN].get("rooms", []))

    def _update_force_return(self) -> None:
        """Re-evaluate pre-heating on every tick.

        Called only from _async_tick so state mutation stays out of properties.

        Pre-heating is only activated when the person is actively approaching
        home (distance decreasing by more than GPS noise) AND the estimated
        travel time is shorter than the time needed to heat the room. This
        prevents false triggers when the person is stationary near home (e.g.
        at the office, visiting a friend, or at the supermarket).
        """
        if self._preset_mode != MODE_AWAY or self._cur_temp is None:
            # Keep _last_nearest_distance in sync so the first away tick has
            # an accurate baseline and doesn't falsely detect an approach.
            self._last_nearest_distance = self._nearest_distance
            self._force_return = False
            return

        # 500 m threshold filters out GPS noise between ticks
        approaching = self._nearest_distance < (self._last_nearest_distance - 500)
        self._last_nearest_distance = self._nearest_distance

        if not approaching:
            self._force_return = False
            return

        base = self.comfort_temp
        if self._outdoor_temp is not None and self._outdoor_temp < 5:
            base += (5 - self._outdoor_temp) * 0.1
        avg_speed = max(self._get_global(CONF_AVG_SPEED, 50.0), 1.0)
        h_rate = max(self._heating_rate, MIN_HEATING_RATE)
        travel_time_min = (self._nearest_distance / 1000) / (avg_speed / 60)
        temp_deficit = base - self._cur_temp
        if temp_deficit > 0:
            heat_time_min = temp_deficit / h_rate
            self._force_return = travel_time_min <= heat_time_min
        else:
            self._force_return = False

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
            return self.away_temp
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

    def _compute_savings_est(self) -> dict[str, Any]:
        """Estimate monthly kWh/€ savings using the Heating Degree Hours method.

        HDH values are accumulated at each scheduled tick using the actual outdoor
        temperature at that moment, so the estimate integrates real conditions over
        the month rather than applying a single end-of-period snapshot factor.
        """
        g = self.hass.data[DOMAIN].get("global")
        if not g:
            return {}
        price = g.data.get(CONF_ENERGY_PRICE_KWH)
        annual_data = g.data.get(CONF_ENERGY_ANNUAL_DATA) or {}
        annual_kwh = annual_data.get(str(dt_util.now().year))
        if not annual_kwh or not price:
            return {}

        kwh_per_hour = float(annual_kwh) / 8760
        price = float(price)

        saved_kwh = (
            self._monthly_hdh_away
            + self._monthly_hdh_eco
            + self._monthly_hdh_window
        ) * kwh_per_hour

        return {
            ATTR_SAVINGS_KWH_MONTH: round(saved_kwh, 2),
            ATTR_SAVINGS_EUR_MONTH: round(saved_kwh * price, 2),
        }

    @staticmethod
    def _heater_active(state) -> bool:
        """Return True if a heater entity is currently active."""
        if state is None:
            return False
        domain = state.entity_id.split(".")[0]
        # climate / water_heater: active when not "off" (state is "heat", "auto", etc.)
        if domain in ("climate", "water_heater"):
            return state.state not in ("off", "unavailable", "unknown")
        return state.state == STATE_ON

    async def _set_heaters(
        self,
        switch_on: bool,
        climate_active: bool,
        target_temp: float | None = None,
    ):
        # --- Idempotence checks ---
        switch_state_changed = self._last_heater_state != switch_on
        climate_state_changed = self._last_climate_active != climate_active
        climate_target_changed = (
            climate_active
            and target_temp is not None
            and target_temp != self._last_target_temp
        )

        if not switch_state_changed and not climate_state_changed and not climate_target_changed:
            return

        # Update trackers before issuing commands
        if switch_state_changed:
            self._last_heater_state = switch_on
        if climate_state_changed:
            self._last_climate_active = climate_active
        if not climate_active:
            self._last_target_temp = None
        elif target_temp is not None:
            self._last_target_temp = target_temp

        for eid in self._heaters:
            domain = eid.split(".")[0]
            if domain == "climate":
                # Setpoint mode: keep in heat mode while heating is desired and let
                # the TRV/AC manage its valve internally. Only turn off when Vesta
                # explicitly wants no heating (vacation, schedule off, window open…).
                if climate_state_changed:
                    await self.hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": eid, "hvac_mode": "heat" if climate_active else "off"},
                    )
                if climate_active and target_temp is not None and (
                    climate_state_changed or climate_target_changed
                ):
                    await self.hass.services.async_call(
                        "climate",
                        "set_temperature",
                        {"entity_id": eid, "temperature": target_temp},
                    )
            else:
                # Bang-bang for switches and other simple heaters
                if switch_state_changed:
                    await self.hass.services.async_call(
                        "homeassistant",
                        "turn_on" if switch_on else "turn_off",
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

        # 1. Vacation Mode (Global) — entity takes priority over static boolean
        vacation_entity_id = g.data.get(CONF_VACATION_ENTITY)
        if vacation_entity_id:
            v_state = self.hass.states.get(vacation_entity_id)
            self._vacation_active = v_state is not None and v_state.state == STATE_ON
        else:
            vacation_status = g.data.get(CONF_VACATION_STATE, False)
            if isinstance(vacation_status, str):
                self._vacation_active = vacation_status == "on"
            else:
                self._vacation_active = bool(vacation_status)

        # 1b. Emergency Heat Override Switch (Global)
        override_sw_id = g.data.get(CONF_OVERRIDE_SWITCH)
        if override_sw_id:
            sw_state = self.hass.states.get(override_sw_id)
            self._emergency_heat_active = sw_state is not None and sw_state.state == STATE_ON
        else:
            self._emergency_heat_active = False

        # 2. Schedule Logic: HA schedule entity
        sched_id = (
            self._entry.data.get(CONF_SCHEDULE)
            if self._entry.data.get(CONF_OVERRIDE_SCHEDULE)
            else g.data.get(CONF_SCHEDULE)
        )
        if sched_id and (s_state := self.hass.states.get(sched_id)):
            # Schedule-based manual revert (next_schedule / next_schedule_on / timer_or_schedule)
            if (
                self._preset_mode == MODE_MANUAL
                and self._schedule_state_at_override is not None
                and s_state.state != self._schedule_state_at_override
            ):
                ovr_mode = self._get_manual_override_mode()
                should_revert = (
                    ovr_mode == MANUAL_OVERRIDE_NEXT_SCHEDULE
                    or ovr_mode == MANUAL_OVERRIDE_TIMER_OR_SCHEDULE
                    or (ovr_mode == MANUAL_OVERRIDE_NEXT_SCHEDULE_ON and s_state.state == STATE_ON)
                )
                if should_revert:
                    _LOGGER.info(
                        "Schedule changed for %s: reverting manual override (%s).",
                        self._name,
                        ovr_mode,
                    )
                    self._preset_mode = MODE_SMART_SCHEDULE
                    self._force_return = False
                    self._schedule_state_at_override = None

        if self._preset_mode != MODE_MANUAL:
            if sched_id and (s_state := self.hass.states.get(sched_id)):
                if self._preset_mode == MODE_AWAY:
                    # In away mode the schedule cannot override temperature or turn
                    # off heating. Restore hvac_mode if a previous schedule block
                    # had turned it off.
                    if self._hvac_mode == HVACMode.OFF:
                        self._hvac_mode = HVACMode.HEAT
                else:
                    block_data = self._get_current_schedule_block_data(sched_id)

                    # Controlla se il blocco richiede spegnimento
                    mode = str((block_data or {}).get("mode", "")).lower().strip()
                    if mode == "off":
                        self._hvac_mode = HVACMode.OFF
                    else:
                        # Riattiva se era stato spento dallo schedule
                        if self._hvac_mode == HVACMode.OFF:
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
            ovr_mode = self._get_manual_override_mode()

            if any_home:
                if self._preset_mode == MODE_AWAY:
                    self._preset_mode = MODE_SMART_SCHEDULE
                    self._force_return = False
                elif (
                    self._preset_mode == MODE_MANUAL
                    and ovr_mode == MANUAL_OVERRIDE_ON_ARRIVAL
                    and not self._was_any_home
                ):
                    # Someone just arrived → revert manual override
                    _LOGGER.info(
                        "Arrival detected for %s: reverting manual override.", self._name
                    )
                    self._preset_mode = MODE_SMART_SCHEDULE
                    self._force_return = False
                    self._schedule_state_at_override = None
            elif self._preset_mode == MODE_MANUAL and ovr_mode == MANUAL_OVERRIDE_ON_DEPARTURE and self._was_any_home:
                # Everyone just left → revert manual override to away mode
                _LOGGER.info(
                    "Departure detected for %s: reverting manual override to away.", self._name
                )
                self._preset_mode = MODE_AWAY
                self._force_return = False
                self._schedule_state_at_override = None
            elif self._preset_mode not in (MODE_MANUAL, MODE_VACATION):
                self._preset_mode = MODE_AWAY
                self._force_return = False

            self._was_any_home = any_home

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
            self._monthly_actual_heating_s = int(
                old.attributes.get("_monthly_actual_heating_s", 0)
            )
            self._monthly_away_s = int(old.attributes.get("_monthly_away_s", 0))
            self._monthly_window_s = int(old.attributes.get("_monthly_window_s", 0))
            self._monthly_eco_s = int(old.attributes.get("_monthly_eco_s", 0))
            self._monthly_hdh_away = float(old.attributes.get("_monthly_hdh_away", 0.0))
            self._monthly_hdh_window = float(old.attributes.get("_monthly_hdh_window", 0.0))
            self._monthly_hdh_eco = float(old.attributes.get("_monthly_hdh_eco", 0.0))
            self._last_savings_reset_month = old.attributes.get(
                "_last_savings_reset_month"
            )
            self._schedule_state_at_override = old.attributes.get(
                "_schedule_state_at_override"
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

        for sid in self._sensor_ids:
            if state := self.hass.states.get(sid):
                if state.state not in ("unknown", "unavailable"):
                    try:
                        self._sensor_readings[sid] = float(state.state)
                    except (ValueError, TypeError):
                        pass
        self._cur_temp = self._compute_cur_temp()

        # Initialise heater state from reality to avoid a spurious command at startup
        if self._heaters:
            self._last_heater_state = any(
                self._heater_active(self.hass.states.get(eid))
                for eid in self._heaters
                if eid.split(".")[0] != "climate"
            )
            self._last_climate_active = any(
                self._heater_active(self.hass.states.get(eid))
                for eid in self._heaters
                if eid.split(".")[0] == "climate"
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
        self.hass.data[DOMAIN].get("climate_entities_by_entry", {}).pop(
            self._entry.entry_id, None
        )
        await super().async_will_remove_from_hass()

    def _setup_listeners(self):
        for listener in self._event_listeners:
            listener()
        self._event_listeners = []

        if self._sensor_ids:
            self._event_listeners.append(
                async_track_state_change_event(
                    self.hass, self._sensor_ids, self._on_sensor
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

        vacation_entity_id = g.data.get(CONF_VACATION_ENTITY) if g else None
        if vacation_entity_id:
            self._event_listeners.append(
                async_track_state_change_event(
                    self.hass, [vacation_entity_id], self._on_vacation_entity
                )
            )

        override_sw_id = g.data.get(CONF_OVERRIDE_SWITCH) if g else None
        if override_sw_id:
            self._event_listeners.append(
                async_track_state_change_event(
                    self.hass, [override_sw_id], self._on_override_switch
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
            domain = s.entity_id.split(".")[0]
            if domain == "climate":
                self._last_climate_active = self._heater_active(s)
                # Detect temperature change made directly on TRV or via external app
                trv_target = s.attributes.get("temperature")
                if trv_target is not None and self._last_target_temp is not None:
                    try:
                        if abs(float(trv_target) - self._last_target_temp) > 0.1:
                            self._handle_external_temp_override(float(trv_target))
                    except (ValueError, TypeError):
                        pass
            else:
                self._last_heater_state = self._heater_active(s)
            self.async_write_ha_state()

    @callback
    def _on_sensor(self, event):
        s = event.data.get("new_state")
        if s:
            if s.state not in ("unknown", "unavailable"):
                try:
                    self._sensor_readings[s.entity_id] = float(s.state)
                except (ValueError, TypeError):
                    self._sensor_readings[s.entity_id] = None
            else:
                self._sensor_readings[s.entity_id] = None
            self._cur_temp = self._compute_cur_temp()
            self.async_write_ha_state()

    @callback
    def _on_window(self, event):
        s = event.data.get("new_state")
        if not s:
            return
        is_open = s.state == STATE_ON
        if is_open:
            if not self._window_ajar:
                self._window_ajar = True
                self._window_ajar_since = time.time()
            # Trigger a tick so state is written; delay logic runs inside _async_tick
            self.hass.async_create_task(self._async_tick(None))
        else:
            self._window_ajar = False
            self._window_ajar_since = None
            self._window_open = False
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

    @callback
    def _on_vacation_entity(self, event):
        """React immediately when the vacation mode entity changes state."""
        self.hass.async_create_task(self._async_tick(None))

    @callback
    def _on_override_switch(self, event):
        """React immediately when the emergency heat override switch changes state."""
        self.hass.async_create_task(self._async_tick(None))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if t := kwargs.get(ATTR_TEMPERATURE):
            self._target_temp = t
            self._preset_mode = MODE_MANUAL
            self._force_return = False
            self._manual_start_time = time.time()
            self._record_schedule_state_for_override()
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
    def hvac_action(self) -> HVACAction:
        if self._hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self._cur_temp is not None:
            effective_target = self._compute_effective_target()
            frost_risk = self._cur_temp < ANTI_FROST_TEMP
            target = ANTI_FROST_TEMP if frost_risk else effective_target
            actively_heating = (frost_risk or (
                not self._window_open and self._cur_temp < (target - 0.2)
            ))
            if actively_heating:
                return HVACAction.HEATING
        return HVACAction.IDLE

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
            self._record_schedule_state_for_override()
        else:
            self._schedule_state_at_override = None
        await self._async_tick(None)