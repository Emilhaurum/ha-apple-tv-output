"""Tests for the actions."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest

from custom_components.apple_tv_output import services
from custom_components.apple_tv_output.const import CACHE_TTL, DOMAIN

from .conftest import ATV_AIRPLAY_ID, ATV_ENTITY, ATV_NAME, FakeSpeaker, Network, add_apple_tv

LIVING = FakeSpeaker("Living Room", "34:7E:5C:D6:4E:1E")
KITCHEN = FakeSpeaker("Kitchen", "48:A6:B8:00:00:01")
HOMEPOD = FakeSpeaker("Bedroom", "F0:B3:EC:00:00:02", mrp_id="6C8E1B0A-1111-2222-3333-444444444444")


async def call(hass: HomeAssistant, service: str, **data: Any) -> Any:
    data.setdefault("entity_id", ATV_ENTITY)
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=service == "get_outputs"
    )


@pytest.fixture(autouse=True)
def speakers(network: Network) -> None:
    network.add(LIVING, KITCHEN, HOMEPOD)


async def test_set_output_by_name(hass: HomeAssistant, atv: Any) -> None:
    await call(hass, "set_output", speakers=["living room"])
    assert atv.audio.calls == [("set", (LIVING.airplay_id,))]


async def test_set_output_uses_airplay_id_not_mrp_id(hass: HomeAssistant, atv: Any) -> None:
    """A HomePod's main pyatv id is its MRP id; the outputs need the AirPlay one."""
    await call(hass, "set_output", speakers=["Bedroom"])
    assert atv.audio.calls == [("set", (HOMEPOD.airplay_id,))]


async def test_set_output_skips_when_already_only_output(hass: HomeAssistant, atv: Any) -> None:
    atv.audio.set_current(("Living Room", LIVING.airplay_id))
    await call(hass, "set_output", speakers=["Living Room"])
    assert atv.audio.calls == []


async def test_set_output_ignores_the_apple_tv_itself(hass: HomeAssistant, atv: Any) -> None:
    atv.audio.set_current((ATV_NAME, ATV_AIRPLAY_ID), ("Living Room", LIVING.airplay_id))
    await call(hass, "set_output", speakers=["Living Room"])
    assert atv.audio.calls == []


async def test_set_output_sends_when_other_speakers_play(hass: HomeAssistant, atv: Any) -> None:
    """Living Room is an output, but so is Kitchen: set_output must drop Kitchen."""
    atv.audio.set_current(("Living Room", LIVING.airplay_id), ("Kitchen", KITCHEN.airplay_id))
    await call(hass, "set_output", speakers=["Living Room"])
    assert atv.audio.calls == [("set", (LIVING.airplay_id,))]
    assert [d.name for d in atv.audio.output_devices] == ["Living Room"]


async def test_force(hass: HomeAssistant, atv: Any) -> None:
    atv.audio.set_current(("Living Room", LIVING.airplay_id))
    await call(hass, "set_output", speakers=["Living Room"], force=True)
    assert atv.audio.calls == [("set", (LIVING.airplay_id,))]


@pytest.mark.parametrize("written", ["347e5cd64e1e", "34-7E-5C-D6-4E-1E", "34:7e:5c:d6:4e:1e"])
async def test_id_written_differently(hass: HomeAssistant, atv: Any, network: Network, written: str) -> None:
    atv.audio.set_current(("Living Room", LIVING.airplay_id))
    await call(hass, "set_output", speakers=[written])
    assert atv.audio.calls == []
    await call(hass, "set_output", speakers=[written], force=True)
    assert atv.audio.calls == [("set", (LIVING.airplay_id,))]
    assert network.scans == 0


async def test_speaker_from_media_player_entity(hass: HomeAssistant, atv: Any) -> None:
    hass.states.async_set("media_player.kitchen", "idle", {"friendly_name": "Kitchen"})
    await call(hass, "set_output", speakers=["media_player.kitchen"])
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]


async def test_unknown_speaker_entity(hass: HomeAssistant, atv: Any) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "set_output", speakers=["media_player.nope"])
    assert err.value.translation_key == "unknown_speaker_entity"


async def test_add_output(hass: HomeAssistant, atv: Any) -> None:
    atv.audio.set_current(("Living Room", LIVING.airplay_id))
    await call(hass, "add_output", speakers=["Living Room"])
    assert atv.audio.calls == []
    await call(hass, "add_output", speakers=["Kitchen"])
    assert atv.audio.calls == [("add", (KITCHEN.airplay_id,))]
    assert {d.name for d in atv.audio.output_devices} == {"Living Room", "Kitchen"}


