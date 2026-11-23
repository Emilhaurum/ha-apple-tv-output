"""Tests for a paired Apple TV's entry: connection, entities, default speakers, options and diagnostics."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.apple_tv_output.const import (
    CONF_ADDRESS,
    CONF_DEFAULT_SPEAKERS,
    DOMAIN,
    ISSUE_LEGACY_ENTRY,
)
from custom_components.apple_tv_output.diagnostics import async_get_config_entry_diagnostics

from .conftest import ATV_NAME, FakeSpeaker, Network

LIVING = FakeSpeaker("Living Room", "34:7E:5C:D6:4E:1E")
KITCHEN = FakeSpeaker("Kitchen", "48:A6:B8:00:00:01")
SENSOR = "sensor.living_room_tv_audio_outputs"
SELECT = "select.living_room_tv_audio_output"
DEFAULTS = {CONF_DEFAULT_SPEAKERS: ["Kitchen"]}


@pytest.fixture(autouse=True)
def speakers(network: Network) -> None:
    network.add(LIVING, KITCHEN)


async def reconnected(hass: HomeAssistant) -> None:
    """Let the connection's background reconnect run."""
    for _ in range(20):
        await asyncio.sleep(0.02)
    await hass.async_block_till_done()


# Entities


async def test_sensor(hass: HomeAssistant, setup_integration: Any) -> None:
    atv, _ = await setup_integration()
    atv.audio.set_current((ATV_NAME, "AA:BB:CC:DD:EE:FF"), ("Living Room", LIVING.airplay_id))
    await hass.async_block_till_done()
    state = hass.states.get(SENSOR)
    assert state.state == f"{ATV_NAME}, Living Room"
    assert state.attributes["speakers"] == ["Living Room"]
    assert [o["identifier"] for o in state.attributes["outputs"]] == ["AA:BB:CC:DD:EE:FF", LIVING.airplay_id]

    # Gone from the network: unavailable.
    atv.online = False
    atv.lose_connection()
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == STATE_UNAVAILABLE


async def test_entities_device(hass: HomeAssistant, setup_integration: Any) -> None:
    _, entry = await setup_integration()
    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert device.name == ATV_NAME
    assert device.manufacturer == "Apple"


async def test_select(hass: HomeAssistant, setup_integration: Any) -> None:
    atv, _ = await setup_integration()
    state = hass.states.get(SELECT)
    # The background scan found the speakers, and the Apple TV itself.
    assert state.attributes["options"] == ["Kitchen", "Living Room", ATV_NAME]
    assert state.state == "unknown"

    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "Kitchen"}, blocking=True)
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]
    assert hass.states.get(SELECT).state == "Kitchen"

    # Several speakers: nothing selected.
    atv.audio.set_current(("Kitchen", KITCHEN.airplay_id), ("Living Room", LIVING.airplay_id))
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "unknown"


# Connection


async def test_reconnects(hass: HomeAssistant, setup_integration: Any) -> None:
    atv, _ = await setup_integration()
    atv.lose_connection()
    await hass.async_block_till_done()
    await reconnected(hass)
    assert atv.connection is not None
    assert hass.states.get(SENSOR).state != STATE_UNAVAILABLE


async def test_address_change_saved_without_reload(hass: HomeAssistant, setup_integration: Any) -> None:
    atv, entry = await setup_integration()
    connection = entry.runtime_data
    atv.lose_connection()
    atv.address = "10.0.0.99"
    await reconnected(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data[CONF_ADDRESS] == "10.0.0.99"
    # Not set up again: the same connection is still in use.
    assert entry.runtime_data is connection
    assert atv.connection is not None


async def test_rejected_pairing_asks_to_pair_again(hass: HomeAssistant, setup_integration: Any) -> None:
    atv, entry = await setup_integration()
    atv.accepted = {next(iter(atv.accepted)): "something else"}  # pairing removed on the Apple TV
    atv.lose_connection()
    await reconnected(hass)
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]
    assert flows[0]["context"]["entry_id"] == entry.entry_id


async def test_unload_closes_connection(hass: HomeAssistant, setup_integration: Any) -> None:
    atv, entry = await setup_integration()
    connection = atv.connection
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert connection.closed


# Default speakers


async def test_default_speakers_on_wake(hass: HomeAssistant, setup_integration: Any) -> None:
    atv, _ = await setup_integration(DEFAULTS)
    assert atv.audio.calls == []  # already on at setup: left alone
    atv.set_power(False)
    atv.set_power(True)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]


async def test_default_speakers_after_sleep_dropped_connection(hass: HomeAssistant, setup_integration: Any) -> None:
    """The Apple TV goes off and drops the connection while asleep; reconnecting to it on is a wake-up."""
    atv, _ = await setup_integration(DEFAULTS)
    atv.set_power(False)
    atv.lose_connection()
    atv.power = atv.power.__class__.On
    await reconnected(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]


