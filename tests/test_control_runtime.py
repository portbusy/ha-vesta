"""Regression tests for control priority, transitions and actuator failures."""
import time
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.exceptions import HomeAssistantError

from custom_components.vesta.const import DOMAIN
from custom_components.vesta.store import ScheduleStore
from .runtime_helpers import make_room


@pytest.mark.parametrize("temperature,off,season,window,emergency,expected", [
    (4, True, False, True, False, True),
    (4, True, True, True, False, True),
    (5.5, True, True, False, False, False),
    (18, True, True, False, True, True),
    (18, False, True, True, False, False),
    (18, False, True, False, False, True),
    (22, False, True, False, False, False),
    (18, False, False, False, False, False),
])
async def test_actuators_boiler_and_ui_agree(hass, temperature, off, season, window, emergency, expected):
    room = make_room(hass, {"heating_season_active": season, "override_switch": "input_boolean.emergency"})
    hass.states.async_set("sensor.room", str(temperature))
    hass.states.async_set("input_boolean.emergency", "on" if emergency else "off")
    room._user_hvac_off = off
    room._window_states = {"binary_sensor.window": window}
    room._window_ajar_since = {"binary_sensor.window": time.time() - 60}
    room._set_heaters = AsyncMock()
    await room._async_tick(None)
    assert room._set_heaters.await_args.kwargs["switch_on"] is expected
    assert room.boiler_demand is expected
    assert (room.hvac_action == HVACAction.HEATING) is expected
    if temperature < 5:
        assert room.target_temperature == room.boiler_target_temperature == 5


async def test_off_survives_active_schedule_and_heat_resumes(hass):
    room = make_room(hass, {"schedule_entity": "schedule.house"})
    hass.states.async_set("schedule.house", "on", {"temp": 23})
    room._set_heaters = AsyncMock()
    await room.async_set_hvac_mode(HVACMode.OFF)
    await room._async_tick(None)
    assert room.hvac_mode == HVACMode.OFF
    assert not room.boiler_demand
    await room.async_set_hvac_mode(HVACMode.HEAT)
    assert room.target_temperature == 23
    assert room.boiler_demand


async def test_manual_expiry_applies_current_schedule_in_same_tick(hass):
    room = make_room(hass, {"schedule_entity": "schedule.house", "manual_override_hours": 1})
    hass.states.async_set("schedule.house", "on", {"temp": 19})
    room._preset_mode = "manual"
    room._manual_start_time = time.time() - 7200
    room._target_temp = 28
    room._set_heaters = AsyncMock()
    await room._async_tick(None)
    assert room.preset_mode == "smart_schedule"
    assert room.target_temperature == 19


async def test_manual_away_survives_departure_and_arrival(hass):
    room = make_room(hass, {"presence_sensors": ["person.test"]})
    room._set_heaters = AsyncMock()
    hass.states.async_set("person.test", "not_home")
    await room.async_set_preset_mode("away")
    assert not room._away_set_by_presence
    hass.states.async_set("person.test", "home")
    await room._async_tick(None)
    assert room.preset_mode == "away"


async def test_unknown_presence_does_not_trigger_departure(hass):
    room = make_room(hass, {"presence_sensors": ["person.test"]})
    room._set_heaters = AsyncMock()
    hass.states.async_set("person.test", "home")
    await room._async_tick(None)
    hass.states.async_set("person.test", "unavailable")
    await room._async_tick(None)
    assert room.preset_mode == "smart_schedule"


async def test_vacation_does_not_turn_off_during_off_schedule_block(hass):
    room = make_room(hass, {"schedule_entity": "schedule.house"})
    hass.states.async_set("sensor.room", "5.5")
    hass.states.async_set("schedule.house", "on", {"mode": "off"})
    room._set_heaters = AsyncMock()
    await room.async_set_preset_mode("vacation")
    assert room.hvac_mode == HVACMode.HEAT
    assert room.target_temperature == 5


