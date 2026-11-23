"""Tests for adding and pairing an Apple TV, and for the actions being registered."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pyatv.const import DeviceModel, Protocol
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.apple_tv_output.const import (
    CONF_ADDRESS,
    CONF_CREDENTIALS,
    CONF_DEFAULT_SPEAKERS,
    CONF_IDENTIFIERS,
    DOMAIN,
)

from .conftest import ATV_AIRPLAY_ID, ATV_MRP_ID, ATV_NAME, PIN, FakeSpeaker, Network

pytestmark = pytest.mark.usefixtures("mock_async_zeroconf")


@pytest.fixture(autouse=True)
def devices(network: Network) -> None:
    network.add(FakeSpeaker("Kitchen", "48:A6:B8:00:00:01"))
    network.add_apple_tv(ATV_NAME, ATV_MRP_ID, ATV_AIRPLAY_ID)
    network.add_apple_tv(
        "HomePod", "88888888-2222-3333-4444-555555555555", "AA:BB:CC:00:00:02", model=DeviceModel.HomePodMini
    )


async def start(hass: HomeAssistant) -> dict[str, Any]:
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})


async def test_pair_apple_tv(hass: HomeAssistant, network: Network) -> None:
    result = await start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    # Only the Apple TV is offered: not the HomePod, nor the speaker.
    options = result["data_schema"].schema["device"].config["options"]
    assert [o["value"] for o in options] == [ATV_MRP_ID]

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": ATV_MRP_ID})
    assert result["step_id"] == "pin"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"pin": "0000"})
    assert result["step_id"] == "pin"
    assert result["errors"] == {"base": "invalid_pin"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"pin": str(PIN)})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == ATV_NAME
    assert result["result"].unique_id == ATV_MRP_ID
    data = result["data"]
    assert data[CONF_ADDRESS] == "10.0.0.10"
    assert set(data[CONF_IDENTIFIERS]) == {ATV_MRP_ID, ATV_AIRPLAY_ID}
    assert list(data[CONF_CREDENTIALS]) == [str(Protocol.AirPlay.value)]

    # The new entry connects with the credentials from pairing.
    await hass.async_block_till_done(wait_background_tasks=True)
    assert result["result"].state is ConfigEntryState.LOADED
    assert network.apple_tvs[0].connection is not None


async def test_already_configured(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=ATV_MRP_ID, data={CONF_IDENTIFIERS: [ATV_MRP_ID]}).add_to_hass(hass)
    result = await start(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_no_devices(hass: HomeAssistant, network: Network) -> None:
    network.apple_tvs.clear()
    result = await start(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_cannot_start_pairing(hass: HomeAssistant) -> None:
    result = await start(hass)
    with patch("tests.conftest.FakePairing.begin", side_effect=OSError("unreachable")):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": ATV_MRP_ID})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_pin_typed_on_device_not_supported(hass: HomeAssistant) -> None:
    result = await start(hass)
    with patch("tests.conftest.FakePairing.begin", _no_pin):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": ATV_MRP_ID})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "pairing_not_supported"


async def _no_pin(handler: Any) -> None:
    handler.device_provides_pin = False


async def test_takes_over_legacy_default_speakers(hass: HomeAssistant) -> None:
    """Default speakers a version 1 entry kept for the Apple TV integration's media player carry over."""
    apple_tv_entry = MockConfigEntry(domain="apple_tv", unique_id=ATV_MRP_ID)
    apple_tv_entry.add_to_hass(hass)
    player = er.async_get(hass).async_get_or_create("media_player", "apple_tv", ATV_MRP_ID, config_entry=apple_tv_entry)
    MockConfigEntry(domain=DOMAIN, data={}, options={CONF_DEFAULT_SPEAKERS: {player.id: ["Kitchen"]}}).add_to_hass(hass)
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": ATV_MRP_ID})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"pin": str(PIN)})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {CONF_DEFAULT_SPEAKERS: ["Kitchen"]}


async def test_reauth(hass: HomeAssistant, network: Network) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=ATV_NAME,
        unique_id=ATV_MRP_ID,
        data={CONF_ADDRESS: "10.0.0.10", CONF_IDENTIFIERS: [ATV_MRP_ID, ATV_AIRPLAY_ID], CONF_CREDENTIALS: {}},
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pin"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"pin": str(PIN)})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert list(entry.data[CONF_CREDENTIALS]) == [str(Protocol.AirPlay.value)]
    # The entry is set up again and connects with the new pairing.
    await hass.async_block_till_done(wait_background_tasks=True)
    assert network.apple_tvs[0].connection is not None


async def test_setup_registers_actions(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert set(hass.services.async_services_for_domain(DOMAIN)) == {
        "set_output",
        "add_output",
        "remove_output",
        "get_outputs",
        "get_speakers",
        "set_volume",
    }


async def test_errors_are_translated(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    hass.states.async_set("media_player.other", "idle")
    with pytest.raises(ServiceValidationError, match=r"^media_player\.other is not an Apple TV paired with"):
        await hass.services.async_call(
            DOMAIN, "set_output", {"entity_id": "media_player.other", "speakers": ["Kitchen"]}, blocking=True
        )