async def test_default_speakers_not_applied_after_short_glitch(hass: HomeAssistant, setup_integration: Any) -> None:
    """The connection drops for a moment while the Apple TV stays on: not a wake-up."""
    atv, _ = await setup_integration(DEFAULTS)
    atv.lose_connection()
    await reconnected(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert atv.audio.calls == []


async def test_default_speakers_after_long_outage(hass: HomeAssistant, setup_integration: Any) -> None:
    """Gone long enough to have slept without saying so: a wake-up."""
    atv, _ = await setup_integration(DEFAULTS)
    with patch("custom_components.apple_tv_output.const.WAKE_AFTER_OUTAGE", 0):
        atv.lose_connection()
        await reconnected(hass)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]


async def test_hand_picked_speaker_stays(hass: HomeAssistant, setup_integration: Any) -> None:
    atv, _ = await setup_integration(DEFAULTS)
    atv.set_power(False)
    atv.set_power(True)
    await hass.async_block_till_done(wait_background_tasks=True)
    atv.audio.set_current(("Living Room", LIVING.airplay_id))  # picked by hand
    atv.set_power(True)  # power reported again while on: not a wake-up
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(atv.audio.calls) == 1
    assert [d.name for d in atv.audio.output_devices] == ["Living Room"]


async def test_default_speakers_not_applied_on_reload(hass: HomeAssistant, setup_integration: Any) -> None:
    atv, entry = await setup_integration(DEFAULTS)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert atv.audio.calls == []


async def test_changed_default_speakers_applied_at_once(hass: HomeAssistant, setup_integration: Any) -> None:
    atv, entry = await setup_integration()
    hass.config_entries.async_update_entry(entry, options=DEFAULTS)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]


async def test_default_speakers_retry(hass: HomeAssistant, setup_integration: Any) -> None:
    """Right after waking, the Apple TV ignores the first command."""
    atv, _ = await setup_integration(DEFAULTS)
    atv.audio.ignore = 1
    atv.set_power(False)
    atv.set_power(True)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))] * 2
    assert [d.name for d in atv.audio.output_devices] == ["Kitchen"]


async def test_default_speakers_error_logged_once(
    hass: HomeAssistant, setup_integration: Any, caplog: pytest.LogCaptureFixture
) -> None:
    atv, _ = await setup_integration({CONF_DEFAULT_SPEAKERS: ["Garage"]})
    atv.set_power(False)
    atv.set_power(True)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert caplog.text.count(f"Could not send {ATV_NAME} to its default speakers") == 1
    assert atv.audio.calls == []


# Options


async def test_options_flow(hass: HomeAssistant, setup_integration: Any) -> None:
    _, entry = await setup_integration()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"speakers": ["Kitchen"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == DEFAULTS
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"speakers": []})
    assert entry.options == {CONF_DEFAULT_SPEAKERS: []}


# Upgrading from version 1


async def test_legacy_entry(hass: HomeAssistant, mock_async_zeroconf: None) -> None:
    """A version 1 entry does nothing, raises a repair notice, and the notice goes with the entry."""
    legacy = MockConfigEntry(domain=DOMAIN, title="Apple TV Audio Output", data={})
    legacy.add_to_hass(hass)
    assert await hass.config_entries.async_setup(legacy.entry_id)
    await hass.async_block_till_done()
    assert legacy.state is ConfigEntryState.LOADED
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_LEGACY_ENTRY) is not None

    result = await hass.config_entries.options.async_init(legacy.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "legacy_entry"

    assert await hass.config_entries.async_remove(legacy.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_LEGACY_ENTRY) is None


# Diagnostics


async def test_diagnostics(hass: HomeAssistant, setup_integration: Any) -> None:
    atv, entry = await setup_integration({CONF_DEFAULT_SPEAKERS: ["Kitchen", LIVING.airplay_id]})
    atv.audio.set_current(("Living Room", LIVING.airplay_id))
    await hass.async_block_till_done()
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data["default_speakers"] == ["Kitchen", "**REDACTED**"]
    assert data["connected"] is True
    assert data["outputs"] == [{"name": "Living Room", "identifier": "**REDACTED**"}]
    assert data["entry"]["data"] == {
        "address": "**REDACTED**",
        "identifiers": "**REDACTED**",
        "credentials": "**REDACTED**",
    }
    assert {"name": "Kitchen", "identifier": "**REDACTED**"} in data["speakers_found"]
    # The pairing credentials (the fake ones are the text "paired") never appear.
    assert '"paired"' not in json.dumps(data)
    manifest = json.loads(
        (Path(__file__).parent.parent / "custom_components/apple_tv_output/manifest.json").read_text()
    )
    assert data["versions"]["integration"] == manifest["version"]
