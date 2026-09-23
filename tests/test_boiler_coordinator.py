"""Tests for aggregate boiler demand and state reconciliation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio

import pytest

from custom_components.vesta import BoilerCoordinator


def _hass_with_boiler(state="off"):
    return SimpleNamespace(
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(state=state, attributes={})
        ),
        services=SimpleNamespace(async_call=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_climate_boiler_uses_effective_room_target():
    hass = _hass_with_boiler()
    coordinator = BoilerCoordinator(hass, "climate.boiler", 5.0)
    room = SimpleNamespace(
        boiler_demand=True,
        boiler_target_temperature=35.0,
        comfort_temp=21.0,
    )

    await coordinator.async_update([room])

    assert hass.services.async_call.await_count == 2
    assert hass.services.async_call.await_args_list[1].args == (
        "climate",
        "set_temperature",
        {"entity_id": "climate.boiler", "temperature": 40.0},
    )


@pytest.mark.asyncio
async def test_external_boiler_shutdown_is_reconciled():
    hass = _hass_with_boiler(state="off")
    coordinator = BoilerCoordinator(hass, "climate.boiler", 5.0)
    coordinator._last_boiler_on = True
    coordinator._last_flow_temp = 26.0
    room = SimpleNamespace(
        boiler_demand=True,
        boiler_target_temperature=21.0,
        comfort_temp=21.0,
    )

    await coordinator.async_update([room])

    assert hass.services.async_call.await_count == 2
    assert hass.services.async_call.await_args_list[0].args[2]["hvac_mode"] == "heat"


async def test_failed_command_is_retried():
    hass = _hass_with_boiler()
    coordinator = BoilerCoordinator(hass, "switch.boiler", 5)
    room = SimpleNamespace(boiler_demand=True)
    hass.services.async_call.side_effect = RuntimeError("offline")
    await coordinator.async_update([room])
    assert coordinator._last_boiler_on is None
    hass.services.async_call.side_effect = None
    await coordinator.async_update([room])
    assert hass.services.async_call.await_count == 2
    assert coordinator._last_boiler_on is True


async def test_shutdown_serializes_and_blocks_queued_heat():
    hass = _hass_with_boiler()
    coordinator = BoilerCoordinator(hass, "switch.boiler", 5)
    started, release = asyncio.Event(), asyncio.Event()
    async def send(domain, service, data, **kwargs):
        if service == "turn_on":
            started.set()
            await release.wait()
    hass.services.async_call.side_effect = send
    room = SimpleNamespace(boiler_demand=True)
    first = asyncio.create_task(coordinator.async_update([room]))
    await started.wait()
    shutdown = asyncio.create_task(coordinator.async_shutdown())
    queued = asyncio.create_task(coordinator.async_update([room]))
    release.set()
    await asyncio.gather(first, shutdown, queued)
    assert [call.args[1] for call in hass.services.async_call.await_args_list] == ["turn_on", "turn_off"]
    assert coordinator._closed
    assert not coordinator._last_boiler_on


async def test_climate_boiler_reconciles_external_target(hass, monkeypatch):
    coordinator = BoilerCoordinator(hass, "climate.boiler", 5)
    room = SimpleNamespace(boiler_demand=True, boiler_target_temperature=21)
    service = AsyncMock()
    monkeypatch.setattr(type(hass.services), "async_call", service)
    hass.states.async_set("climate.boiler", "heat", {"temperature": 26})
    await coordinator.async_update([room])
    service.reset_mock()
    hass.states.async_set("climate.boiler", "heat", {"temperature": 40})
    await coordinator.async_update([room])
    assert service.await_count == 1
    assert service.await_args.args[2]["temperature"] == 26
