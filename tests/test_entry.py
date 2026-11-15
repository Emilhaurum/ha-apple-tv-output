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


async def test_default_speakers_not_applied_when_already_awake(
    hass: HomeAssistant, atv: Any, setup_integration: Any
) -> None:
    """Home Assistant starts while the Apple TV is on: the user may have picked the speaker by hand."""
    hass.states.async_set(ATV_ENTITY, "playing")
    await setup_integration({CONF_DEFAULT_SPEAKERS: {atv_registry_id(hass): ["Kitchen"]}})
    assert atv.audio.calls == []


async def test_default_speakers_after_unknown_state(hass: HomeAssistant, atv: Any, setup_integration: Any) -> None:
    """Unknown (starting up) to idle is not a wake-up; off to idle afterwards is."""
    await setup_integration({CONF_DEFAULT_SPEAKERS: {atv_registry_id(hass): ["Kitchen"]}})
    hass.states.async_set(ATV_ENTITY, "idle")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert atv.audio.calls == []
    hass.states.async_set(ATV_ENTITY, "off")
    hass.states.async_set(ATV_ENTITY, "idle")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]


async def test_default_speakers_not_applied_after_connection_gap(
    hass: HomeAssistant, atv: Any, setup_integration: Any
) -> None:
    """Playing, unavailable for a moment, playing again: not a wake-up."""
    hass.states.async_set(ATV_ENTITY, "playing")
    await setup_integration({CONF_DEFAULT_SPEAKERS: {atv_registry_id(hass): ["Kitchen"]}})
    for state in ("unavailable", "playing"):
        hass.states.async_set(ATV_ENTITY, state)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert atv.audio.calls == []


async def test_default_speakers_not_applied_on_reload(hass: HomeAssistant, atv: Any, setup_integration: Any) -> None:
    hass.states.async_set(ATV_ENTITY, "off")
    entry = await setup_integration({CONF_DEFAULT_SPEAKERS: {atv_registry_id(hass): ["Kitchen"]}})
    hass.states.async_set(ATV_ENTITY, "idle")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(atv.audio.calls) == 1
    # The user picks another speaker by hand; reloading must not switch back.
    atv.audio.set_current(("Living Room", LIVING.airplay_id))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(atv.audio.calls) == 1


async def test_changed_default_speakers_applied_at_once(hass: HomeAssistant, atv: Any, setup_integration: Any) -> None:
    hass.states.async_set(ATV_ENTITY, "playing")
    entry = await setup_integration()
    hass.config_entries.async_update_entry(entry, options={CONF_DEFAULT_SPEAKERS: {atv_registry_id(hass): ["Kitchen"]}})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]


async def test_default_speakers_stop_on_lasting_error(
    hass: HomeAssistant, atv: Any, setup_integration: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """An error that waiting cannot fix is not retried for the whole connection wait."""
    hass.states.async_set(ATV_ENTITY, "off")
    await setup_integration({CONF_DEFAULT_SPEAKERS: {atv_registry_id(hass): ["Garage"]}})
    hass.states.async_set(ATV_ENTITY, "idle")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert caplog.text.count("Could not send media_player.living_room_tv to its default speakers") == 1
    assert atv.audio.calls == []


async def test_renamed_apple_tv(hass: HomeAssistant, atv: Any, setup_integration: Any) -> None:
    """The entities follow an Apple TV whose entity id is changed."""
    await setup_integration()
    er.async_get(hass).async_update_entity(ATV_ENTITY, new_entity_id="media_player.lounge_tv")
    await hass.async_block_till_done(wait_background_tasks=True)
    atv.audio.set_current(("Kitchen", KITCHEN.airplay_id))
    await poll(hass)
    assert hass.states.get(SENSOR).state == "Kitchen"


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
    entry = await setup_integration({CONF_DEFAULT_SPEAKERS: {atv_registry_id(hass): ["Kitchen", LIVING.airplay_id]}})
    atv.audio.set_current(("Living Room", LIVING.airplay_id))
    await poll(hass)
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data["default_speakers"] == {ATV_ENTITY: ["Kitchen", "**REDACTED**"]}
    assert data["apple_tvs"][0]["connected"] is True
    assert data["apple_tvs"][0]["outputs"][0] == {"name": "Living Room", "identifier": "**REDACTED**", **VOLUME}
    assert {"name": "Kitchen", "identifier": "**REDACTED**"} in data["speakers_found"]
    assert data["versions"]["integration"] == "1.2.0"


async def test_default_speakers_no_wait_on_unsupported_version(
    hass: HomeAssistant, atv: Any, setup_integration: Any
) -> None:
    """Only a missing connection is waited for; changed internals are not."""
    hass.states.async_set(ATV_ENTITY, "off")
    await setup_integration({CONF_DEFAULT_SPEAKERS: {atv_registry_id(hass): ["Kitchen"]}})
    hass.config_entries.async_entries("apple_tv")[0].runtime_data = SimpleNamespace(connection=atv)
    attempts = 0
    real_get_apple_tv = defaults.get_apple_tv

    def get_apple_tv(*args: Any, **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        return real_get_apple_tv(*args, **kwargs)

    with patch.object(defaults, "get_apple_tv", get_apple_tv):
        hass.states.async_set(ATV_ENTITY, "idle")
        await hass.async_block_till_done(wait_background_tasks=True)
    assert attempts == 1


async def test_homepod_does_not_reload(hass: HomeAssistant, atv: Any, network: Network, setup_integration: Any) -> None:
    entry = await setup_integration()
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        add_apple_tv(
            hass,
            network,
            "homepod",
            "HomePod",
            "88888888-2222-3333-4444-555555555555",
            "AA:BB:CC:00:00:02",
            model="HomePod mini",
        )
        await hass.async_block_till_done()
    reload.assert_not_called()
    assert entry.state is ConfigEntryState.LOADED


async def test_reload_does_not_scan_again(
    hass: HomeAssistant, atv: Any, network: Network, setup_integration: Any
) -> None:
    entry = await setup_integration()
    assert network.scans == 1
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert network.scans == 1
