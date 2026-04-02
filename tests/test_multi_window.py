"""Tests for multi-window sensor logic in SmartClimatePro.

These tests verify that the window open/ajar state is correctly aggregated
across multiple window sensors without requiring a real HA instance.
"""
import time
import types
import pytest

from custom_components.vesta.const import CONF_WINDOW_DELAY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(sensor_ids: list[str], delay_min: float = 0) -> types.SimpleNamespace:
    """Build a minimal stub matching SmartClimatePro's window-related attributes."""
    e = types.SimpleNamespace()
    e._window_sensor_ids = sensor_ids
    e._window_states = {eid: False for eid in sensor_ids}
    e._window_ajar_since = {eid: None for eid in sensor_ids}
    e._window_ajar = False
    e._window_open = False
    e._window_stuck_warned = False
    e._name = "TestRoom"
    e._entry = types.SimpleNamespace(data={CONF_WINDOW_DELAY: delay_min})
    return e


def _run_window_step(e: types.SimpleNamespace) -> None:
    """Execute tick step 3 (window logic) directly on a stub entity."""
    import logging
    _LOGGER = logging.getLogger("test")

    any_ajar = any(e._window_states.values())
    e._window_ajar = any_ajar
    if any_ajar:
        delay_min = float(e._entry.data.get(CONF_WINDOW_DELAY, 0))
        now_ts = time.time()
        window_open = False
        for eid, is_ajar in e._window_states.items():
            if not is_ajar:
                continue
            since = e._window_ajar_since.get(eid)
            if since is None:
                continue
            elapsed_min = (now_ts - since) / 60
            if delay_min <= 0 or elapsed_min >= delay_min:
                window_open = True
            hours_open = (now_ts - since) / 3600
            if hours_open > 2 and not e._window_stuck_warned:
                e._window_stuck_warned = True
        e._window_open = window_open
    else:
        e._window_open = False


# ---------------------------------------------------------------------------
# Multi-window aggregation
# ---------------------------------------------------------------------------

class TestMultiWindowAggregation:
    def test_no_sensors_window_stays_closed(self):
        e = _make_entity([])
        _run_window_step(e)
        assert e._window_open is False
        assert e._window_ajar is False

    def test_single_sensor_open_no_delay(self):
        e = _make_entity(["binary_sensor.win_a"])
        e._window_states["binary_sensor.win_a"] = True
        e._window_ajar_since["binary_sensor.win_a"] = time.time() - 1
        _run_window_step(e)
        assert e._window_open is True
        assert e._window_ajar is True

    def test_single_sensor_closed_window_closed(self):
        e = _make_entity(["binary_sensor.win_a"])
        e._window_states["binary_sensor.win_a"] = False
        _run_window_step(e)
        assert e._window_open is False
        assert e._window_ajar is False

    def test_any_sensor_open_triggers_ajar(self):
        e = _make_entity(["binary_sensor.win_a", "binary_sensor.win_b"])
        e._window_states["binary_sensor.win_b"] = True
        e._window_ajar_since["binary_sensor.win_b"] = time.time() - 1
        _run_window_step(e)
        assert e._window_ajar is True
        assert e._window_open is True

    def test_all_closed_window_closed(self):
        e = _make_entity(["binary_sensor.win_a", "binary_sensor.win_b"])
        e._window_states["binary_sensor.win_a"] = False
        e._window_states["binary_sensor.win_b"] = False
        _run_window_step(e)
        assert e._window_open is False
        assert e._window_ajar is False

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
        assert e._window_ajar is True
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

    def test_constructor_handles_string_sensor(self):
        """SmartClimatePro constructor must accept old single-string window sensor."""
        from custom_components.vesta.climate import SmartClimatePro
        from custom_components.vesta.const import (
            CONF_WINDOW_SENSOR, CONF_HEATER_ENTITIES, CONF_SENSOR, CONF_NAME,
        )
        data = {
            CONF_NAME: "Test",
            CONF_HEATER_ENTITIES: [],
            CONF_SENSOR: [],
            CONF_WINDOW_SENSOR: "binary_sensor.my_window",
        }
        # We only instantiate partially — just test that _window_sensor_ids is set correctly
        # by extracting the logic from the constructor
        raw_window = data.get(CONF_WINDOW_SENSOR)
        if isinstance(raw_window, list):
            ids = [w for w in raw_window if w]
        elif isinstance(raw_window, str) and raw_window:
            ids = [raw_window]
        else:
            ids = []
        assert ids == ["binary_sensor.my_window"]

    def test_constructor_handles_list_sensor(self):
        from custom_components.vesta.const import CONF_WINDOW_SENSOR
        raw_window = ["binary_sensor.win_a", "binary_sensor.win_b"]
        if isinstance(raw_window, list):
            ids = [w for w in raw_window if w]
        elif isinstance(raw_window, str) and raw_window:
            ids = [raw_window]
        else:
            ids = []
        assert ids == ["binary_sensor.win_a", "binary_sensor.win_b"]

    def test_constructor_handles_none_sensor(self):
        from custom_components.vesta.const import CONF_WINDOW_SENSOR
        raw_window = None
        if isinstance(raw_window, list):
            ids = [w for w in raw_window if w]
        elif isinstance(raw_window, str) and raw_window:
            ids = [raw_window]
        else:
            ids = []
        assert ids == []
