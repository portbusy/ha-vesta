"""Focused runtime-path tests for tick serialization and safety behavior."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from .runtime_helpers import make_room

from custom_components.vesta import climate as climate_module
from custom_components.vesta.climate import SmartClimatePro
from custom_components.vesta.const import DOMAIN


@pytest.mark.asyncio
async def test_tick_processes_event_arriving_during_pending_rerun():
    entity = SimpleNamespace(
        _entry=SimpleNamespace(entry_id="room-1"),
        _tick_running=False,
        _tick_pending=False,
        hass=SimpleNamespace(
            data={DOMAIN: {"climate_entities_by_entry": {"room-1": object()}}}
        ),
    )
    entity.hass.data[DOMAIN]["climate_entities_by_entry"]["room-1"] = entity
    calls = []

    async def tick_impl(now):
        calls.append(now)
        if len(calls) < 3:
            entity._tick_pending = True

    entity._async_tick_impl = tick_impl

    await SmartClimatePro._async_tick(entity, datetime(2026, 1, 1))

    assert calls == [datetime(2026, 1, 1), None, None]
    assert entity._tick_running is False
    assert entity._tick_pending is False


@pytest.mark.asyncio
async def test_sensor_failure_updates_state_sensors_and_boiler(monkeypatch, hass):
    monkeypatch.setattr(climate_module.dt_util, "now", lambda: datetime(2026, 1, 1, 12, 10))
    entity = make_room(hass)
    hass.states.async_set("sensor.room", "unavailable")
    companion = SimpleNamespace(async_write_ha_state=Mock())
    coordinator = SimpleNamespace(async_update=AsyncMock())
    entity._companion_sensors = [companion]
    entity._set_heaters = AsyncMock()
    hass.data[DOMAIN]["boiler_coordinator"] = coordinator
    await entity._async_tick_impl(datetime(2026, 1, 1, 12, 10))
    assert entity._failsafe_heating_active is True
    assert entity._daily_usage_seconds == 60
    assert entity._monthly_actual_heating_s == 60
    entity.async_write_ha_state.assert_called_once()
    companion.async_write_ha_state.assert_called_once()
    coordinator.async_update.assert_awaited_once_with([entity])


@pytest.mark.asyncio
async def test_final_heater_boundary_clamps_unsafe_target():
    services = SimpleNamespace(async_call=AsyncMock())
    entity = SimpleNamespace(
        hass=SimpleNamespace(services=services, states=SimpleNamespace(get=lambda _: None)),
        _name="Test room",
        _removed=False,
        _heaters=["climate.trv"],
        _heater_states={"climate.trv": True},
        _heater_targets={"climate.trv": 20.0},
        _last_heater_cmd_time=0.0,
        comfort_temp=21.0,
    )

    await SmartClimatePro._set_heaters(
        entity, switch_on=True, climate_active=True, target_temp=1000.0
    )

    services.async_call.assert_awaited_once_with(
        "climate",
        "set_temperature",
        {"entity_id": "climate.trv", "temperature": 35.0}, blocking=True,
    )