async def test_failed_heater_is_retried_without_skipping_other_heaters(hass, monkeypatch):
    room = make_room(hass, data={"heaters": ["switch.bad", "switch.good"]})
    async def send(domain, service, data, **kwargs):
        if data["entity_id"] == "switch.bad":
            raise HomeAssistantError("offline")
    service = AsyncMock(side_effect=send)
    monkeypatch.setattr(type(hass.services), "async_call", service)
    await room._set_heaters(True, True, 21)
    assert service.await_count == 2
    assert "switch.bad" not in room._heater_states
    assert room._heater_states["switch.good"]
    service.side_effect = None
    await room._set_heaters(True, True, 21)
    assert service.await_count == 3
    assert service.await_args.kwargs["blocking"] is True


async def test_fahrenheit_sensor_and_rounded_device_target(hass, monkeypatch):
    from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
    hass.config.units = US_CUSTOMARY_SYSTEM
    room = make_room(hass)
    hass.states.async_set("sensor.room", "68", {"unit_of_measurement": "°F"})
    hass.states.async_set("climate.trv", "heat", {"current_temperature": 68, "target_temp_step": 1, "min_temp": 50, "max_temp": 86})
    assert room._compute_cur_temp() == pytest.approx(20)
    hass.states.async_set("sensor.room", "unavailable")
    assert room._compute_cur_temp() == pytest.approx(20)
    service = AsyncMock()
    monkeypatch.setattr(type(hass.services), "async_call", service)
    await room._set_heaters(True, True, 21.3)
    assert service.await_args.args[2]["temperature"] == 70
    calls = service.await_count
    await room._set_heaters(True, True, 21.3)
    assert service.await_count == calls


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "unavailable"])
async def test_bad_sensor_readings_are_not_control_temperatures(hass, value):
    room = make_room(hass)
    hass.states.async_set("sensor.room", value)
    assert room._compute_cur_temp() is None


async def test_removed_room_cannot_control_replacement(hass):
    old = make_room(hass)
    old._async_tick_impl = AsyncMock()
    hass.data[DOMAIN]["climate_entities_by_entry"][old._entry.entry_id] = object()
    await old._async_tick(None)
    old._async_tick_impl.assert_not_awaited()


async def test_adjacent_identical_blocks_end_manual_override(hass, monkeypatch):
    from custom_components.vesta import climate
    room = make_room(hass, {"manual_override_mode": "next_schedule"}, data={"schedule_source": "vesta", "vesta_schedule_id": "s"})
    store = ScheduleStore(hass)
    store._data = {"s": {"name": "Schedule", "blocks": [
        {"days": [0], "start": "06:00", "end": "08:00", "mode": "comfort"},
        {"days": [0], "start": "08:00", "end": "10:00", "mode": "comfort"},
    ]}}
    hass.data[DOMAIN]["schedule_store"] = store
    room._set_heaters = AsyncMock()
    monkeypatch.setattr(climate.dt_util, "now", lambda: datetime(2026, 9, 21, 7, 0))
    await room.async_set_temperature(temperature=25)
    monkeypatch.setattr(climate.dt_util, "now", lambda: datetime(2026, 9, 21, 8, 0))
    await room._async_tick(None)
    assert room.preset_mode == "smart_schedule"
    assert room.target_temperature == 21


async def test_weather_unavailable_does_not_reuse_stale_attributes(hass):
    room = make_room(hass, {"weather_entity": "weather.home"})
    hass.states.async_set("weather.home", "unavailable", {"temperature": -30})
    await room._update_state()
    assert room._outdoor_temp is None


async def test_unavailable_global_toggles_use_legacy_static_values(hass):
    room = make_room(hass, {
        "vacation_entity": "input_boolean.vacation", "vacation_state": "off",
        "heating_season_entity": "input_boolean.season", "heating_season_active": "off",
    })
    hass.states.async_set("input_boolean.vacation", "unavailable")
    hass.states.async_set("input_boolean.season", "unknown")
    await room._update_state()
    assert not room._vacation_active
    assert not room._heating_season_active


