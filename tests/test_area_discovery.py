"""Exercise room discovery against Home Assistant's real registries."""

import pytest
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vesta.config_flow import _discover_entities_for_area


@pytest.mark.asyncio
@pytest.mark.parametrize("child_device", [False, True], ids=["device", "child"])
@pytest.mark.parametrize("entity_area", [None, "same", "other"])
async def test_discovery_respects_effective_area(
    hass, area_registry, device_registry, entity_registry, child_device, entity_area
):
    """Inherit device/parent areas, but let an explicit entity area override them."""
    if child_device and not hasattr(dr.DeviceRegistry, "async_get_or_create_child"):
        pytest.skip("Child devices were introduced in Home Assistant 2026.9")

    room = area_registry.async_create("Living room")
    other = area_registry.async_create("Bedroom")
    config_entry = MockConfigEntry(domain="test")
    config_entry.add_to_hass(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={("test", "parent")},
    )
    device_registry.async_update_device(device.id, area_id=room.id)
    if child_device:
        device = device_registry.async_get_or_create_child(
            config_entry_id=config_entry.entry_id,
            identifiers={("test", "child")},
            parent_device_id=device.id,
        )

    expected = {"heater_ids": [], "temp_ids": [], "window_ids": []}
    for domain, device_class, key in (
        ("climate", None, "heater_ids"),
        ("sensor", "temperature", "temp_ids"),
        ("binary_sensor", "window", "window_ids"),
    ):
        entity = entity_registry.async_get_or_create(
            domain, "test", domain,
            config_entry=config_entry,
            device_id=device.id,
            original_device_class=device_class,
        )
        if entity_area is not None:
            entity_registry.async_update_entity(
                entity.entity_id,
                area_id=room.id if entity_area == "same" else other.id,
            )
        expected[key].append(entity.entity_id)

    result = _discover_entities_for_area(hass, room.id)
    other_result = _discover_entities_for_area(hass, other.id)
    for key, entity_ids in expected.items():
        assert result[key] == ([] if entity_area == "other" else entity_ids)
        assert other_result[key] == (entity_ids if entity_area == "other" else [])


@pytest.mark.asyncio
async def test_child_area_overrides_parent(
    hass, area_registry, device_registry, entity_registry
):
    """A child's own area takes precedence over the parent's area."""
    if not hasattr(dr.DeviceRegistry, "async_get_or_create_child"):
        pytest.skip("Child devices were introduced in Home Assistant 2026.9")

    parent_area = area_registry.async_create("Parent room")
    child_area = area_registry.async_create("Child room")
    config_entry = MockConfigEntry(domain="test")
    config_entry.add_to_hass(hass)
    parent = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={("test", "parent")}
    )
    device_registry.async_update_device(parent.id, area_id=parent_area.id)
    child = device_registry.async_get_or_create_child(
        config_entry_id=config_entry.entry_id,
        identifiers={("test", "child")},
        parent_device_id=parent.id,
    )
    device_registry.async_update_child_device(child.id, area_id=child_area.id)
    entity = entity_registry.async_get_or_create(
        "climate", "test", "heater", config_entry=config_entry, device_id=child.id
    )

    assert _discover_entities_for_area(hass, parent_area.id)["heater_ids"] == []
    assert _discover_entities_for_area(hass, child_area.id)["heater_ids"] == [
        entity.entity_id
    ]


@pytest.mark.asyncio
async def test_entity_only_area_and_disabled_entities(hass, area_registry, entity_registry):
    """Entities without a device are discoverable; disabled entities are excluded."""
    room = area_registry.async_create("Living room")
    entity = entity_registry.async_get_or_create("climate", "test", "heater")
    entity_registry.async_update_entity(entity.entity_id, area_id=room.id)
    assert _discover_entities_for_area(hass, room.id)["heater_ids"] == [entity.entity_id]

    entity_registry.async_update_entity(
        entity.entity_id, disabled_by=er.RegistryEntryDisabler.USER
    )
    assert _discover_entities_for_area(hass, room.id)["heater_ids"] == []