async def test_remove_output(hass: HomeAssistant, atv: Any) -> None:
    atv.audio.set_current(("Living Room", LIVING.airplay_id), ("Kitchen", KITCHEN.airplay_id))
    await call(hass, "remove_output", speakers=["347e5cd64e1e", "Bedroom"])
    # Sent as the Apple TV reports it, and only the speaker that is an output.
    assert atv.audio.calls == [("remove", (LIVING.airplay_id,))]
    await call(hass, "remove_output", speakers=["Bedroom"])
    assert len(atv.audio.calls) == 1


async def test_get_outputs(hass: HomeAssistant, atv: Any) -> None:
    atv.audio.set_current(("Living Room", LIVING.airplay_id))
    result = await call(hass, "get_outputs")
    assert result == {ATV_ENTITY: {"outputs": [{"name": "Living Room", "identifier": LIVING.airplay_id}]}}


async def test_speaker_not_found(hass: HomeAssistant, atv: Any) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "set_output", speakers=["Garage"])
    assert err.value.translation_key == "speaker_not_found"
    assert err.value.translation_placeholders["found"] == "Bedroom, Kitchen, Living Room"


async def test_speaker_ambiguous(hass: HomeAssistant, atv: Any, network: Network) -> None:
    network.add(FakeSpeaker("Kitchen", "48:A6:B8:00:00:09"))
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "set_output", speakers=["Kitchen"])
    assert err.value.translation_key == "speaker_ambiguous"
    assert "48:A6:B8:00:00:09" in err.value.translation_placeholders["ids"]
    assert atv.audio.calls == []


async def test_names_are_cached(
    hass: HomeAssistant, atv: Any, network: Network, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 1000.0
    monkeypatch.setattr(services.time, "monotonic", lambda: now)
    await call(hass, "set_output", speakers=["Living Room"])
    await call(hass, "set_output", speakers=["Kitchen"])
    assert network.scans == 1
    now += CACHE_TTL + 1
    await call(hass, "set_output", speakers=["Living Room"])
    assert network.scans == 2


async def test_unknown_name_scans_again(hass: HomeAssistant, atv: Any, network: Network) -> None:
    await call(hass, "set_output", speakers=["Living Room"])
    network.add(FakeSpeaker("Office", "48:A6:B8:00:00:05"))
    await call(hass, "set_output", speakers=["Office"])
    assert network.scans == 2
    assert atv.audio.calls[-1] == ("set", ("48:A6:B8:00:00:05",))


async def test_stale_name_scans_again_and_retries(hass: HomeAssistant, atv: Any, network: Network) -> None:
    """The cached id no longer leads to the speaker: scan again and resend with the new id."""
    await call(hass, "set_output", speakers=["Kitchen"])
    network.speakers.remove(KITCHEN)
    network.add(FakeSpeaker("Kitchen", "48:A6:B8:00:00:07"))
    await call(hass, "set_output", speakers=["Kitchen", "Living Room"])
    assert network.scans == 2
    assert atv.audio.calls[1:] == [
        ("set", (KITCHEN.airplay_id, LIVING.airplay_id)),
        ("set", ("48:A6:B8:00:00:07", LIVING.airplay_id)),
    ]
    assert {d.identifier for d in atv.audio.output_devices} == {"48:A6:B8:00:00:07", LIVING.airplay_id}


async def test_unreachable_speaker_warns(
    hass: HomeAssistant, atv: Any, network: Network, caplog: pytest.LogCaptureFixture
) -> None:
    await call(hass, "set_output", speakers=["00:11:22:33:44:55"])
    assert "did not report 00:11:22:33:44:55 as an output" in caplog.text
    assert network.scans == 0


async def test_command_failed(hass: HomeAssistant, atv: Any) -> None:
    atv.audio.fail = OSError("boom")
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, "set_output", speakers=[LIVING.airplay_id])
    assert err.value.translation_key == "command_failed"
    assert err.value.translation_placeholders["error"] == "boom"


async def test_not_an_apple_tv(hass: HomeAssistant, atv: Any, network: Network) -> None:
    hass.states.async_set("media_player.other", "idle")
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "set_output", entity_id=[ATV_ENTITY, "media_player.other"], speakers=["Living Room"])
    assert err.value.translation_key == "not_apple_tv"
    # Checked before anything is changed, and before scanning.
    assert atv.audio.calls == []
    assert network.scans == 0


