"""Fixtures: a fake network of Apple TVs and AirPlay speakers, standing in for pyatv."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pyatv.const import DeviceModel, OperatingSystem, PairingRequirement, PowerState, Protocol
from pyatv.exceptions import AuthenticationError
from pyatv.interface import OutputDevice
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.apple_tv_output.const import CONF_ADDRESS, CONF_CREDENTIALS, CONF_IDENTIFIERS, DOMAIN

# The Apple TV integration's media player of the Apple TV; actions that target it keep working.
ATV_ENTITY = "media_player.living_room_tv"
# Older pyatv (Home Assistant 2025.1) has no volume per output.
HAS_VOLUME = hasattr(OutputDevice(name="x", identifier="x"), "volume")
ATV_NAME = "Living Room TV"
ATV_MRP_ID = "11111111-2222-3333-4444-555555555555"
ATV_AIRPLAY_ID = "AA:BB:CC:DD:EE:FF"
PIN = 1234


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components."""


@pytest.fixture(autouse=True)
def no_waiting():
    """Do not wait for outputs that will never come, nor between attempts, unless a test asks for it."""
    with (
        patch("custom_components.apple_tv_output.const.OUTPUT_SETTLE_TIME", 0),
        patch("custom_components.apple_tv_output.const.RETRY_DELAY", 0),
        patch("custom_components.apple_tv_output.const.RECONNECT_MIN", 0.01),
    ):
        yield


@dataclass
class FakeService:
    identifier: str
    pairing: PairingRequirement = PairingRequirement.NotNeeded
    credentials: str | None = None


@dataclass
class FakeConf:
    """What pyatv.scan reports for a device."""

    name: str
    address: str
    services: dict[Protocol, FakeService]
    device_info: Any

    @property
    def identifier(self) -> str:
        # Like pyatv: MRP first when there is one.
        for protocol in (Protocol.MRP, Protocol.AirPlay):
            if protocol in self.services:
                return self.services[protocol].identifier
        raise AssertionError

    @property
    def all_identifiers(self) -> list[str]:
        return [s.identifier for s in self.services.values()]

    def get_service(self, protocol: Protocol) -> FakeService | None:
        return self.services.get(protocol)

    def set_credentials(self, protocol: Protocol, credentials: str) -> bool:
        self.services[protocol].credentials = credentials
        return True


@dataclass
class FakeSpeaker:
    """An AirPlay speaker on the fake network."""

    name: str
    airplay_id: str
    mrp_id: str | None = None

    def conf(self) -> FakeConf:
        services = {Protocol.AirPlay: FakeService(self.airplay_id)}
        if self.mrp_id:
            services[Protocol.MRP] = FakeService(self.mrp_id)
        info = SimpleNamespace(operating_system=OperatingSystem.Unknown, model=DeviceModel.Unknown)
        return FakeConf(self.name, "10.0.0.50", services, info)


class FakeAudio:
    """pyatv's audio interface: changes the outputs when given ids of reachable speakers."""

    def __init__(self, network: Network) -> None:
        self.network = network
        self.listener: Any = None
        self.output_devices: list[OutputDevice] = []
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.fail: Exception | None = None
        # Seconds before a change shows up in output_devices, as on a real Apple TV.
        self.lag: float = 0
        # Commands to ignore before obeying, like an Apple TV that has only just woken up.
        self.ignore: int = 0
        self.volumes: list[tuple[float, str | None]] = []

    def _apply(self, devices: list[OutputDevice]) -> None:
        def apply() -> None:
            old, self.output_devices = self.output_devices, devices
            if self.listener is not None:
                self.listener.outputdevices_update(old, devices)

        if self.lag:
            asyncio.get_running_loop().call_later(self.lag, apply)
        else:
            apply()

    def _ignored(self) -> bool:
        if self.ignore:
            self.ignore -= 1
            return True
        return False

    def _devices(self, ids: tuple[str, ...]) -> list[OutputDevice]:
        found = [self.network.speaker_by_id(i) for i in ids]
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
        """Change the outputs as if by the Apple TV's own menu."""
        self._apply([OutputDevice(name=n, identifier=i) for n, i in devices])


