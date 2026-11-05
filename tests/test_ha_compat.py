"""Compatibility with the Home Assistant 2026.11 climate and entity APIs."""
from homeassistant.components.climate import ClimateEntity
from homeassistant.const import UnitOfTemperature

from custom_components.vesta import climate as vesta_climate
from custom_components.vesta.climate import SmartClimatePro

_LEGACY_NAMES = ("current_temperature", "target_temperature", "_attr_temperature_unit")


def test_native_temperature_properties_are_implemented():
    assert isinstance(SmartClimatePro.__dict__["native_current_temperature"], property)
    assert isinstance(SmartClimatePro.__dict__["native_target_temperature"], property)


def test_shim_matches_installed_home_assistant():
    has_native = hasattr(ClimateEntity, "native_current_temperature")
    assert vesta_climate._HAS_NATIVE_TEMPERATURE is has_native
    if has_native:
        for name in _LEGACY_NAMES:
            assert name not in SmartClimatePro.__dict__, name
        assert object.__new__(SmartClimatePro)._attr_native_temperature_unit == UnitOfTemperature.CELSIUS
    else:
        assert object.__new__(SmartClimatePro)._attr_temperature_unit == UnitOfTemperature.CELSIUS
        assert SmartClimatePro.__dict__["current_temperature"] is SmartClimatePro.__dict__["native_current_temperature"]
        assert SmartClimatePro.__dict__["target_temperature"] is SmartClimatePro.__dict__["native_target_temperature"]
        assert "_attr_native_temperature_unit" not in SmartClimatePro.__dict__


def test_opts_in_to_in_place_entity_id_changes():
    assert callable(SmartClimatePro.__dict__.get("async_entity_id_changed"))