async def test_not_connected(hass: HomeAssistant, atv: Any) -> None:
    entry = hass.config_entries.async_entries("apple_tv")[0]
    entry.runtime_data = SimpleNamespace(atv=None)
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, "get_outputs")
    assert err.value.translation_key == "not_connected"


async def test_connection_from_entity(hass: HomeAssistant, atv: Any, entity_component: dict[str, Any]) -> None:
    entry = hass.config_entries.async_entries("apple_tv")[0]
    entry.runtime_data = SimpleNamespace(atv=None)
    entity_component[ATV_ENTITY] = SimpleNamespace(atv=atv)
    await call(hass, "set_output", speakers=[LIVING.airplay_id])
    assert atv.audio.calls == [("set", (LIVING.airplay_id,))]


async def test_internals_changed(
    hass: HomeAssistant, atv: Any, entity_component: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    entry = hass.config_entries.async_entries("apple_tv")[0]
    entry.runtime_data = SimpleNamespace(connection=atv)
    entity_component[ATV_ENTITY] = SimpleNamespace(connection=atv)
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, "get_outputs")
    assert err.value.translation_key == "unsupported_version"
    assert "no longer exposes its pyatv connection" in caplog.text


async def test_target_device_keeps_only_apple_tvs(hass: HomeAssistant, atv: Any, network: Network) -> None:
    """A device or area can bring in other entities; only the Apple TV media players are used."""
    entry = hass.config_entries.async_entries("apple_tv")[0]
    device = dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, identifiers={("apple_tv", "x")})
    registry = er.async_get(hass)
    registry.async_update_entity(ATV_ENTITY, device_id=device.id)
    other = registry.async_get_or_create("remote", "apple_tv", "remote-1", config_entry=entry, device_id=device.id)
    hass.states.async_set(ATV_ENTITY, "idle")
    hass.states.async_set(other.entity_id, "on")
    await hass.services.async_call(
        DOMAIN, "set_output", {"device_id": device.id, "speakers": ["Kitchen"]}, blocking=True
    )
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]


async def test_several_apple_tvs(hass: HomeAssistant, atv: Any, network: Network) -> None:
    other, _ = add_apple_tv(
        hass, network, "bedroom_tv", "Bedroom TV", "99999999-2222-3333-4444-555555555555", "AA:BB:CC:00:00:01"
    )
    await call(hass, "set_output", entity_id=[ATV_ENTITY, "media_player.bedroom_tv"], speakers=["Kitchen"])
    assert atv.audio.calls == other.audio.calls == [("set", (KITCHEN.airplay_id,))]
    assert network.scans == 1


async def test_no_target(hass: HomeAssistant, atv: Any) -> None:
    hass.states.async_set("light.lamp", "on")
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "set_output", {"area_id": "nowhere", "speakers": ["Kitchen"]}, blocking=True
        )
    assert err.value.translation_key == "no_apple_tv"


async def test_speaker_gone_on_rescan(
    hass: HomeAssistant, atv: Any, network: Network, caplog: pytest.LogCaptureFixture
) -> None:
    """The command was sent; a speaker that has vanished since is reported, not raised."""
    await call(hass, "set_output", speakers=["Kitchen"])
    network.speakers.remove(KITCHEN)
    await call(hass, "set_output", speakers=["Kitchen", "Living Room"], force=True)
    assert network.scans == 2
    assert "did not report Kitchen as an output" in caplog.text


async def test_known_id_sends_airplay_id(hass: HomeAssistant, atv: Any) -> None:
    """A HomePod given by its MRP id (or in lower case) is sent its AirPlay id."""
    await call(hass, "set_output", speakers=["Bedroom"])
    await call(hass, "set_output", speakers=[HOMEPOD.mrp_id.lower()], force=True)
    assert atv.audio.calls[-1] == ("set", (HOMEPOD.airplay_id,))


async def test_entity_id_all(hass: HomeAssistant, atv: Any, network: Network) -> None:
    other, entry = add_apple_tv(
        hass, network, "bedroom_tv", "Bedroom TV", "99999999-2222-3333-4444-555555555555", "AA:BB:CC:00:00:01"
    )
    entry.runtime_data = SimpleNamespace(atv=None)  # not connected: skipped
    await call(hass, "set_output", entity_id="all", speakers=["Kitchen"])
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]
    assert other.audio.calls == []


