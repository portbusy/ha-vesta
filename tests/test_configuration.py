"""Configuration edits, schedule assignment and lifecycle regressions."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vesta import _async_global_options_updated, async_migrate_entry
from custom_components.vesta import api
from custom_components.vesta.config_flow import SmartClimateProOptionsFlow, _validate_room_entities
from custom_components.vesta.const import DOMAIN, ATTR_SAVINGS_KWH_MONTH, ATTR_SAVINGS_EUR_MONTH
from custom_components.vesta.store import ScheduleStore
from .runtime_helpers import make_room


async def test_options_can_clear_optional_global_entities(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={
        "entry_type": "global", "weather_entity": "weather.old",
        "boiler_entity": "switch.old", "schedule_entity": "schedule.old",
        "schedule_source": "vesta", "vesta_schedule_id": "native",
        "energy_annual_data": {"2026": 1200},
    })
    entry.add_to_hass(hass)
    flow = SmartClimateProOptionsFlow()
    flow.hass = hass
    flow.handler = entry.entry_id
    await flow.async_step_global({"comfort_temp": 22})
    assert "weather_entity" not in entry.data
    assert "boiler_entity" not in entry.data
    assert "schedule_entity" not in entry.data
    assert entry.data["vesta_schedule_id"] == "native"
    assert entry.data["energy_annual_data"] == {"2026": 1200}


@pytest.mark.parametrize("source", ["inherit", "vesta"])
async def test_panel_assignment_replaces_old_entity_override(hass, source):
    room = make_room(hass, {"schedule_source": "vesta", "vesta_schedule_id": "global"}, data={
        "override_schedule": True, "schedule_entity": "schedule.old",
    })
    store = ScheduleStore(hass)
    store._data = {"new": {"name": "New", "blocks": []}}
    hass.data[DOMAIN]["schedule_store"] = store
    connection = SimpleNamespace(send_result=Mock(), send_error=Mock())
    await api.ws_assign_room.__wrapped__.__wrapped__(hass, connection, {
        "id": 1, "entry_id": room._entry.entry_id,
        "schedule_source": source, "vesta_schedule_id": "new",
    })
    connection.send_error.assert_not_called()
    assert room._resolve_schedule_source() == ("vesta", "global" if source == "inherit" else "new")


async def test_vesta_entities_cannot_be_used_as_inputs(hass, entity_registry):
    entity = entity_registry.async_get_or_create("climate", DOMAIN, "room")
    errors = {}
    _validate_room_entities(hass, {"heaters": [entity.entity_id]}, errors)
    assert errors == {"base": "circular_entity"}


async def test_two_rooms_cannot_command_the_same_heater(hass):
    make_room(hass)
    errors = {}
    _validate_room_entities(hass, {"heaters": ["climate.trv"]}, errors)
    assert errors == {"base": "heaters_in_use"}


async def test_global_options_retire_old_boiler_and_tick_rooms(hass):
    room = make_room(hass)
    room._setup_listeners = Mock()
    room._async_tick = AsyncMock()
    old = SimpleNamespace(_boiler_id="switch.old", async_shutdown=AsyncMock())
    hass.data[DOMAIN]["boiler_coordinator"] = old
    await _async_global_options_updated(hass, SimpleNamespace(data={}))
    old.async_shutdown.assert_awaited_once()
    room._setup_listeners.assert_called_once()
    room._async_tick.assert_awaited_once_with(None)


async def test_future_config_version_is_not_downgraded(hass):
    entry = MockConfigEntry(domain=DOMAIN, version=100, data={"future": True})
    entry.add_to_hass(hass)
    assert not await async_migrate_entry(hass, entry)
    assert entry.version == 100
    assert entry.data == {"future": True}


@pytest.mark.parametrize("override", [False, True])
async def test_migration_preserves_legacy_schedule_inheritance(hass, override):
    entry = MockConfigEntry(domain=DOMAIN, version=7, data={
        "entry_type": "room", "schedule_source": "entity",
        "override_schedule": override, "schedule_entity": "schedule.room",
    })
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)
    assert entry.version == 8
    assert entry.data.get("schedule_source") == ("entity" if override else None)
    assert entry.data["schedule_entity"] == "schedule.room"


async def test_restore_preserves_counters_and_explicit_off(hass):
    room = make_room(hass)
    room._daily_away_s = 123
    room._daily_window_s = 456
    room._daily_eco_s = 789
    room._daily_usage_seconds = 135
    room._user_hvac_off = True
    old = State("climate.vesta_test", "off", room.extra_state_attributes)
    restored = make_room(hass)
    restored._restore_state(old)
    assert restored._daily_away_s == 123
    assert restored._daily_window_s == 456
    assert restored._daily_eco_s == 789
    assert restored._daily_usage_seconds == 135
    assert restored._user_hvac_off


async def test_restore_ignores_non_finite_counters(hass):
    room = make_room(hass)
    room._restore_state(State("climate.vesta_test", "off", {
        "_monthly_actual_heating_s": "nan", "_monthly_hdh_base": None,
        "_daily_usage_seconds": "inf", "_last_savings_reset_month": "invalid",
    }))
    assert room._monthly_actual_heating_s == 0
    assert room._monthly_hdh_base == 0
    assert room._daily_usage_seconds == 0


async def test_savings_accept_zero_tariff_and_reject_non_finite_values(hass):
    room = make_room(hass, {
        "energy_price_kwh": 0,
        "energy_annual_data": {str(dt_util.now().year): 1200},
    })
    room._monthly_hdh_base = 10
    room._monthly_hdh_eco = 5
    estimate = room._compute_savings_est()
    assert estimate[ATTR_SAVINGS_KWH_MONTH] == 50
    assert estimate[ATTR_SAVINGS_EUR_MONTH] == 0
    hass.data[DOMAIN]["global"].data["energy_price_kwh"] = "nan"
    assert room._compute_savings_est() == {}
