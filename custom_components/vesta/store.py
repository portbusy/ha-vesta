"""Persistent storage for Vesta native schedules."""
from __future__ import annotations

import copy
import uuid
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

STORAGE_KEY = "vesta_schedules"
STORAGE_VERSION = 1

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
            {"days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "23:59", "mode": "eco"},
        ],
    },
}


def _time_to_minutes(t: str) -> int:
    """Convert HH:MM to minutes since midnight."""
    h, m = t.split(":")
    return int(h) * 60 + int(m)


class ScheduleStore:
    """Manages Vesta native schedules with file-based persistence."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
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
                    valid[sid] = entry
            self._data = valid
        else:
            self._data = {}

    async def async_save(self) -> None:
        """Persist schedules to storage."""
        await self._store.async_save(self._data)

    def get_all(self) -> dict[str, Any]:
        """Return all schedules as {id: {name, blocks}}."""
        return dict(self._data)

    def get(self, schedule_id: str) -> dict[str, Any] | None:
        """Return a single schedule or None."""
        return self._data.get(schedule_id)

    async def async_create(
        self, name: str, template: str | None = None
    ) -> str:
        """Create a new schedule (optionally from a template) and return its ID."""
        schedule_id = str(uuid.uuid4())
        if template and template in SCHEDULE_TEMPLATES:
            blocks = copy.deepcopy(SCHEDULE_TEMPLATES[template]["blocks"])
        else:
            blocks = []
        self._data[schedule_id] = {"name": name, "blocks": blocks}
        await self.async_save()
        return schedule_id

    async def async_duplicate(
        self, schedule_id: str, new_name: str
    ) -> str | None:
        """Duplicate an existing schedule and return the new ID."""
        original = self._data.get(schedule_id)
        if original is None:
            return None
        new_id = str(uuid.uuid4())
        self._data[new_id] = {
            "name": new_name,
            "blocks": copy.deepcopy(original["blocks"]),
        }
        await self.async_save()
        return new_id

    async def async_update(
        self,
        schedule_id: str,
        name: str | None = None,
        blocks: list | None = None,
    ) -> bool:
        """Update name and/or blocks. Returns False if schedule not found."""
        entry = self._data.get(schedule_id)
        if entry is None:
            return False
        if name is not None:
            entry["name"] = name
        if blocks is not None:
            err = self.validate_blocks(blocks)
            if err:
                raise ValueError(err)
            entry["blocks"] = blocks
        await self.async_save()
        return True

    async def async_delete(self, schedule_id: str) -> bool:
        """Delete a schedule. Returns False if not found."""
        if schedule_id not in self._data:
            return False
        del self._data[schedule_id]
        await self.async_save()
        return True

    def get_current_mode(
        self, schedule_id: str, weekday: int, time_str: str
    ) -> str:
        """Return the active mode for the given weekday and time.

        weekday: 0=Monday … 6=Sunday (Python's datetime.weekday() convention).
        time_str: "HH:MM"
        Returns "off" if no block is active.
        """
        entry = self._data.get(schedule_id)
        if not entry:
            return "off"
        current_minutes = _time_to_minutes(time_str)
        for block in entry.get("blocks", []):
            if weekday not in block.get("days", []):
                continue
            start = _time_to_minutes(block["start"])
            end = _time_to_minutes(block["end"])
            if start <= current_minutes < end:
                return block.get("mode", "comfort")
        return "off"

    def validate_blocks(self, blocks: list) -> str | None:
        """Validate a block list. Returns an error message or None if valid."""
        if not isinstance(blocks, list):
            return "blocks must be a list"
        # Check each block structure
        for i, block in enumerate(blocks):
            if not isinstance(block.get("days"), list):
                return f"block {i}: 'days' must be a list"
            if not block.get("start") or not block.get("end"):
                return f"block {i}: 'start' and 'end' are required"
            try:
                s = _time_to_minutes(block["start"])
                e = _time_to_minutes(block["end"])
            except (ValueError, KeyError):
                return f"block {i}: invalid time format (expected HH:MM)"
            if s >= e:
                return f"block {i}: 'start' must be before 'end'"
            if not block.get("mode"):
                return f"block {i}: 'mode' is required"

        # Check overlaps per day
        for day in range(7):
            day_blocks = [
                b for b in blocks if day in b.get("days", [])
            ]
            day_blocks.sort(key=lambda b: _time_to_minutes(b["start"]))
            for j in range(len(day_blocks) - 1):
                end_j = _time_to_minutes(day_blocks[j]["end"])
                start_next = _time_to_minutes(day_blocks[j + 1]["start"])
                if end_j > start_next:
                    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                    return (
                        f"overlap on {day_names[day]}: "
                        f"{day_blocks[j]['start']}-{day_blocks[j]['end']} "
                        f"overlaps {day_blocks[j+1]['start']}-{day_blocks[j+1]['end']}"
                    )
        return None