async def test_preheat_survives_unrelated_ticks(hass):
    room = make_room(hass)
    room._preset_mode = "away"
    room._last_nearest_distance = 10000
    room._nearest_distance = 9000
    room._update_force_return()
    assert room._force_return
    room._update_force_return()
    assert room._force_return
    room._nearest_distance = 11000
    room._update_force_return()
    assert not room._force_return


async def test_inactive_ha_schedule_ignores_stale_block_data(hass):
    room = make_room(hass, {"schedule_entity": "schedule.house"})
    hass.states.async_set("schedule.house", "off", {"temp": 30, "mode": "off"})
    await room._update_state()
    assert room.target_temperature == room.eco_temp
    assert room.hvac_mode == HVACMode.HEAT


async def test_manual_override_survives_midnight_between_native_blocks(hass, monkeypatch):
    from custom_components.vesta import climate
    room = make_room(hass, {"manual_override_mode": "next_schedule"}, data={
        "schedule_source": "vesta", "vesta_schedule_id": "s",
    })
    store = ScheduleStore(hass)
    store._data = {"s": {"name": "Schedule", "blocks": [
        {"days": [1], "start": "06:00", "end": "08:00", "mode": "comfort"},
    ]}}
    hass.data[DOMAIN]["schedule_store"] = store
    room._set_heaters = AsyncMock()
    monkeypatch.setattr(climate.dt_util, "now", lambda: datetime(2026, 9, 21, 23, 59))
    await room.async_set_temperature(temperature=25)
    monkeypatch.setattr(climate.dt_util, "now", lambda: datetime(2026, 9, 22, 0, 0))
    await room._async_tick(None)
    assert room.preset_mode == "manual"
    monkeypatch.setattr(climate.dt_util, "now", lambda: datetime(2026, 9, 22, 6, 0))
    await room._async_tick(None)
    assert room.preset_mode == "smart_schedule"


async def test_ha_adjacent_blocks_and_attribute_order(hass):
    room = make_room(hass, {"manual_override_mode": "next_schedule", "schedule_entity": "schedule.house"})
    room._set_heaters = AsyncMock()
    hass.states.async_set("schedule.house", "on", {"next_event": "08:00", "temp": 21, "mode": "comfort"})
    await room.async_set_temperature(temperature=25)
    hass.states.async_set("schedule.house", "on", {"mode": "comfort", "temp": 21, "next_event": "08:00"})
    await room._async_tick(None)
    assert room.preset_mode == "manual"
    hass.states.async_set("schedule.house", "on", {"mode": "comfort", "temp": 21, "next_event": "10:00"})
    await room._async_tick(None)
    assert room.preset_mode == "smart_schedule"


async def test_next_schedule_on_skips_explicit_off_blocks(hass):
    room = make_room(hass, {"manual_override_mode": "next_schedule_on", "schedule_entity": "schedule.house"})
    room._set_heaters = AsyncMock()
    hass.states.async_set("schedule.house", "off", {"next_event": "08:00"})
    await room.async_set_temperature(temperature=25)
    hass.states.async_set("schedule.house", "on", {"next_event": "10:00", "mode": False})
    await room._async_tick(None)
    assert room.preset_mode == "manual"
    hass.states.async_set("schedule.house", "on", {"next_event": "12:00", "mode": "comfort"})
    await room._async_tick(None)
    assert room.preset_mode == "smart_schedule"


async def test_legacy_override_snapshot_does_not_revert_just_after_upgrade(hass):
    room = make_room(hass, {"manual_override_mode": "next_schedule", "schedule_entity": "schedule.house"})
    room._set_heaters = AsyncMock()
    room._preset_mode = "manual"
    room._target_temp = 25
    room._schedule_state_at_override = "on"
    hass.states.async_set("schedule.house", "on", {"next_event": "08:00"})
    await room._async_tick(None)
    assert room.preset_mode == "manual"
    hass.states.async_set("schedule.house", "off", {"next_event": "10:00"})
    await room._async_tick(None)
    assert room.preset_mode == "smart_schedule"
