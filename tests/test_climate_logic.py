"""Tests for SmartClimatePro pure logic methods.

These tests use lightweight SimpleNamespace stubs so no real HA instance is
needed.  Each test exercises a single method in isolation by calling it as an
unbound function: SmartClimatePro.<method>(stub, ...).
"""
import types
import pytest

from homeassistant.components.climate import HVACMode

from custom_components.vesta.climate import SmartClimatePro, ANTI_FROST_TEMP
from custom_components.vesta.const import (
    MODE_MANUAL,
    MODE_AWAY,
    MODE_VACATION,
    MODE_SMART_SCHEDULE,
    CONF_COMFORT_TEMP,
    CONF_ECO_TEMP,
    CONF_AWAY_TEMP,
    CONF_OVERRIDE_COMFORT,
    CONF_OVERRIDE_ECO,
    CONF_OVERRIDE_AWAY,
)


# ---------------------------------------------------------------------------
# Stub builders
# ---------------------------------------------------------------------------

def _entity(
    vacation_active: bool = False,
    preset_mode: str = MODE_SMART_SCHEDULE,
    force_return: bool = False,
    target_temp: float | None = 21.0,
    outdoor_temp: float | None = None,
    comfort_temp: float = 21.0,
    eco_temp: float = 18.0,
    away_temp: float = 15.0,
    hvac_mode: HVACMode = HVACMode.HEAT,
) -> types.SimpleNamespace:
    """Minimal stub for _compute_effective_target / _apply_vesta_schedule_mode."""
    return types.SimpleNamespace(
        _vacation_active=vacation_active,
        _preset_mode=preset_mode,
        _force_return=force_return,
        _target_temp=target_temp,
        _outdoor_temp=outdoor_temp,
        comfort_temp=comfort_temp,
        eco_temp=eco_temp,
        away_temp=away_temp,
        _hvac_mode=hvac_mode,
    )


def _entity_with_entry(entry_data: dict, global_value=None) -> types.SimpleNamespace:
    """Stub for comfort_temp / eco_temp / away_temp property tests."""
    e = types.SimpleNamespace()
    e._entry = types.SimpleNamespace(data=entry_data)
    e._get_global = lambda key, default: global_value if global_value is not None else default
    return e


# ---------------------------------------------------------------------------
# _compute_effective_target
# ---------------------------------------------------------------------------

class TestComputeEffectiveTarget:
    def test_vacation_active_returns_frost(self):
        e = _entity(vacation_active=True, target_temp=22.0)
        assert SmartClimatePro._compute_effective_target(e) == ANTI_FROST_TEMP

    def test_vacation_preset_returns_frost(self):
        e = _entity(preset_mode=MODE_VACATION)
        assert SmartClimatePro._compute_effective_target(e) == ANTI_FROST_TEMP

    def test_vacation_flag_beats_force_return(self):
        e = _entity(vacation_active=True, force_return=True, comfort_temp=22.0)
        assert SmartClimatePro._compute_effective_target(e) == ANTI_FROST_TEMP

    def test_force_return_returns_comfort_temp(self):
        e = _entity(preset_mode=MODE_AWAY, force_return=True, comfort_temp=22.0)
        assert SmartClimatePro._compute_effective_target(e) == 22.0

    def test_manual_mode_returns_target_temp(self):
        e = _entity(preset_mode=MODE_MANUAL, target_temp=23.5)
        assert SmartClimatePro._compute_effective_target(e) == 23.5

    def test_manual_mode_none_target_falls_back_to_comfort(self):
        e = _entity(preset_mode=MODE_MANUAL, target_temp=None, comfort_temp=21.0)
        assert SmartClimatePro._compute_effective_target(e) == 21.0

    def test_away_mode_returns_away_temp(self):
        e = _entity(preset_mode=MODE_AWAY, away_temp=15.0)
        assert SmartClimatePro._compute_effective_target(e) == 15.0

    def test_normal_mode_returns_target_temp(self):
        e = _entity(preset_mode=MODE_SMART_SCHEDULE, target_temp=21.5)
        assert SmartClimatePro._compute_effective_target(e) == pytest.approx(21.5)

    def test_weather_compensation_below_5c(self):
        # outdoor = 0 → boost = (5 - 0) * 0.1 = +0.5
        e = _entity(target_temp=21.0, outdoor_temp=0.0)
        assert SmartClimatePro._compute_effective_target(e) == pytest.approx(21.5)

    def test_weather_compensation_at_minus_5c(self):
        # outdoor = -5 → boost = (5 - (-5)) * 0.1 = +1.0
        e = _entity(target_temp=21.0, outdoor_temp=-5.0)
        assert SmartClimatePro._compute_effective_target(e) == pytest.approx(22.0)

    def test_no_weather_compensation_at_threshold(self):
        e = _entity(target_temp=21.0, outdoor_temp=5.0)
        assert SmartClimatePro._compute_effective_target(e) == pytest.approx(21.0)

    def test_no_weather_compensation_above_threshold(self):
        e = _entity(target_temp=21.0, outdoor_temp=15.0)
        assert SmartClimatePro._compute_effective_target(e) == pytest.approx(21.0)

    def test_no_weather_compensation_when_outdoor_temp_unknown(self):
        e = _entity(target_temp=21.0, outdoor_temp=None)
        assert SmartClimatePro._compute_effective_target(e) == pytest.approx(21.0)

    def test_away_mode_weather_compensation_not_applied(self):
        # Away mode returns away_temp directly, bypassing weather boost
        e = _entity(preset_mode=MODE_AWAY, away_temp=15.0, outdoor_temp=0.0)
        assert SmartClimatePro._compute_effective_target(e) == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# _apply_vesta_schedule_mode
