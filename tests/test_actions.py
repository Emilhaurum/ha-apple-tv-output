"""Tests for the actions and fields added in 1.2.0."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
import pytest

from custom_components.apple_tv_output.const import DOMAIN, ISSUE_UNSUPPORTED_VERSION
from custom_components.apple_tv_output.speakers import async_start_background_scans

from .conftest import ATV_ENTITY, HAS_VOLUME, FakeSpeaker, Network

LIVING = FakeSpeaker("Living Room", "34:7E:5C:D6:4E:1E")
KITCHEN = FakeSpeaker("Kitchen", "48:A6:B8:00:00:01")


@pytest.fixture(autouse=True)
def speakers(network: Network) -> None:
    network.add(LIVING, KITCHEN)


async def call(hass: HomeAssistant, service: str, response: bool = False, **data: Any) -> Any:
    data.setdefault("entity_id", ATV_ENTITY)
    return await hass.services.async_call(DOMAIN, service, data, blocking=True, return_response=response)


async def test_get_speakers(hass: HomeAssistant, atv: Any, network: Network) -> None:
    result = await hass.services.async_call(DOMAIN, "get_speakers", {}, blocking=True, return_response=True)
    assert result == {
        "speakers": [
            {"name": "Kitchen", "identifier": KITCHEN.airplay_id},
            {"name": "Living Room", "identifier": LIVING.airplay_id},
        ]
    }
    assert network.scans == 1
    # Uses the recent scan, unless asked to scan again.
    await hass.services.async_call(DOMAIN, "get_speakers", {}, blocking=True, return_response=True)
    assert network.scans == 1
    await hass.services.async_call(DOMAIN, "get_speakers", {"rescan": True}, blocking=True, return_response=True)
    assert network.scans == 2


async def test_modify_returns_previous_and_new_outputs(hass: HomeAssistant, atv: Any) -> None:
    atv.audio.set_current(("Living Room", LIVING.airplay_id))
    result = await call(hass, "set_output", response=True, speakers=["Kitchen"])
    entry = result[ATV_ENTITY]
    assert [o["name"] for o in entry["previous_outputs"]] == ["Living Room"]
    assert [o["name"] for o in entry["outputs"]] == ["Kitchen"]
    # Without response_variable the call still works.
    assert await call(hass, "remove_output", speakers=["Kitchen"]) is None


async def test_retries(hass: HomeAssistant, atv: Any) -> None:
    """The Apple TV ignores the first two commands, as right after waking up."""
    atv.audio.ignore = 2
    await call(hass, "set_output", speakers=[LIVING.airplay_id], retries=3)
    assert atv.audio.calls == [("set", (LIVING.airplay_id,))] * 3
    assert [d.name for d in atv.audio.output_devices] == ["Living Room"]


async def test_retries_add_only_missing(hass: HomeAssistant, atv: Any) -> None:
    atv.audio.set_current(("Living Room", LIVING.airplay_id))
    atv.audio.ignore = 1
    await call(hass, "add_output", speakers=[LIVING.airplay_id, KITCHEN.airplay_id], force=True, retries=1)
    assert atv.audio.calls[-1] == ("add", (KITCHEN.airplay_id,))


async def test_no_retries_by_default(hass: HomeAssistant, atv: Any) -> None:
    atv.audio.ignore = 1
    await call(hass, "set_output", speakers=[LIVING.airplay_id])
    assert len(atv.audio.calls) == 1


async def test_fail_if_not_applied(hass: HomeAssistant, atv: Any, caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, "set_output", speakers=["00:11:22:33:44:55"], fail_if_not_applied=True)
    assert err.value.translation_key == "not_applied"
    assert err.value.translation_placeholders["speakers"] == "00:11:22:33:44:55"
    assert "did not report" not in caplog.text


async def test_set_volume(hass: HomeAssistant, atv: Any) -> None:
    atv.audio.set_current(("Living Room", LIVING.airplay_id))
    await call(hass, "set_volume", speaker="Living Room", volume_level=0.3)
    assert atv.audio.volumes == [(30.0, LIVING.airplay_id)]


async def test_set_volume_speaker_not_output(hass: HomeAssistant, atv: Any) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "set_volume", speaker="Kitchen", volume_level=0.3)
    assert err.value.translation_key == "speaker_not_output"


async def test_set_volume_not_supported(hass: HomeAssistant, atv: Any) -> None:
    """Older pyatv (Home Assistant 2025.1) cannot set the volume of one output."""

    async def set_volume(level: float) -> None:
        raise AssertionError

    atv.audio.set_volume = set_volume
    atv.audio.set_current(("Living Room", LIVING.airplay_id))
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, "set_volume", speaker="Living Room", volume_level=0.3)
    assert err.value.translation_key == "volume_not_supported"


def add_speaker_entity(hass: HomeAssistant, entity_id: str, name: str, mac: str | None) -> None:
    """Add a speaker's media player the way an integration such as Sonos registers it."""
    entry = hass.config_entries.async_entries("apple_tv")[0]
    connections = {(dr.CONNECTION_NETWORK_MAC, mac)} if mac else set()
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("sonos", entity_id)}, connections=connections
    )
    er.async_get(hass).async_get_or_create(
        "media_player", "sonos", entity_id, suggested_object_id=entity_id.split(".")[1], device_id=device.id
    )
    hass.states.async_set(entity_id, "idle", {"friendly_name": name})