async def test_area_skips_homepods_and_unconnected(hass: HomeAssistant, atv: Any, network: Network) -> None:
    """An area brings in a HomePod's media player and an Apple TV that is off: both are skipped."""
    area = "living_room"
    devices, entities = dr.async_get(hass), er.async_get(hass)
    homepod, homepod_entry = add_apple_tv(
        hass, network, "homepod", "HomePod", "88888888-2222-3333-4444-555555555555", "AA:BB:CC:00:00:02"
    )
    off, off_entry = add_apple_tv(
        hass, network, "den_tv", "Den TV", "77777777-2222-3333-4444-555555555555", "AA:BB:CC:00:00:03"
    )
    off_entry.runtime_data = SimpleNamespace(atv=None)
    for entity_id, entry, model in [
        (ATV_ENTITY, hass.config_entries.async_entries("apple_tv")[0], "Apple TV 4K"),
        ("media_player.homepod", homepod_entry, "HomePod Mini"),
        ("media_player.den_tv", off_entry, "Apple TV 4K"),
    ]:
        device = devices.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={("apple_tv", entity_id)}, model=model
        )
        devices.async_update_device(device.id, area_id=area)
        entities.async_update_entity(entity_id, device_id=device.id)
    await hass.services.async_call(DOMAIN, "set_output", {"area_id": area, "speakers": ["Kitchen"]}, blocking=True)
    assert atv.audio.calls == [("set", (KITCHEN.airplay_id,))]
    assert homepod.audio.calls == off.audio.calls == []


async def test_scan_keeps_speakers_that_miss_a_scan(hass: HomeAssistant, atv: Any, network: Network) -> None:
    await call(hass, "set_output", speakers=["Living Room"])
    network.speakers.remove(LIVING)  # asleep during the next scan
    with pytest.raises(ServiceValidationError):
        await call(hass, "set_output", speakers=["Kitchn"])
    assert network.scans == 2
    await call(hass, "set_output", speakers=["Kitchen", "Living Room"])
    assert atv.audio.calls[-1] == ("set", (KITCHEN.airplay_id, LIVING.airplay_id))


async def test_rescan_forgets_renamed_speaker(hass: HomeAssistant, atv: Any, network: Network) -> None:
    await call(hass, "set_output", speakers=["Kitchen"])
    network.speakers.remove(KITCHEN)
    network.add(FakeSpeaker("Dining Room", KITCHEN.airplay_id))
    await call(hass, "set_output", speakers=["Dining Room"])
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "set_output", speakers=["Kitchen"])
    assert "Kitchen" not in err.value.translation_placeholders["found"]


async def test_waits_for_late_outputs(
    hass: HomeAssistant, atv: Any, network: Network, caplog: pytest.LogCaptureFixture
) -> None:
    """The Apple TV reports the new outputs a moment later: no rescan, no warning."""
    await call(hass, "set_output", speakers=["Kitchen"])
    atv.audio.lag = 0.3
    with patch("custom_components.apple_tv_output.services.OUTPUT_SETTLE_TIME", 2):
        await call(hass, "set_output", speakers=["Living Room"])
    assert network.scans == 1
    assert "did not report" not in caplog.text


async def test_add_output_rescan_resends_only_changed(hass: HomeAssistant, atv: Any, network: Network) -> None:
    await call(hass, "set_output", speakers=["Kitchen"])
    atv.audio.set_current()
    network.speakers.remove(KITCHEN)
    network.add(FakeSpeaker("Kitchen", "48:A6:B8:00:00:07"))
    await call(hass, "add_output", speakers=["Kitchen", "Living Room"])
    assert atv.audio.calls[1:] == [
        ("add", (KITCHEN.airplay_id, LIVING.airplay_id)),
        ("add", ("48:A6:B8:00:00:07",)),
    ]


async def test_rescan_error_is_contained(
    hass: HomeAssistant, atv: Any, network: Network, caplog: pytest.LogCaptureFixture
) -> None:
    """The command was sent: a failing rescan must not turn the call into an error."""
    await call(hass, "set_output", speakers=["Kitchen"])
    network.speakers.remove(KITCHEN)
    network.scan_error = OSError("mDNS down")
    await call(hass, "set_output", speakers=["Kitchen"], force=True)
    assert "did not report Kitchen as an output" in caplog.text


async def test_concurrent_calls_share_one_scan(hass: HomeAssistant, atv: Any, network: Network) -> None:
    network.scan_delay = 0.1
    await asyncio.gather(
        call(hass, "set_output", speakers=["Kitchen"]),
        call(hass, "add_output", speakers=["Living Room"]),
    )
    assert network.scans == 1
