"""Real Vesta entities with Home Assistant state registries for runtime tests."""
from types import SimpleNamespace
from unittest.mock import Mock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vesta.climate import SmartClimatePro
from custom_components.vesta.const import DOMAIN


def make_room(hass, global_data=None, data=None):
    entry = MockConfigEntry(domain=DOMAIN, version=7, data={
        "name": "Test room", "entry_type": "room", "heaters": ["climate.trv"],
        "target_sensor": ["sensor.room"], **(data or {}),
    })
    entry.add_to_hass(hass)
    room = SmartClimatePro(hass, entry, entry.data)
    room.entity_id = "climate.vesta_test"
    room.async_write_ha_state = Mock()
    hass.data[DOMAIN] = {
        "global": SimpleNamespace(data=global_data or {}), "rooms": [room],
        "climate_entities_by_entry": {entry.entry_id: room},
        "schedule_store": None, "boiler_coordinator": None,
    }
    hass.states.async_set("sensor.room", "18", {"unit_of_measurement": "°C"})
    room._cur_temp = 18.0
    return room