async def test_speaker_entity_by_address(hass: HomeAssistant, atv: Any, network: Network) -> None:
    """The entity's name differs from the AirPlay name; its MAC address is used, with no scan."""
    add_speaker_entity(hass, "media_player.kitchen_sonos", "Kitchen Sonos", KITCHEN.airplay_id.lower())
    await call(hass, "set_output", speakers=["media_player.kitchen_sonos"])
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]
    assert network.scans == 0


async def test_speaker_entity_address_falls_back_to_name(hass: HomeAssistant, atv: Any, network: Network) -> None:
    """The registered address is not the AirPlay id: the entity's name is tried instead."""
    add_speaker_entity(hass, "media_player.kitchen", "Kitchen", "AA:AA:AA:AA:AA:AA")
    await call(hass, "set_output", speakers=["media_player.kitchen"])
    assert atv.audio.calls == [("set", ("AA:AA:AA:AA:AA:AA",)), ("set", (KITCHEN.airplay_id,))]
    assert [d.name for d in atv.audio.output_devices] == ["Kitchen"]


async def test_background_scans(hass: HomeAssistant, atv: Any, network: Network) -> None:
    unsubscribe = async_start_background_scans(hass)
    await hass.async_block_till_done()
    assert network.scans == 1
    # A call by name now needs no scan of its own.
    await call(hass, "set_output", speakers=["Kitchen"])
    assert network.scans == 1
    unsubscribe()


async def test_repairs_issue(hass: HomeAssistant, atv: Any, entity_component: dict[str, Any]) -> None:
    entry = hass.config_entries.async_entries("apple_tv")[0]
    entry.runtime_data = SimpleNamespace(connection=atv)
    entity_component[ATV_ENTITY] = SimpleNamespace(connection=atv)
    with pytest.raises(HomeAssistantError):
        await call(hass, "get_outputs", response=True)
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, ISSUE_UNSUPPORTED_VERSION) is not None

    # Fixed by an update: the issue goes away on the next successful lookup.
    entry.runtime_data = SimpleNamespace(atv=atv)
    entity_component.clear()
    await call(hass, "get_outputs", response=True)
    assert issues.async_get_issue(DOMAIN, ISSUE_UNSUPPORTED_VERSION) is None


async def test_speaker_entity_known_name_skips_wrong_address(hass: HomeAssistant, atv: Any, network: Network) -> None:
    """The scan knows the entity's name and its address is not an AirPlay id: no wrong command is sent."""
    await hass.services.async_call(DOMAIN, "get_speakers", {}, blocking=True, return_response=True)
    add_speaker_entity(hass, "media_player.kitchen", "Kitchen", "AA:AA:AA:AA:AA:AA")
    await call(hass, "set_output", speakers=["media_player.kitchen"])
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]


async def test_remove_speaker_entity_with_wrong_address(hass: HomeAssistant, atv: Any) -> None:
    add_speaker_entity(hass, "media_player.kitchen", "Kitchen", "AA:AA:AA:AA:AA:AA")
    atv.audio.set_current(("Kitchen", KITCHEN.airplay_id))
    await call(hass, "remove_output", speakers=["media_player.kitchen"])
    assert atv.audio.calls == [("remove", (KITCHEN.airplay_id,))]


async def test_set_volume_speaker_entity_with_wrong_address(hass: HomeAssistant, atv: Any) -> None:
    add_speaker_entity(hass, "media_player.kitchen", "Kitchen", "AA:AA:AA:AA:AA:AA")
    atv.audio.set_current(("Kitchen", KITCHEN.airplay_id))
    await call(hass, "set_volume", speaker="media_player.kitchen", volume_level=0.5)
    assert atv.audio.volumes == [(50.0, KITCHEN.airplay_id)]


@pytest.mark.skipif(not HAS_VOLUME, reason="older pyatv has no volume per output")
async def test_get_outputs_volume(hass: HomeAssistant, atv: Any) -> None:
    """A reported volume is shown; 0, which also means "not reported yet", is left out."""
    atv.audio.set_current(("Living Room", LIVING.airplay_id), ("Kitchen", KITCHEN.airplay_id))
    atv.audio.output_devices[0].volume = 35.0
    result = await call(hass, "get_outputs", response=True)
    assert result[ATV_ENTITY]["outputs"] == [
        {"name": "Living Room", "identifier": LIVING.airplay_id, "volume_level": 0.35},
        {"name": "Kitchen", "identifier": KITCHEN.airplay_id},
    ]
