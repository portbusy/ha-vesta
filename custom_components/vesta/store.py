"""Persistent storage for Vesta native schedules."""
from __future__ import annotations

import asyncio
import copy
import logging
import re
import math
import uuid
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "vesta_schedules"
STORAGE_VERSION = 1
MIN_SCHEDULE_TEMP = 5.0
MAX_SCHEDULE_TEMP = 35.0
SCHEDULE_MODES = frozenset({"comfort", "eco", "away", "frost", "off"})

# Block format: {"days": [0-6], "start": "HH:MM", "end": "HH:MM", "mode": str}
# mode values: "comfort", "eco", "away", "frost", "off", "temp:22.5"

SCHEDULE_TEMPLATES: dict[str, dict] = {
    "standard_it": {
        "name": "Standard Italia",
        "blocks": [
            {"days": [0, 1, 2, 3, 4], "start": "06:30", "end": "08:30", "mode": "comfort"},
            {"days": [0, 1, 2, 3, 4], "start": "17:30", "end": "22:30", "mode": "comfort"},
            {"days": [5, 6], "start": "08:00", "end": "23:00", "mode": "comfort"},
        ],
    },
    "morning_evening": {
        "name": "Mattina e Sera",
        "blocks": [
            {"days": [0, 1, 2, 3, 4, 5, 6], "start": "06:00", "end": "09:00", "mode": "comfort"},
            {"days": [0, 1, 2, 3, 4, 5, 6], "start": "18:00", "end": "23:00", "mode": "comfort"},
        ],
    },
    "evening_only": {
        "name": "Solo Sera",
        "blocks": [
            {"days": [0, 1, 2, 3, 4, 5, 6], "start": "18:00", "end": "23:00", "mode": "comfort"},
        ],
    },
    "always_eco": {
        "name": "Sempre Eco",
        "blocks": [
            {"days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "24:00", "mode": "eco"},
        ],
    },
}


def _time_to_minutes(t: str, *, end_of_day: bool = False) -> int:
    """Parse HH:MM; 24:00 is valid only as an exclusive block end."""
    if end_of_day and t == "24:00":
        return 1440
    if not isinstance(t, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", t):
        raise ValueError(f"Invalid time {t!r}: expected HH:MM")
    h, m = t.split(":")
    return int(h) * 60 + int(m)


class ScheduleStore:
    """Manages Vesta native schedules with file-based persistence."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._lock = asyncio.Lock()
        self._data: dict[str, Any] = {}  # {schedule_id: {name, blocks}}

    async def async_load(self) -> None:
        """Load schedules from persistent storage."""
        stored = await self._store.async_load()
        if stored and isinstance(stored, dict):
            # Validate structure: keep only well-formed schedule entries
            valid = {}
            for sid, entry in stored.items():
                if (
                    isinstance(entry, dict)
                    and isinstance(entry.get("name"), str)
                    and isinstance(entry.get("blocks"), list)
                ):
                    error = self.validate_blocks(entry["blocks"])
                    if error:
                        _LOGGER.warning("Ignoring invalid persisted schedule %s: %s", sid, error)
                        continue
                    valid[sid] = entry
            self._data = valid
        else:
            self._data = {}

    async def _async_commit(self, data) -> None:
        """Publish a new snapshot only after persistence succeeds."""
        await self._store.async_save(data)
        self._data = data

    def get_all(self) -> dict[str, Any]:
        """Return all schedules as {id: {name, blocks}}."""
        return copy.deepcopy(self._data)

    def get(self, schedule_id: str) -> dict[str, Any] | None:
        """Return a single schedule or None."""
        return copy.deepcopy(self._data.get(schedule_id))

    async def async_create(
        self, name: str, template: str | None = None
    ) -> str:
        """Create a new schedule (optionally from a template) and return its ID."""
        async with self._lock:
            schedule_id = str(uuid.uuid4())
            blocks = copy.deepcopy(SCHEDULE_TEMPLATES[template]["blocks"]) if template in SCHEDULE_TEMPLATES else []
            updated = {**self._data, schedule_id: {"name": name, "blocks": blocks}}
            await self._async_commit(updated)
            return schedule_id

    async def async_duplicate(self, schedule_id: str, new_name: str) -> str | None:
        """Duplicate a committed schedule."""
        async with self._lock:
            if (original := self._data.get(schedule_id)) is None:
                return None
            new_id = str(uuid.uuid4())
            updated = {**self._data, new_id: {"name": new_name, "blocks": copy.deepcopy(original["blocks"])}}
            await self._async_commit(updated)
            return new_id

    async def async_update(self, schedule_id: str, name: str | None = None, blocks: list | None = None) -> bool:
        """Validate and atomically persist updates under the store lock."""
        if blocks is not None and (error := self.validate_blocks(blocks)):
            raise ValueError(error)
        async with self._lock:
            if (entry := self._data.get(schedule_id)) is None:
                return False
            updated_entry = copy.deepcopy(entry)
            if name is not None:
                updated_entry["name"] = name
            if blocks is not None:
                updated_entry["blocks"] = copy.deepcopy(blocks)
            await self._async_commit({**self._data, schedule_id: updated_entry})
            return True

    async def async_delete(self, schedule_id: str) -> bool:
        """Delete a schedule only after the new snapshot reaches storage."""
        async with self._lock:
            if schedule_id not in self._data:
                return False
            updated = {sid: entry for sid, entry in self._data.items() if sid != schedule_id}
            await self._async_commit(updated)
            return True

    def get_current_block(self, schedule_id: str, weekday: int, time_str: str):
        """Return a validated active block, or None."""
        entry = self._data.get(schedule_id)
        if not entry:
            return None
        try:
            minute = _time_to_minutes(time_str)
        except ValueError:
            return None
        for block in entry.get("blocks", []):
            if self.validate_blocks([block]) is not None:
                continue
            if weekday in block["days"] and _time_to_minutes(block["start"]) <= minute < _time_to_minutes(block["end"], end_of_day=True):
                return copy.deepcopy(block)
        return None

    def get_current_mode(
        self, schedule_id: str, weekday: int, time_str: str
    ) -> str:
        """Return the active mode for the given weekday and time.

        weekday: 0=Monday … 6=Sunday (Python's datetime.weekday() convention).
        time_str: "HH:MM"
        Returns "off" if no block is active.
        """
        block = self.get_current_block(schedule_id, weekday, time_str)
        return block["mode"].lower().strip() if block else "off"

    def validate_blocks(self, blocks: list) -> str | None:
        """Validate a block list. Returns an error message or None if valid."""
        if not isinstance(blocks, list):
            return "blocks must be a list"
        # Check each block structure
        for i, block in enumerate(blocks):
            if not isinstance(block, dict):
                return f"block {i}: must be an object"
            days = block.get("days")
            if not isinstance(days, list) or not days:
                return f"block {i}: 'days' must be a non-empty list"
            if not all(type(d) is int and 0 <= d <= 6 for d in days):
                return f"block {i}: 'days' values must be integers in range 0-6"
            if not block.get("start") or not block.get("end"):
                return f"block {i}: 'start' and 'end' are required"
            try:
                s = _time_to_minutes(block["start"])
                e = _time_to_minutes(block["end"], end_of_day=True)
            except (ValueError, KeyError):
                return f"block {i}: invalid time format (expected HH:MM)"
            if s >= e:
                return f"block {i}: 'start' must be before 'end'"
            mode = block.get("mode")
            if not isinstance(mode, str) or not mode.strip():
                return f"block {i}: 'mode' is required"
            mode = mode.lower().strip()
            if mode in SCHEDULE_MODES:
                continue
            if not mode.startswith("temp:"):
                return f"block {i}: unsupported mode '{mode}'"
            try:
                temperature = float(mode.split(":", 1)[1])
            except (TypeError, ValueError):
                return f"block {i}: invalid custom temperature"
            if not math.isfinite(temperature):
                return f"block {i}: custom temperature must be finite"
            if not MIN_SCHEDULE_TEMP <= temperature <= MAX_SCHEDULE_TEMP:
                return (
                    f"block {i}: custom temperature must be between "
                    f"{MIN_SCHEDULE_TEMP:g} and {MAX_SCHEDULE_TEMP:g} °C"
                )

        # Check overlaps per day
        for day in range(7):
            day_blocks = [
                b for b in blocks if day in b.get("days", [])
            ]
            day_blocks.sort(key=lambda b: _time_to_minutes(b["start"]))
            for j in range(len(day_blocks) - 1):
                end_j = _time_to_minutes(day_blocks[j]["end"], end_of_day=True)
                start_next = _time_to_minutes(day_blocks[j + 1]["start"])
                if end_j > start_next:
                    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                    return (
                        f"overlap on {day_names[day]}: "
                        f"{day_blocks[j]['start']}-{day_blocks[j]['end']} "
                        f"overlaps {day_blocks[j+1]['start']}-{day_blocks[j+1]['end']}"
                    )
        return None
