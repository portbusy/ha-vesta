"""WebSocket API for Vesta native schedules."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry

from .const import (
    DOMAIN,
    CONF_ENTRY_TYPE,
    ENTRY_TYPE_GLOBAL,
    ENTRY_TYPE_ROOM,
    CONF_OVERRIDE_SCHEDULE,
    CONF_SCHEDULE_SOURCE,
    CONF_VESTA_SCHEDULE_ID,
    SCHEDULE_SOURCE_VESTA,
    SCHEDULE_SOURCE_ENTITY,
)
from .store import SCHEDULE_TEMPLATES


@callback
def async_setup_api(hass: HomeAssistant) -> None:
    """Register all Vesta WebSocket commands."""
    websocket_api.async_register_command(hass, ws_list_schedules)
    websocket_api.async_register_command(hass, ws_get_schedule)
    websocket_api.async_register_command(hass, ws_create_schedule)
    websocket_api.async_register_command(hass, ws_duplicate_schedule)
    websocket_api.async_register_command(hass, ws_update_schedule)
    websocket_api.async_register_command(hass, ws_delete_schedule)
    websocket_api.async_register_command(hass, ws_list_rooms)
    websocket_api.async_register_command(hass, ws_assign_room)
    websocket_api.async_register_command(hass, ws_get_global_schedule)
    websocket_api.async_register_command(hass, ws_set_global_schedule)
    websocket_api.async_register_command(hass, ws_list_templates)


# ---------------------------------------------------------------------------
# Schedule CRUD
# ---------------------------------------------------------------------------

@websocket_api.websocket_command({vol.Required("type"): "vesta/schedules/list"})
@callback
def ws_list_schedules(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    store = hass.data[DOMAIN].get("schedule_store")
    if not store:
        connection.send_error(msg["id"], "store_unavailable", "Schedule store not ready")
        return
    schedules = store.get_all()
    result = [
        {"id": sid, "name": s["name"], "block_count": len(s.get("blocks", []))}
        for sid, s in schedules.items()
    ]
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "vesta/schedules/get",
        vol.Required("schedule_id"): str,
    }
)
@callback
def ws_get_schedule(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    store = hass.data[DOMAIN].get("schedule_store")
    if not store:
        connection.send_error(msg["id"], "store_unavailable", "Schedule store not ready")
        return
    entry = store.get(msg["schedule_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Schedule not found")
        return
    connection.send_result(msg["id"], {"id": msg["schedule_id"], **entry})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "vesta/schedules/create",
        vol.Required("name"): str,
        vol.Optional("template"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_create_schedule(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    store = hass.data[DOMAIN].get("schedule_store")
    if not store:
        connection.send_error(msg["id"], "store_unavailable", "Schedule store not ready")
        return
    schedule_id = await store.async_create(msg["name"], msg.get("template"))
    connection.send_result(msg["id"], {"id": schedule_id, "name": msg["name"]})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "vesta/schedules/duplicate",
        vol.Required("schedule_id"): str,
        vol.Required("new_name"): str,
    }
)
@websocket_api.async_response
async def ws_duplicate_schedule(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    store = hass.data[DOMAIN].get("schedule_store")
    if not store:
        connection.send_error(msg["id"], "store_unavailable", "Schedule store not ready")
        return
    new_id = await store.async_duplicate(msg["schedule_id"], msg["new_name"])
    if new_id is None:
        connection.send_error(msg["id"], "not_found", "Schedule not found")
    else:
        connection.send_result(msg["id"], {"id": new_id, "name": msg["new_name"]})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "vesta/schedules/update",
        vol.Required("schedule_id"): str,
        vol.Optional("name"): str,
        vol.Optional("blocks"): list,
    }
)
@websocket_api.async_response
async def ws_update_schedule(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    store = hass.data[DOMAIN].get("schedule_store")
    if not store:
        connection.send_error(msg["id"], "store_unavailable", "Schedule store not ready")
        return
    try:
        ok = await store.async_update(
            msg["schedule_id"],
            name=msg.get("name"),
            blocks=msg.get("blocks"),
        )
    except ValueError as exc:
        connection.send_error(msg["id"], "invalid_blocks", str(exc))
        return
    if not ok:
        connection.send_error(msg["id"], "not_found", "Schedule not found")
        return
    entry = store.get(msg["schedule_id"])
    connection.send_result(msg["id"], {"id": msg["schedule_id"], **entry})
    # Trigger a tick on rooms using this schedule
    for room in hass.data[DOMAIN].get("rooms", []):
        if hasattr(room, "_async_tick"):
            hass.async_create_task(room._async_tick(None))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "vesta/schedules/delete",
        vol.Required("schedule_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_schedule(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    store = hass.data[DOMAIN].get("schedule_store")
    if not store:
        connection.send_error(msg["id"], "store_unavailable", "Schedule store not ready")
        return
    ok = await store.async_delete(msg["schedule_id"])
    if not ok:
        connection.send_error(msg["id"], "not_found", "Schedule not found")
        return

    connection.send_result(msg["id"], {"deleted": msg["schedule_id"]})

    # Remove the schedule from any room or global entry that was using it
    sid = msg["schedule_id"]
    entries_to_reload = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_VESTA_SCHEDULE_ID) == sid:
            new_data = {k: v for k, v in entry.data.items()
                        if k not in (CONF_SCHEDULE_SOURCE, CONF_VESTA_SCHEDULE_ID)}
            hass.config_entries.async_update_entry(entry, data=new_data)
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
                entries_to_reload.append(entry.entry_id)
    for eid in entries_to_reload:
        await hass.config_entries.async_reload(eid)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

@websocket_api.websocket_command({vol.Required("type"): "vesta/schedules/templates"})
@callback
def ws_list_templates(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    result = [
        {"id": tid, "name": tdata["name"], "block_count": len(tdata["blocks"])}
        for tid, tdata in SCHEDULE_TEMPLATES.items()
    ]
    connection.send_result(msg["id"], result)


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------

@websocket_api.websocket_command({vol.Required("type"): "vesta/rooms/list"})
@callback
def ws_list_rooms(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    result = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
            continue
        source = entry.data.get(CONF_SCHEDULE_SOURCE, SCHEDULE_SOURCE_ENTITY)
        vesta_id = entry.data.get(CONF_VESTA_SCHEDULE_ID)
        result.append({
            "entry_id": entry.entry_id,
            "name": entry.title,
            "schedule_source": source,
            "vesta_schedule_id": vesta_id,
            "override_schedule": entry.data.get(CONF_OVERRIDE_SCHEDULE, False),
        })
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "vesta/rooms/assign",
        vol.Required("entry_id"): str,
        vol.Required("schedule_source"): vol.In([SCHEDULE_SOURCE_ENTITY, SCHEDULE_SOURCE_VESTA, "inherit"]),
        vol.Optional("vesta_schedule_id"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_assign_room(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if not entry or entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
        connection.send_error(msg["id"], "not_found", "Room entry not found")
        return

    new_data = dict(entry.data)
    source = msg["schedule_source"]

    if source == "inherit":
        new_data.pop(CONF_SCHEDULE_SOURCE, None)
        new_data.pop(CONF_VESTA_SCHEDULE_ID, None)
    elif source == SCHEDULE_SOURCE_VESTA:
        vesta_id = msg.get("vesta_schedule_id")
        if not vesta_id:
            connection.send_error(msg["id"], "missing_id", "vesta_schedule_id required")
            return
        new_data[CONF_SCHEDULE_SOURCE] = SCHEDULE_SOURCE_VESTA
        new_data[CONF_VESTA_SCHEDULE_ID] = vesta_id
    else:
        new_data[CONF_SCHEDULE_SOURCE] = SCHEDULE_SOURCE_ENTITY

    hass.config_entries.async_update_entry(entry, data=new_data)
    connection.send_result(msg["id"], {"entry_id": msg["entry_id"], "assigned": source})

    # Trigger immediate tick on this room
    for room in hass.data[DOMAIN].get("rooms", []):
        if getattr(room, "_entry", None) and room._entry.entry_id == msg["entry_id"]:
            if hasattr(room, "_async_tick"):
                hass.async_create_task(room._async_tick(None))


# ---------------------------------------------------------------------------
# Global schedule
# ---------------------------------------------------------------------------

@websocket_api.websocket_command({vol.Required("type"): "vesta/global/get_schedule"})
@callback
def ws_get_global_schedule(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    g = hass.data[DOMAIN].get("global")
    if not g:
        connection.send_result(msg["id"], {"schedule_source": None, "vesta_schedule_id": None})
        return
    source = g.data.get(CONF_SCHEDULE_SOURCE, SCHEDULE_SOURCE_ENTITY)
    vesta_id = g.data.get(CONF_VESTA_SCHEDULE_ID)
    connection.send_result(msg["id"], {
        "schedule_source": source,
        "vesta_schedule_id": vesta_id,
    })


@websocket_api.websocket_command(
    {
        vol.Required("type"): "vesta/global/set_schedule",
        vol.Required("schedule_source"): vol.In([SCHEDULE_SOURCE_ENTITY, SCHEDULE_SOURCE_VESTA]),
        vol.Optional("vesta_schedule_id"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_set_global_schedule(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    g = hass.data[DOMAIN].get("global")
    if not g:
        connection.send_error(msg["id"], "no_global", "Global entry not configured")
        return

    new_data = dict(g.data)
    new_data[CONF_SCHEDULE_SOURCE] = msg["schedule_source"]
    if msg["schedule_source"] == SCHEDULE_SOURCE_VESTA:
        vesta_id = msg.get("vesta_schedule_id")
        if not vesta_id:
            connection.send_error(msg["id"], "missing_id", "vesta_schedule_id required")
            return
        new_data[CONF_VESTA_SCHEDULE_ID] = vesta_id
    else:
        new_data.pop(CONF_VESTA_SCHEDULE_ID, None)

    hass.config_entries.async_update_entry(g, data=new_data)
    connection.send_result(msg["id"], {"ok": True})
    for room in hass.data[DOMAIN].get("rooms", []):
        if hasattr(room, "_async_tick"):
            hass.async_create_task(room._async_tick(None))
