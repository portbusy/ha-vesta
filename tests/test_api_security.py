import asyncio
"""Authorization and reference-integrity tests for the Vesta WebSocket API."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import Unauthorized

from custom_components.vesta import api
from custom_components.vesta.store import ScheduleStore


MUTATING_COMMANDS = [
    api.ws_create_schedule,
    api.ws_duplicate_schedule,
    api.ws_update_schedule,
    api.ws_delete_schedule,
    api.ws_assign_room,
    api.ws_set_global_schedule,
]


@pytest.mark.parametrize("command", MUTATING_COMMANDS)
def test_mutating_commands_reject_non_admin_users(command):
    connection = SimpleNamespace(user=SimpleNamespace(is_admin=False))

    with pytest.raises(Unauthorized):
        command(None, connection, {"id": 1})


def test_mutating_command_allows_admin_user_through_authorization_boundary():
    class FakeHass:
        called = False

        def async_create_background_task(self, coro, *_args, **_kwargs):
            self.called = True
            coro.close()

    hass = FakeHass()
    connection = SimpleNamespace(user=SimpleNamespace(is_admin=True))

    api.ws_create_schedule(hass, connection, {"id": 1})

    assert hass.called is True


@pytest.mark.asyncio
async def test_room_assignment_rejects_unknown_schedule_id():
    entry = SimpleNamespace(entry_id="room-1", domain="vesta", data={"entry_type": "room"})

    class ConfigEntries:
        def async_get_entry(self, entry_id):
            return entry if entry_id == "room-1" else None

        def async_update_entry(self, *_args, **_kwargs):
            raise AssertionError("invalid schedule must not update the entry")

    connection = SimpleNamespace(
        send_error=lambda *args: errors.append(args),
        send_result=lambda *_args: None,
    )
    errors = []
    hass = SimpleNamespace(
        config_entries=ConfigEntries(),
        data={"vesta": {"schedule_store": SimpleNamespace(get=lambda _sid: None)}},
    )
    original_handler = api.ws_assign_room.__wrapped__.__wrapped__

    await original_handler(
        hass,
        connection,
        {
            "id": 1,
            "entry_id": "room-1",
            "schedule_source": "vesta",
            "vesta_schedule_id": "missing",
        },
    )

    assert errors == [(1, "not_found", "Schedule not found")]


def _schedule_store():
    store = ScheduleStore.__new__(ScheduleStore)
    store._data = {"s1": {"name": "Test", "blocks": []}}
    store._lock = asyncio.Lock()
    store._store = SimpleNamespace(async_save=AsyncMock())
    return store


@pytest.mark.asyncio
async def test_schedule_update_api_rejects_unsafe_temperature():
    store = _schedule_store()
    errors = []
    connection = SimpleNamespace(
        send_error=lambda *args: errors.append(args),
        send_result=lambda *_args: None,
    )
    hass = SimpleNamespace(data={"vesta": {"schedule_store": store}})
    original_handler = api.ws_update_schedule.__wrapped__.__wrapped__

    await original_handler(
        hass,
        connection,
        {
            "id": 1,
            "schedule_id": "s1",
            "blocks": [
                {
                    "days": [0],
                    "start": "06:00",
                    "end": "09:00",
                    "mode": "temp:1000",
                }
            ],
        },
    )

    assert errors and errors[0][1] == "invalid_blocks"
    assert store.get("s1")["blocks"] == []
    store._store.async_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_update_api_preserves_valid_custom_temperature():
    store = _schedule_store()
    results = []
    connection = SimpleNamespace(
        send_error=lambda *_args: None,
        send_result=lambda *args: results.append(args),
    )
    hass = SimpleNamespace(
        data={"vesta": {"schedule_store": store, "rooms": []}},
        async_create_task=lambda _coro: None,
    )
    original_handler = api.ws_update_schedule.__wrapped__.__wrapped__
    blocks = [
        {
            "days": [0],
            "start": "06:00",
            "end": "09:00",
            "mode": "temp:23.5",
        }
    ]

    await original_handler(
        hass,
        connection,
        {"id": 1, "schedule_id": "s1", "blocks": blocks},
    )

    assert results[0][1]["blocks"] == blocks
    store._store.async_save.assert_awaited_once()
