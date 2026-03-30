"""Tests for ScheduleStore pure logic (no HA instance required)."""
import pytest

from custom_components.vesta.store import ScheduleStore, _time_to_minutes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(schedule_id: str | None = None, blocks: list | None = None) -> ScheduleStore:
    """Build a ScheduleStore with pre-populated in-memory data (no HA/IO)."""
    store = ScheduleStore.__new__(ScheduleStore)
    store._data = {}
    if schedule_id is not None:
        store._data[schedule_id] = {"name": "Test", "blocks": blocks or []}
    return store


# ---------------------------------------------------------------------------
# _time_to_minutes
# ---------------------------------------------------------------------------

class TestTimeToMinutes:
    def test_midnight(self):
        assert _time_to_minutes("00:00") == 0

    def test_noon(self):
        assert _time_to_minutes("12:00") == 720

    def test_end_of_day(self):
        assert _time_to_minutes("23:59") == 1439

    def test_half_hour(self):
        assert _time_to_minutes("06:30") == 390

    def test_arbitrary_minutes(self):
        assert _time_to_minutes("10:45") == 645


# ---------------------------------------------------------------------------
# get_current_mode
# ---------------------------------------------------------------------------

class TestGetCurrentMode:
    def test_unknown_schedule_returns_off(self):
        store = _make_store()
        assert store.get_current_mode("nonexistent", 0, "10:00") == "off"

    def test_empty_blocks_returns_off(self):
        store = _make_store("s1", [])
        assert store.get_current_mode("s1", 0, "10:00") == "off"

    def test_active_block(self):
        store = _make_store("s1", [
            {"days": [0], "start": "06:00", "end": "09:00", "mode": "comfort"},
        ])
        assert store.get_current_mode("s1", 0, "07:00") == "comfort"

    def test_start_is_inclusive(self):
        store = _make_store("s1", [
            {"days": [0], "start": "06:00", "end": "09:00", "mode": "comfort"},
        ])
        assert store.get_current_mode("s1", 0, "06:00") == "comfort"

    def test_end_is_exclusive(self):
        store = _make_store("s1", [
            {"days": [0], "start": "06:00", "end": "09:00", "mode": "comfort"},
        ])
        assert store.get_current_mode("s1", 0, "09:00") == "off"

    def test_before_block_returns_off(self):
        store = _make_store("s1", [
            {"days": [0], "start": "06:00", "end": "09:00", "mode": "comfort"},
        ])
        assert store.get_current_mode("s1", 0, "05:59") == "off"

    def test_wrong_day_returns_off(self):
        store = _make_store("s1", [
            {"days": [0], "start": "06:00", "end": "09:00", "mode": "comfort"},
        ])
        assert store.get_current_mode("s1", 1, "07:00") == "off"

    def test_second_block_active(self):
        store = _make_store("s1", [
            {"days": [0, 1, 2, 3, 4], "start": "06:30", "end": "08:30", "mode": "comfort"},
            {"days": [0, 1, 2, 3, 4], "start": "17:30", "end": "22:30", "mode": "eco"},
        ])
        assert store.get_current_mode("s1", 0, "19:00") == "eco"

    def test_between_two_blocks_returns_off(self):
        store = _make_store("s1", [
            {"days": [0], "start": "06:00", "end": "08:00", "mode": "comfort"},
            {"days": [0], "start": "17:00", "end": "22:00", "mode": "eco"},
        ])
        assert store.get_current_mode("s1", 0, "12:00") == "off"

    def test_custom_temp_mode(self):
        store = _make_store("s1", [
            {"days": [0], "start": "08:00", "end": "22:00", "mode": "temp:23.5"},
        ])
        assert store.get_current_mode("s1", 0, "10:00") == "temp:23.5"

    def test_sunday_is_day_6(self):
        store = _make_store("s1", [
            {"days": [5, 6], "start": "08:00", "end": "23:00", "mode": "comfort"},
        ])
        assert store.get_current_mode("s1", 6, "12:00") == "comfort"
        assert store.get_current_mode("s1", 0, "12:00") == "off"

    def test_frost_mode(self):
        store = _make_store("s1", [
            {"days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "23:59", "mode": "frost"},
        ])
        assert store.get_current_mode("s1", 3, "15:00") == "frost"


# ---------------------------------------------------------------------------
# validate_blocks
# ---------------------------------------------------------------------------

class TestValidateBlocks:
    def _store(self) -> ScheduleStore:
        return _make_store()

    def test_empty_list_is_valid(self):
        assert self._store().validate_blocks([]) is None

    def test_valid_single_block(self):
        blocks = [{"days": [0], "start": "06:00", "end": "09:00", "mode": "comfort"}]
        assert self._store().validate_blocks(blocks) is None

    def test_valid_multiple_non_overlapping_blocks(self):
        blocks = [
            {"days": [0], "start": "06:00", "end": "09:00", "mode": "comfort"},
            {"days": [0], "start": "17:00", "end": "22:00", "mode": "eco"},
        ]
        assert self._store().validate_blocks(blocks) is None

    def test_not_a_list_returns_error(self):
        assert self._store().validate_blocks("not a list") is not None

    def test_missing_days_returns_error(self):
        blocks = [{"start": "06:00", "end": "09:00", "mode": "comfort"}]
        assert self._store().validate_blocks(blocks) is not None

    def test_missing_start_returns_error(self):
        blocks = [{"days": [0], "end": "09:00", "mode": "comfort"}]
        assert self._store().validate_blocks(blocks) is not None

    def test_missing_end_returns_error(self):
        blocks = [{"days": [0], "start": "06:00", "mode": "comfort"}]
        assert self._store().validate_blocks(blocks) is not None

    def test_missing_mode_returns_error(self):
        blocks = [{"days": [0], "start": "06:00", "end": "09:00"}]
        assert self._store().validate_blocks(blocks) is not None

    def test_start_equals_end_returns_error(self):
        blocks = [{"days": [0], "start": "09:00", "end": "09:00", "mode": "comfort"}]
        assert self._store().validate_blocks(blocks) is not None

    def test_start_after_end_returns_error(self):
        blocks = [{"days": [0], "start": "10:00", "end": "09:00", "mode": "comfort"}]
        assert self._store().validate_blocks(blocks) is not None

    def test_invalid_time_format_returns_error(self):
        blocks = [{"days": [0], "start": "not-a-time", "end": "09:00", "mode": "comfort"}]
        assert self._store().validate_blocks(blocks) is not None

    def test_overlap_same_day_returns_error(self):
        blocks = [
            {"days": [0], "start": "06:00", "end": "10:00", "mode": "comfort"},
            {"days": [0], "start": "09:00", "end": "12:00", "mode": "eco"},
        ]
        err = self._store().validate_blocks(blocks)
        assert err is not None
        assert "overlap" in err.lower()

    def test_overlap_on_one_of_multiple_days(self):
        blocks = [
            {"days": [0, 1], "start": "06:00", "end": "10:00", "mode": "comfort"},
            {"days": [1], "start": "09:00", "end": "12:00", "mode": "eco"},
        ]
        # day 1 has overlap; day 0 does not
        assert self._store().validate_blocks(blocks) is not None

    def test_no_overlap_different_days(self):
        blocks = [
            {"days": [0], "start": "06:00", "end": "10:00", "mode": "comfort"},
            {"days": [1], "start": "09:00", "end": "12:00", "mode": "eco"},
        ]
        assert self._store().validate_blocks(blocks) is None

    def test_adjacent_blocks_are_not_overlapping(self):
        blocks = [
            {"days": [0], "start": "06:00", "end": "09:00", "mode": "comfort"},
            {"days": [0], "start": "09:00", "end": "12:00", "mode": "eco"},
        ]
        assert self._store().validate_blocks(blocks) is None