class FakeAppleTV:
    """A connected pyatv AppleTV: its audio and power interfaces, and the connection's listener."""

    def __init__(self, device: FakeAppleTVDevice) -> None:
        self.device = device
        self.audio = device.audio
        self.power = SimpleNamespace(power_state=device.power, listener=None)
        self.listener: Any = None
        self.device_info = SimpleNamespace(
            output_device_id=None, mac=device.airplay_id, model_str="Apple TV 4K (gen 3)", version="26.1"
        )
        self.closed = False

    def close(self) -> set[asyncio.Task]:
        self.closed = True
        return set()


@dataclass
class FakeAppleTVDevice:
    """An Apple TV on the fake network."""

    network: Network
    name: str
    mrp_id: str
    airplay_id: str
    address: str = "10.0.0.10"
    model: DeviceModel = DeviceModel.AppleTV4KGen3
    power: PowerState = PowerState.On
    online: bool = True
    # The credentials it accepts for each protocol (set by pairing).
    accepted: dict[Protocol, str] = field(default_factory=dict)
    connection: FakeAppleTV | None = None

    def __post_init__(self) -> None:
        self.audio = FakeAudio(self.network)

    def conf(self) -> FakeConf:
        services = {
            Protocol.MRP: FakeService(self.mrp_id),
            Protocol.AirPlay: FakeService(self.airplay_id, PairingRequirement.Mandatory),
        }
        info = SimpleNamespace(operating_system=OperatingSystem.TvOS, model=self.model)
        return FakeConf(self.name, self.address, services, info)

    def connect(self, conf: FakeConf) -> FakeAppleTV:
        for protocol, credentials in self.accepted.items():
            service = conf.get_service(protocol)
            if service is None or service.credentials != credentials:
                raise AuthenticationError("not paired")
        self.connection = FakeAppleTV(self)
        return self.connection

    def lose_connection(self) -> None:
        """Drop the connection, as when the network fails or (possibly) the Apple TV sleeps."""
        connection, self.connection = self.connection, None
        assert connection is not None and connection.listener is not None
        connection.listener.connection_lost(ConnectionError("lost"))

    def set_power(self, on: bool) -> None:
        old, self.power = self.power, PowerState.On if on else PowerState.Off
        if self.connection is not None:
            self.connection.power.power_state = self.power
            if self.connection.power.listener is not None:
                self.connection.power.listener.powerstate_update(old, self.power)


@dataclass
class Network:
    """The Apple TVs and speakers a scan finds."""

    speakers: list[FakeSpeaker] = field(default_factory=list)
    apple_tvs: list[FakeAppleTVDevice] = field(default_factory=list)
    scans: int = 0
    scan_delay: float = 0
    scan_error: Exception | None = None

    def add(self, *speakers: FakeSpeaker) -> None:
        self.speakers.extend(speakers)

    def speaker_by_id(self, identifier: str) -> FakeSpeaker | None:
        return next((s for s in self.speakers if s.airplay_id == identifier), None)

    def add_apple_tv(self, name: str, mrp_id: str, airplay_id: str, **kwargs: Any) -> FakeAppleTVDevice:
        device = FakeAppleTVDevice(self, name, mrp_id, airplay_id, **kwargs)
        self.apple_tvs.append(device)
        return device

    def device_for(self, conf: FakeConf) -> FakeAppleTVDevice:
        return next(d for d in self.apple_tvs if d.mrp_id in conf.all_identifiers)


@pytest.fixture
def network() -> Network:
    return Network()


