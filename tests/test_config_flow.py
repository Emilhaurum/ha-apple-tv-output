"""Tests for setting up the integration."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
import pytest

from custom_components.apple_tv_output.const import DOMAIN


async def test_flow_creates_single_entry(hass: HomeAssistant, mock_async_zeroconf: None) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Apple TV Audio Output"

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_setup_registers_actions(hass: HomeAssistant, mock_async_zeroconf: None) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert set(hass.services.async_services_for_domain(DOMAIN)) == {
        "set_output",
        "add_output",
        "remove_output",
        "get_outputs",
    }


async def test_errors_are_translated(hass: HomeAssistant, mock_async_zeroconf: None) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    hass.states.async_set("media_player.other", "idle")
    with pytest.raises(ServiceValidationError, match=r"^media_player\.other is not an Apple TV media player"):
        await hass.services.async_call(
            DOMAIN, "set_output", {"entity_id": "media_player.other", "speakers": ["Kitchen"]}, blocking=True
        )
