"""Fixtures: a fake Apple TV, a fake network of AirPlay speakers, and the actions registered."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.components.media_player import DATA_COMPONENT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pyatv.const import Protocol
from pyatv.interface import OutputDevice
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.apple_tv_output.const import DOMAIN
from custom_components.apple_tv_output.services import async_setup_services

ATV_ENTITY = "media_player.living_room_tv"
# Older pyatv (Home Assistant 2025.1) has no volume per output.
VOLUME: dict[str, float] = {"volume_level": 0.0} if hasattr(OutputDevice(name="x", identifier="x"), "volume") else {}
ATV_NAME = "Living Room TV"
ATV_MRP_ID = "11111111-2222-3333-4444-555555555555"
ATV_AIRPLAY_ID = "AA:BB:CC:DD:EE:FF"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components."""


@pytest.fixture(autouse=True)
def no_settle_time():
    """Do not wait for outputs that will never come, unless a test asks for it."""
    with (
        patch("custom_components.apple_tv_output.const.OUTPUT_SETTLE_TIME", 0),
        patch("custom_components.apple_tv_output.const.RETRY_DELAY", 0),
    ):
        yield


@dataclass
class FakeSpeaker:
    """An AirPlay speaker on the fake network."""

    name: str
    airplay_id: str
    mrp_id: str | None = None

    def conf(self) -> Any:
        """Return what pyatv.scan would report for this speaker."""
        services = {Protocol.AirPlay: SimpleNamespace(identifier=self.airplay_id)}
        if self.mrp_id:
            services[Protocol.MRP] = SimpleNamespace(identifier=self.mrp_id)
        return SimpleNamespace(
            name=self.name,
            # Like pyatv: MRP first when there is one.
            identifier=self.mrp_id or self.airplay_id,
            all_identifiers=[s.identifier for s in services.values()],
            get_service=services.get,
        )


@dataclass
class Network:
    """The speakers a scan finds, and the ones the Apple TV can actually reach."""

    speakers: list[FakeSpeaker] = field(default_factory=list)
    scans: int = 0
    scan_delay: float = 0
    scan_error: Exception | None = None

    def add(self, *speakers: FakeSpeaker) -> None:
        self.speakers.extend(speakers)

    def by_id(self, identifier: str) -> FakeSpeaker | None:
        return next((s for s in self.speakers if s.airplay_id == identifier), None)


class FakeAudio:
    """pyatv's audio interface: changes the outputs when given ids of reachable speakers."""

    def __init__(self, network: Network) -> None:
        self.network = network
        self.output_devices: list[OutputDevice] = []
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.fail: Exception | None = None
        # Seconds before a change shows up in output_devices, as on a real Apple TV.
        self.lag: float = 0
        # Commands to ignore before obeying, like an Apple TV that has only just woken up.
        self.ignore: int = 0
        self.volumes: list[tuple[float, str | None]] = []

    def _apply(self, devices: list[OutputDevice]) -> None:
        if self.lag:
            asyncio.get_running_loop().call_later(self.lag, setattr, self, "output_devices", devices)
        else:
            self.output_devices = devices

    def _ignored(self) -> bool:
        if self.ignore:
            self.ignore -= 1
            return True
        return False

    def _devices(self, ids: tuple[str, ...]) -> list[OutputDevice]:
        found = [self.network.by_id(i) for i in ids]
        return [OutputDevice(name=s.name, identifier=s.airplay_id) for s in found if s]

    async def set_output_devices(self, *ids: str) -> None:
        self.calls.append(("set", ids))
        if self.fail:
            raise self.fail
        if self._ignored():
            return
        self._apply(self._devices(ids))

    async def add_output_devices(self, *ids: str) -> None:
        self.calls.append(("add", ids))
        if self.fail:
            raise self.fail
        if self._ignored():
            return
        current = {d.identifier for d in self.output_devices}
        self._apply(self.output_devices + [d for d in self._devices(ids) if d.identifier not in current])

    async def remove_output_devices(self, *ids: str) -> None:
        self.calls.append(("remove", ids))
        if self.fail:
            raise self.fail
        self._apply([d for d in self.output_devices if d.identifier not in ids])

    async def set_volume(self, level: float, output_device: OutputDevice | None = None) -> None:
        self.volumes.append((level, output_device.identifier if output_device else None))

    def set_current(self, *devices: tuple[str, str]) -> None:
        self.output_devices = [OutputDevice(name=n, identifier=i) for n, i in devices]


@pytest.fixture
def network() -> Network:
    return Network()


@pytest.fixture
def mock_scan(network: Network):
    """Replace the network scan with the fake network."""

    async def scan(*args: Any, **kwargs: Any) -> list[Any]:
        network.scans += 1
        await asyncio.sleep(network.scan_delay)
        if network.scan_error:
            raise network.scan_error
        return [s.conf() for s in network.speakers]

    with (
        patch("pyatv.scan", side_effect=scan),
        patch(
            "custom_components.apple_tv_output.speakers.zeroconf.async_get_async_instance",
            AsyncMock(return_value=None),
        ),
    ):
        yield


def add_apple_tv(
    hass: HomeAssistant,
    network: Network,
    object_id: str,
    name: str,
    mrp_id: str,
    airplay_id: str,
    model: str = "Apple TV 4K",
) -> tuple[Any, MockConfigEntry]:
    """Add an Apple TV the way the Apple TV integration sets it up; return its pyatv connection."""
    atv = SimpleNamespace(audio=FakeAudio(network), device_info=SimpleNamespace(output_device_id=None, mac=airplay_id))
    entry = MockConfigEntry(
        domain="apple_tv", unique_id=mrp_id, title=name, data={"name": name, "identifiers": [mrp_id, airplay_id]}
    )
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(atv=atv)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("apple_tv", mrp_id)}, name=name, model=model
    )
    er.async_get(hass).async_get_or_create(
        "media_player", "apple_tv", mrp_id, suggested_object_id=object_id, config_entry=entry, device_id=device.id
    )
    return atv, entry


@pytest.fixture
async def atv(hass: HomeAssistant, network: Network, mock_scan: None) -> Any:
    """An Apple TV, and the actions registered."""
    atv, _ = add_apple_tv(hass, network, "living_room_tv", ATV_NAME, ATV_MRP_ID, ATV_AIRPLAY_ID)
    async_setup_services(hass)
    return atv


@pytest.fixture
def entity_component(hass: HomeAssistant):
    """Let tests hand out media player entities, as the media player component would."""
    entities: dict[str, Any] = {}
    hass.data[DATA_COMPONENT] = SimpleNamespace(get_entity=entities.get)
    return entities


@pytest.fixture
def setup_integration(hass: HomeAssistant, atv: Any, mock_async_zeroconf: None):
    """Return a function that loads the integration's config entry, with the given options."""

    async def setup(options: dict[str, Any] | None = None) -> MockConfigEntry:
        entry = MockConfigEntry(domain=DOMAIN, title="Apple TV Audio Output", options=options or {})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        # Default speakers and the first scan run as background tasks.
        await hass.async_block_till_done(wait_background_tasks=True)
        return entry

    # The Apple TV integration's own setup would try to reach the Apple TV.
    with patch("homeassistant.components.apple_tv.async_setup_entry", return_value=True):
        yield setup