@pytest.fixture(autouse=True)
def mock_pyatv(network: Network):
    """Replace pyatv's scan, connect and pair with the fake network."""

    async def scan(*args: Any, identifier: Any = None, hosts: Any = None, **kwargs: Any) -> list[FakeConf]:
        network.scans += 1
        await asyncio.sleep(network.scan_delay)
        if network.scan_error:
            raise network.scan_error
        confs = [d.conf() for d in network.apple_tvs if d.online] + [s.conf() for s in network.speakers]
        if identifier:
            wanted = {identifier} if isinstance(identifier, str) else set(identifier)
            confs = [c for c in confs if wanted & set(c.all_identifiers)]
        if hosts:
            confs = [c for c in confs if c.address in hosts]
        return confs

    async def connect(conf: FakeConf, loop: Any, **kwargs: Any) -> FakeAppleTV:
        return network.device_for(conf).connect(conf)

    async def pair(conf: FakeConf, protocol: Protocol, loop: Any, **kwargs: Any) -> Any:
        return FakePairing(network.device_for(conf), conf, protocol)

    with (
        patch("pyatv.scan", side_effect=scan),
        patch("pyatv.connect", side_effect=connect),
        patch("pyatv.pair", side_effect=pair),
        patch(
            "custom_components.apple_tv_output.speakers.zeroconf.async_get_async_instance", AsyncMock(return_value=None)
        ),
        patch(
            "custom_components.apple_tv_output.connection.zeroconf.async_get_async_instance",
            AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.apple_tv_output.config_flow.zeroconf.async_get_async_instance",
            AsyncMock(return_value=None),
        ),
        # The fake pyatv needs no web session; a real one would start resolver threads.
        patch("custom_components.apple_tv_output.connection.async_get_clientsession", return_value=None),
        patch("custom_components.apple_tv_output.config_flow.async_get_clientsession", return_value=None),
    ):
        yield


class FakePairing:
    """pyatv's pairing handler: the Apple TV shows PIN, and pairing succeeds when it is typed."""

    def __init__(self, device: FakeAppleTVDevice, conf: FakeConf, protocol: Protocol) -> None:
        self.device = device
        self.service = conf.get_service(protocol)
        self.protocol = protocol
        self.device_provides_pin = True
        self.has_paired = False
        self._pin: int | None = None
        self.closed = False

    async def begin(self) -> None:
        pass

    def pin(self, pin: int) -> None:
        self._pin = pin

    async def finish(self) -> None:
        if self._pin == PIN:
            credentials = f"credentials-{self.protocol.name}-{len(self.device.accepted)}"
            self.service.credentials = credentials
            self.device.accepted[self.protocol] = credentials
            self.has_paired = True

    async def close(self) -> None:
        self.closed = True


def add_apple_tv(
    hass: HomeAssistant,
    network: Network,
    object_id: str,
    name: str,
    mrp_id: str,
    airplay_id: str,
    model: str = "Apple TV 4K",
    *,
    options: dict[str, Any] | None = None,
) -> tuple[FakeAppleTVDevice, MockConfigEntry]:
    """Add a paired Apple TV: on the network, as this integration's entry, and as the Apple TV integration's
    media player (whose entity id actions may still target)."""
    device = network.add_apple_tv(name, mrp_id, airplay_id)
    device.accepted = {Protocol.AirPlay: "paired"}
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=name,
        unique_id=mrp_id,
        data={
            CONF_ADDRESS: device.address,
            CONF_IDENTIFIERS: [mrp_id, airplay_id],
            CONF_CREDENTIALS: {str(Protocol.AirPlay.value): "paired"},
        },
        options=options or {},
    )
    entry.add_to_hass(hass)
    apple_tv_entry = MockConfigEntry(domain="apple_tv", unique_id=mrp_id, title=name)
    apple_tv_entry.add_to_hass(hass)
    core_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=apple_tv_entry.entry_id, identifiers={("apple_tv", mrp_id)}, name=name, model=model
    )
    er.async_get(hass).async_get_or_create(
        "media_player",
        "apple_tv",
        mrp_id,
        suggested_object_id=object_id,
        config_entry=apple_tv_entry,
        device_id=core_device.id,
    )
    return device, entry


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    # The connection, the first scan and default speakers run as background tasks.
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.fixture
def setup_integration(hass: HomeAssistant, network: Network, mock_async_zeroconf: None):
    """Return a function that adds the Apple TV with the given options and loads its entry."""

    async def setup(options: dict[str, Any] | None = None) -> tuple[FakeAppleTVDevice, MockConfigEntry]:
        device, entry = add_apple_tv(
            hass, network, "living_room_tv", ATV_NAME, ATV_MRP_ID, ATV_AIRPLAY_ID, options=options
        )
        await setup_entry(hass, entry)
        return device, entry

    return setup


@pytest.fixture
async def atv(setup_integration: Any) -> FakeAppleTVDevice:
    """A paired, connected Apple TV."""
    device, _ = await setup_integration()
    return device
