"""Exercise actual HA platform setup, schedule listeners, reload and unload."""
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vesta.const import DOMAIN


async def test_room_before_global_reacts_to_schedule_and_reloads(hass, enable_custom_integrations, monkeypatch, tmp_path):
    # HA's separately shipped JS bundle is not needed for backend lifecycle
    # tests; keep HTTP, panel registration and Vesta's own assets real.
    monkeypatch.setattr("homeassistant.components.frontend._frontend_root", lambda _: tmp_path)
    hass.states.async_set("sensor.room", "18", {"unit_of_measurement": "°C"})
    hass.states.async_set("schedule.house", "on", {"temp": 23})
    room_entry = MockConfigEntry(domain=DOMAIN, version=8, data={
        "entry_type": "room", "name": "Room", "target_sensor": ["sensor.room"],
        "heaters": [],
    })
    room_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(room_entry.entry_id)
    await hass.async_block_till_done()
    room = hass.data[DOMAIN]["climate_entities_by_entry"][room_entry.entry_id]
    assert hass.states.get(room.entity_id) is not None
    assert len(room._companion_sensors) == 11

    global_entry = MockConfigEntry(domain=DOMAIN, version=8, data={
        "entry_type": "global", "schedule_entity": "schedule.house",
    })
    global_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(global_entry.entry_id)
    await hass.async_block_till_done()
    assert room.native_target_temperature == 23
    hass.states.async_set("schedule.house", "on", {"temp": 19})
    await hass.async_block_till_done()
    assert room.native_target_temperature == 19

    assert await hass.config_entries.async_reload(room_entry.entry_id)
    await hass.async_block_till_done()
    replacement = hass.data[DOMAIN]["climate_entities_by_entry"][room_entry.entry_id]
    assert replacement is not room
    assert room._removed
    assert replacement.native_target_temperature == 19
    assert len(hass.data[DOMAIN]["rooms"]) == 1
    assert await hass.config_entries.async_unload(room_entry.entry_id)
    assert not hass.data[DOMAIN]["rooms"]
    assert not hass.data[DOMAIN]["climate_entities_by_entry"]
    assert await hass.config_entries.async_unload(global_entry.entry_id)
