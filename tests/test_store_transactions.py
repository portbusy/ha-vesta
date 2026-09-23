"""Persistence failure and concurrency must not change the active schedule."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from custom_components.vesta.store import ScheduleStore


@pytest.mark.parametrize("operation", ["create", "duplicate", "update", "delete"])
async def test_write_failure_preserves_committed_data(hass, operation):
    store = ScheduleStore(hass)
    store._data = {"s": {"name": "Original", "blocks": []}}
    store._store.async_save = AsyncMock(side_effect=OSError("disk full"))
    operations = {
        "create": lambda: store.async_create("New"),
        "duplicate": lambda: store.async_duplicate("s", "Copy"),
        "update": lambda: store.async_update("s", name="Changed"),
        "delete": lambda: store.async_delete("s"),
    }
    with pytest.raises(OSError):
        await operations[operation]()
    assert store.get_all() == {"s": {"name": "Original", "blocks": []}}


async def test_concurrent_updates_are_serialized(hass):
    store = ScheduleStore(hass)
    started = asyncio.Event()
    release = asyncio.Event()
    snapshots = []
    async def save(data):
        snapshots.append(data)
        if len(snapshots) == 1:
            started.set()
            await release.wait()
    store._store.async_save = AsyncMock(side_effect=save)
    first = asyncio.create_task(store.async_create("First"))
    await started.wait()
    second = asyncio.create_task(store.async_create("Second"))
    assert store.get_all() == {}
    release.set()
    await asyncio.gather(first, second)
    assert len(snapshots) == 2
    assert len(snapshots[-1]) == 2
    assert {entry["name"] for entry in store.get_all().values()} == {"First", "Second"}


async def test_callers_cannot_mutate_active_schedule(hass):
    store = ScheduleStore(hass)
    store._store.async_save = AsyncMock()
    sid = await store.async_create("Original")
    blocks = [{"days": [0], "start": "00:00", "end": "24:00", "mode": "eco"}]
    await store.async_update(sid, blocks=blocks)
    blocks[0]["mode"] = "off"
    store.get(sid)["blocks"].clear()
    store.get_all()[sid]["name"] = "Mutated"
    assert store.get(sid)["name"] == "Original"
    assert store.get_current_mode(sid, 0, "23:59") == "eco"


async def test_corrupted_persisted_block_is_skipped(hass):
    store = ScheduleStore(hass)
    store._store.async_load = AsyncMock(return_value={
        "bad": {"name": "Bad", "blocks": [{"days": None}]},
        "good": {"name": "Good", "blocks": []},
    })
    await store.async_load()
    assert list(store.get_all()) == ["good"]


async def test_all_day_template_has_no_gap_at_midnight(hass):
    store = ScheduleStore(hass)
    store._store.async_save = AsyncMock()
    sid = await store.async_create("Eco", "always_eco")
    assert store.get_current_mode(sid, 0, "23:59") == "eco"
    assert store.get_current_mode(sid, 1, "00:00") == "eco"
