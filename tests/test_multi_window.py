"""Tests for multi-window sensor logic in SmartClimatePro.

These tests verify that the window open/ajar state is correctly aggregated
across multiple window sensors without requiring a real HA instance.
"""
import time
import types

from custom_components.vesta.climate import SmartClimatePro
from custom_components.vesta.const import CONF_WINDOW_DELAY
from .runtime_helpers import make_room


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(sensor_ids: list[str], delay_min: float = 0) -> types.SimpleNamespace:
    """Build a minimal stub matching SmartClimatePro's window-related attributes."""
    e = types.SimpleNamespace()
    e._window_sensor_ids = sensor_ids
    e._window_states = {eid: False for eid in sensor_ids}
    e._window_ajar_since = {eid: None for eid in sensor_ids}
    e._window_open = False
    e._window_stuck_warned = {}
    e._name = "TestRoom"
    e._entry = types.SimpleNamespace(data={CONF_WINDOW_DELAY: delay_min})
    return e


def _run_window_step(e: types.SimpleNamespace) -> None:
    """Execute the production window aggregation logic on a stub entity."""
    SmartClimatePro._update_window_state(e)


# ---------------------------------------------------------------------------
# Multi-window aggregation
# ---------------------------------------------------------------------------

class TestMultiWindowAggregation:
    def test_no_sensors_window_stays_closed(self):
        e = _make_entity([])
        _run_window_step(e)
        assert e._window_open is False

    def test_single_sensor_open_no_delay(self):
        e = _make_entity(["binary_sensor.win_a"])
        e._window_states["binary_sensor.win_a"] = True
        e._window_ajar_since["binary_sensor.win_a"] = time.time() - 1
        _run_window_step(e)
        assert e._window_open is True

    def test_single_sensor_closed_window_closed(self):
        e = _make_entity(["binary_sensor.win_a"])
        e._window_states["binary_sensor.win_a"] = False
        _run_window_step(e)
        assert e._window_open is False

    def test_any_sensor_open_triggers_ajar(self):
        e = _make_entity(["binary_sensor.win_a", "binary_sensor.win_b"])
        e._window_states["binary_sensor.win_b"] = True
        e._window_ajar_since["binary_sensor.win_b"] = time.time() - 1
        _run_window_step(e)
        assert e._window_open is True

    def test_all_closed_window_closed(self):
        e = _make_entity(["binary_sensor.win_a", "binary_sensor.win_b"])
        e._window_states["binary_sensor.win_a"] = False
        e._window_states["binary_sensor.win_b"] = False
        _run_window_step(e)
        assert e._window_open is False

    def test_second_sensor_open_while_first_is_open(self):
        """Both sensors open → still open."""
        e = _make_entity(["binary_sensor.win_a", "binary_sensor.win_b"])
        e._window_states["binary_sensor.win_a"] = True
        e._window_ajar_since["binary_sensor.win_a"] = time.time() - 5
        e._window_states["binary_sensor.win_b"] = True
        e._window_ajar_since["binary_sensor.win_b"] = time.time() - 2
        _run_window_step(e)
        assert e._window_open is True

    def test_one_open_one_closed_still_open(self):
        """One sensor open is enough to keep the window logically open."""
        e = _make_entity(["binary_sensor.win_a", "binary_sensor.win_b"])
        e._window_states["binary_sensor.win_a"] = True
        e._window_ajar_since["binary_sensor.win_a"] = time.time() - 5
        e._window_states["binary_sensor.win_b"] = False
        _run_window_step(e)
        assert e._window_open is True

    def test_three_sensors_one_open(self):
        ids = ["binary_sensor.a", "binary_sensor.b", "binary_sensor.c"]
        e = _make_entity(ids)
        e._window_states["binary_sensor.c"] = True
        e._window_ajar_since["binary_sensor.c"] = time.time() - 1
        _run_window_step(e)
        assert e._window_open is True

    # ---------------------------------------------------------------------------
    # Delay logic with multiple sensors
    # ---------------------------------------------------------------------------

    def test_delay_not_elapsed_window_not_open(self):
        e = _make_entity(["binary_sensor.win_a"], delay_min=5)
        e._window_states["binary_sensor.win_a"] = True
        e._window_ajar_since["binary_sensor.win_a"] = time.time() - 60  # 1 min < 5 min
        _run_window_step(e)
        assert e._window_open is False

    def test_delay_elapsed_window_open(self):
        e = _make_entity(["binary_sensor.win_a"], delay_min=2)
        e._window_states["binary_sensor.win_a"] = True
        e._window_ajar_since["binary_sensor.win_a"] = time.time() - 180  # 3 min > 2 min
        _run_window_step(e)
        assert e._window_open is True

    def test_second_sensor_passes_delay_first_does_not(self):
        """Window becomes open if ANY sensor passes the delay."""
        e = _make_entity(["binary_sensor.win_a", "binary_sensor.win_b"], delay_min=5)
        e._window_states["binary_sensor.win_a"] = True
        e._window_ajar_since["binary_sensor.win_a"] = time.time() - 60   # 1 min, not yet
        e._window_states["binary_sensor.win_b"] = True
        e._window_ajar_since["binary_sensor.win_b"] = time.time() - 400  # 6.6 min, yes
        _run_window_step(e)
        assert e._window_open is True

    # ---------------------------------------------------------------------------
    # Backward compat: single-string value in config
    # ---------------------------------------------------------------------------

    async def test_constructor_handles_string_sensor(self, hass):
        """SmartClimatePro constructor must accept old single-string window sensor."""
        room = make_room(hass, data={"window_sensor": "binary_sensor.my_window"})
        assert room._window_sensor_ids == ["binary_sensor.my_window"]

    async def test_constructor_handles_list_sensor(self, hass):
        sensors = ["binary_sensor.win_a", "binary_sensor.win_b"]
        room = make_room(hass, data={"window_sensor": sensors})
        assert room._window_sensor_ids == sensors

    async def test_constructor_handles_none_sensor(self, hass):
        room = make_room(hass, data={"window_sensor": None})
        assert room._window_sensor_ids == []