# ---------------------------------------------------------------------------

class TestApplyVestaScheduleMode:
    def test_off_sets_hvac_off(self):
        e = _entity(hvac_mode=HVACMode.HEAT)
        SmartClimatePro._apply_vesta_schedule_mode(e, "off")
        assert e._hvac_mode == HVACMode.OFF

    def test_off_does_not_change_target_temp(self):
        e = _entity(hvac_mode=HVACMode.HEAT, target_temp=22.0)
        SmartClimatePro._apply_vesta_schedule_mode(e, "off")
        assert e._target_temp == 22.0

    def test_comfort_sets_comfort_temp(self):
        e = _entity(comfort_temp=22.0)
        SmartClimatePro._apply_vesta_schedule_mode(e, "comfort")
        assert e._target_temp == 22.0

    def test_eco_sets_eco_temp(self):
        e = _entity(eco_temp=18.5)
        SmartClimatePro._apply_vesta_schedule_mode(e, "eco")
        assert e._target_temp == 18.5

    def test_away_sets_away_temp(self):
        e = _entity(away_temp=14.0)
        SmartClimatePro._apply_vesta_schedule_mode(e, "away")
        assert e._target_temp == 14.0

    def test_frost_sets_anti_frost_temp(self):
        e = _entity()
        SmartClimatePro._apply_vesta_schedule_mode(e, "frost")
        assert e._target_temp == ANTI_FROST_TEMP

    def test_custom_temp(self):
        e = _entity()
        SmartClimatePro._apply_vesta_schedule_mode(e, "temp:23.5")
        assert e._target_temp == pytest.approx(23.5)

    def test_custom_temp_integer(self):
        e = _entity()
        SmartClimatePro._apply_vesta_schedule_mode(e, "temp:20")
        assert e._target_temp == pytest.approx(20.0)

    def test_custom_temp_invalid_falls_back_to_comfort(self):
        e = _entity(comfort_temp=21.0)
        SmartClimatePro._apply_vesta_schedule_mode(e, "temp:abc")
        assert e._target_temp == 21.0

    def test_unknown_mode_falls_back_to_eco(self):
        e = _entity(eco_temp=18.0)
        SmartClimatePro._apply_vesta_schedule_mode(e, "unknown_mode")
        assert e._target_temp == 18.0

    def test_active_mode_re_enables_heat_when_was_off(self):
        e = _entity(hvac_mode=HVACMode.OFF)
        SmartClimatePro._apply_vesta_schedule_mode(e, "comfort")
        assert e._hvac_mode == HVACMode.HEAT

    def test_active_mode_keeps_heat_when_already_on(self):
        e = _entity(hvac_mode=HVACMode.HEAT)
        SmartClimatePro._apply_vesta_schedule_mode(e, "eco")
        assert e._hvac_mode == HVACMode.HEAT


# ---------------------------------------------------------------------------
# comfort_temp / eco_temp / away_temp properties
# ---------------------------------------------------------------------------

