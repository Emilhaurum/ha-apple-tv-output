"""Tests for the config entry: entities, default speakers, options and diagnostics."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.apple_tv_output import defaults
from custom_components.apple_tv_output.const import CONF_DEFAULT_SPEAKERS
from custom_components.apple_tv_output.diagnostics import async_get_config_entry_diagnostics

from .conftest import ATV_ENTITY, ATV_NAME, VOLUME, FakeSpeaker, Network, add_apple_tv

LIVING = FakeSpeaker("Living Room", "34:7E:5C:D6:4E:1E")
KITCHEN = FakeSpeaker("Kitchen", "48:A6:B8:00:00:01")
SENSOR = "sensor.living_room_tv_audio_outputs"
SELECT = "select.living_room_tv_audio_output"


@pytest.fixture(autouse=True)
def speakers(network: Network) -> None:
    network.add(LIVING, KITCHEN)


def atv_registry_id(hass: HomeAssistant) -> str:
    entry = er.async_get(hass).async_get(ATV_ENTITY)
    assert entry is not None
    return entry.id


async def poll(hass: HomeAssistant) -> None:
    """Let the entities read the outputs again."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3))
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_sensor(hass: HomeAssistant, atv: Any, setup_integration: Any) -> None:
    await setup_integration()
    atv.audio.set_current((ATV_NAME, "AA:BB:CC:DD:EE:FF"), ("Living Room", LIVING.airplay_id))
    await poll(hass)
    state = hass.states.get(SENSOR)
    assert state is not None
    assert state.state == f"{ATV_NAME}, Living Room"
    assert state.attributes["speakers"] == ["Living Room"]
    assert [o["identifier"] for o in state.attributes["outputs"]] == ["AA:BB:CC:DD:EE:FF", LIVING.airplay_id]

    # Disconnected Apple TV: unavailable.
    hass.config_entries.async_entries("apple_tv")[0].runtime_data = SimpleNamespace(atv=None)
    await poll(hass)
    assert hass.states.get(SENSOR).state == STATE_UNAVAILABLE


async def test_sensor_follows_state_changes(hass: HomeAssistant, atv: Any, setup_integration: Any) -> None:
    """A change of the Apple TV's state refreshes at once, without waiting for the next poll."""
    await setup_integration()
    atv.audio.set_current(("Kitchen", KITCHEN.airplay_id))
    hass.states.async_set(ATV_ENTITY, "playing")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(SENSOR).state == "Kitchen"


async def test_entities_device(hass: HomeAssistant, atv: Any, setup_integration: Any) -> None:
    """The entities get a device named like the Apple TV, connected via the Apple TV's device."""
    await setup_integration()
    entities, devices = er.async_get(hass), dr.async_get(hass)
    own = entities.async_get(SENSOR).device_id
    assert entities.async_get(SELECT).device_id == own
    device = devices.async_get(own)
    assert device.name == ATV_NAME
    assert device.via_device_id == entities.async_get(ATV_ENTITY).device_id


async def test_select(hass: HomeAssistant, atv: Any, setup_integration: Any) -> None:
    await setup_integration()
    state = hass.states.get(SELECT)
    # The background scan found the speakers.
    assert state.attributes["options"] == ["Kitchen", "Living Room"]
    assert state.state == "unknown"

    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "Kitchen"}, blocking=True)
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]
    assert hass.states.get(SELECT).state == "Kitchen"

    # Several speakers: nothing selected.
    atv.audio.set_current(("Kitchen", KITCHEN.airplay_id), ("Living Room", LIVING.airplay_id))
    await poll(hass)
    assert hass.states.get(SELECT).state == "unknown"


async def test_default_speakers_on_wake(hass: HomeAssistant, atv: Any, setup_integration: Any) -> None:
    hass.states.async_set(ATV_ENTITY, "off")
    await setup_integration({CONF_DEFAULT_SPEAKERS: {atv_registry_id(hass): ["Kitchen"]}})
    assert atv.audio.calls == []

    hass.states.async_set(ATV_ENTITY, "idle")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]

    # The user then picks another speaker by hand; playing after idle is not a wake-up, so it stays.
    atv.audio.set_current(("Living Room", LIVING.airplay_id))
    hass.states.async_set(ATV_ENTITY, "playing")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(atv.audio.calls) == 1
    assert [d.name for d in atv.audio.output_devices] == ["Living Room"]