class TestComfortTemp:
    def test_override_enabled_reads_room_config(self):
        e = _entity_with_entry({CONF_OVERRIDE_COMFORT: True, CONF_COMFORT_TEMP: 22.0})
        assert SmartClimatePro.comfort_temp.fget(e) == pytest.approx(22.0)

    def test_override_disabled_reads_global(self):
        e = _entity_with_entry({CONF_OVERRIDE_COMFORT: False}, global_value=21.5)
        assert SmartClimatePro.comfort_temp.fget(e) == pytest.approx(21.5)

    def test_no_override_key_reads_global(self):
        e = _entity_with_entry({}, global_value=20.0)
        assert SmartClimatePro.comfort_temp.fget(e) == pytest.approx(20.0)

    def test_default_when_global_missing(self):
        e = _entity_with_entry({}, global_value=None)
        assert SmartClimatePro.comfort_temp.fget(e) == pytest.approx(21.0)

    def test_override_missing_temp_uses_default(self):
        # Override flag set but CONF_COMFORT_TEMP not in entry data → default 21.0
        e = _entity_with_entry({CONF_OVERRIDE_COMFORT: True})
        assert SmartClimatePro.comfort_temp.fget(e) == pytest.approx(21.0)


class TestEcoTemp:
    def test_override_enabled_reads_room_config(self):
        e = _entity_with_entry({CONF_OVERRIDE_ECO: True, CONF_ECO_TEMP: 17.0})
        assert SmartClimatePro.eco_temp.fget(e) == pytest.approx(17.0)

    def test_override_disabled_reads_global(self):
        e = _entity_with_entry({CONF_OVERRIDE_ECO: False}, global_value=18.5)
        assert SmartClimatePro.eco_temp.fget(e) == pytest.approx(18.5)

    def test_default_when_global_missing(self):
        e = _entity_with_entry({}, global_value=None)
        assert SmartClimatePro.eco_temp.fget(e) == pytest.approx(18.0)


class TestHvacAction:
    """hvac_action must not report HEATING during off-season OFF mode."""

    def test_frost_risk_always_heating(self):
        from homeassistant.components.climate import HVACAction
        e = types.SimpleNamespace(
            _hvac_mode=HVACMode.HEAT,
            _cur_temp=4.0,  # below ANTI_FROST_TEMP (5.0)
            _heating_season_active=False,
            _window_open=False,
        )
        e._compute_effective_target = lambda: 21.0
        assert SmartClimatePro.hvac_action.fget(e) == HVACAction.HEATING

    def test_off_season_no_frost_returns_idle(self):
        from homeassistant.components.climate import HVACAction
        e = types.SimpleNamespace(
            _hvac_mode=HVACMode.HEAT,
            _cur_temp=15.0,
            _heating_season_active=False,
            _emergency_heat_active=False,
            _vacation_active=False,
            _preset_mode=None,
            _window_open=False,
        )
        e._get_global = lambda key, default: default
        e._compute_effective_target = lambda: 21.0
        assert SmartClimatePro.hvac_action.fget(e) == HVACAction.IDLE

    def test_hvac_off_returns_off(self):
        from homeassistant.components.climate import HVACAction
        e = types.SimpleNamespace(
            _hvac_mode=HVACMode.OFF,
            _cur_temp=15.0,
            _heating_season_active=True,
            _window_open=False,
        )
        e._compute_effective_target = lambda: 21.0
        assert SmartClimatePro.hvac_action.fget(e) == HVACAction.OFF

    def test_window_open_returns_idle(self):
        from homeassistant.components.climate import HVACAction
        e = types.SimpleNamespace(
            _hvac_mode=HVACMode.HEAT,
            _cur_temp=18.0,
            _heating_season_active=True,
            _emergency_heat_active=False,
            _window_open=True,
        )
        e._compute_effective_target = lambda: 21.0
        assert SmartClimatePro.hvac_action.fget(e) == HVACAction.IDLE

    def test_below_target_returns_heating(self):
        from homeassistant.components.climate import HVACAction
        e = types.SimpleNamespace(
            _hvac_mode=HVACMode.HEAT,
            _cur_temp=18.0,
            _heating_season_active=True,
            _emergency_heat_active=False,
            _window_open=False,
        )
        e._compute_effective_target = lambda: 21.0
        assert SmartClimatePro.hvac_action.fget(e) == HVACAction.HEATING


class TestAwayTemp:
    def test_override_enabled_reads_room_config(self):
        e = _entity_with_entry({CONF_OVERRIDE_AWAY: True, CONF_AWAY_TEMP: 14.0})
        assert SmartClimatePro.away_temp.fget(e) == pytest.approx(14.0)

    def test_override_disabled_reads_global(self):
        e = _entity_with_entry({CONF_OVERRIDE_AWAY: False}, global_value=15.5)
        assert SmartClimatePro.away_temp.fget(e) == pytest.approx(15.5)

    def test_default_when_global_missing(self):
        e = _entity_with_entry({}, global_value=None)
        assert SmartClimatePro.away_temp.fget(e) == pytest.approx(15.0)