async def test_default_speakers_when_already_awake(hass: HomeAssistant, atv: Any, setup_integration: Any) -> None:
    hass.states.async_set(ATV_ENTITY, "playing")
    await setup_integration({CONF_DEFAULT_SPEAKERS: {atv_registry_id(hass): ["Kitchen"]}})
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]


async def test_default_speakers_wait_for_connection(hass: HomeAssistant, atv: Any, setup_integration: Any) -> None:
    """The Apple TV reports idle before its connection is ready."""
    apple_tv_entry = hass.config_entries.async_entries("apple_tv")[0]
    apple_tv_entry.runtime_data = SimpleNamespace(atv=None)
    hass.states.async_set(ATV_ENTITY, "off")
    await setup_integration({CONF_DEFAULT_SPEAKERS: {atv_registry_id(hass): ["Kitchen"]}})

    attempts = 0
    real_get_apple_tv = defaults.get_apple_tv

    def get_apple_tv(*args: Any, **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 3:
            # Connected after two failed attempts.
            apple_tv_entry.runtime_data = SimpleNamespace(atv=atv)
        return real_get_apple_tv(*args, **kwargs)

    with patch.object(defaults, "get_apple_tv", get_apple_tv):
        hass.states.async_set(ATV_ENTITY, "idle")
        await hass.async_block_till_done(wait_background_tasks=True)
    assert attempts == 3
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]


async def test_default_speakers_retry(hass: HomeAssistant, atv: Any, setup_integration: Any) -> None:
    """Right after waking, the Apple TV ignores the first command."""
    atv.audio.ignore = 1
    hass.states.async_set(ATV_ENTITY, "off")
    await setup_integration({CONF_DEFAULT_SPEAKERS: {atv_registry_id(hass): ["Kitchen"]}})
    hass.states.async_set(ATV_ENTITY, "idle")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))] * 2
    assert [d.name for d in atv.audio.output_devices] == ["Kitchen"]


async def test_options_flow(hass: HomeAssistant, atv: Any, setup_integration: Any) -> None:
    entry = await setup_integration()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"apple_tv": atv_registry_id(hass)})
    assert result["step_id"] == "speakers"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"speakers": ["Kitchen"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_DEFAULT_SPEAKERS: {atv_registry_id(hass): ["Kitchen"]}}
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED

    # Emptying the list removes the Apple TV's default speakers.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"apple_tv": atv_registry_id(hass)})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"speakers": []})
    assert entry.options == {CONF_DEFAULT_SPEAKERS: {}}


async def test_options_flow_without_apple_tv(hass: HomeAssistant, atv: Any, setup_integration: Any) -> None:
    entry = await setup_integration()
    er.async_get(hass).async_remove(ATV_ENTITY)
    await hass.async_block_till_done(wait_background_tasks=True)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_apple_tvs"


async def test_new_apple_tv_gets_entities(
    hass: HomeAssistant, atv: Any, network: Network, setup_integration: Any
) -> None:
    await setup_integration()
    add_apple_tv(hass, network, "bedroom_tv", "Bedroom TV", "99999999-2222-3333-4444-555555555555", "AA:BB:CC:00:00:01")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("sensor.bedroom_tv_audio_outputs") is not None


async def test_unload(hass: HomeAssistant, atv: Any, setup_integration: Any) -> None:
    entry = await setup_integration()
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics(hass: HomeAssistant, atv: Any, setup_integration: Any) -> None:
    entry = await setup_integration({CONF_DEFAULT_SPEAKERS: {atv_registry_id(hass): ["Kitchen"]}})
    atv.audio.set_current(("Living Room", LIVING.airplay_id))
    await poll(hass)
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data["default_speakers"] == {ATV_ENTITY: ["Kitchen"]}
    assert data["apple_tvs"][0]["connected"] is True
    assert data["apple_tvs"][0]["outputs"][0] == {"name": "Living Room", "identifier": "**REDACTED**", **VOLUME}
    assert {"name": "Kitchen", "identifier": "**REDACTED**"} in data["speakers_found"]
    assert data["versions"]["integration"] == "1.2.0"
