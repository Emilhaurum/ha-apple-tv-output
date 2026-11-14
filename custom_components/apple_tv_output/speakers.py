"""Finding AirPlay speakers and turning names, entities and ids into speakers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
import logging
import time

from homeassistant.components import zeroconf
from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util.hass_dict import HassKey

from .common import canonical, error, is_id, key
from .const import CACHE_TTL, DOMAIN, SCAN_TIMEOUT

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Device:
    """An AirPlay speaker."""

    name: str
    # The id sent to the Apple TV.
    identifier: str
    # Every id the speaker is known by, as key() forms; any of them can show up in the outputs.
    keys: frozenset[str]


@dataclass
class Cache:
    """Speakers found by network scans, by case-folded name."""

    devices: dict[str, list[Device]] = field(default_factory=dict)
    scanned_at: float | None = None
    # Only one scan at a time; calls that wait for it use its result.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Called after every scan, for entities that list the speakers.
    listeners: list[Callable[[], None]] = field(default_factory=list)

    @property
    def expired(self) -> bool:
        return self.scanned_at is None or time.monotonic() - self.scanned_at > CACHE_TTL

    def all(self) -> list[Device]:
        """Return every known speaker, sorted by name."""
        return sorted((d for ds in self.devices.values() for d in ds), key=lambda d: (d.name.casefold(), d.identifier))

    def names(self) -> str:
        return ", ".join(sorted({d.name for d in self.all()}, key=str.casefold)) or "none"

    def by_key(self) -> dict[str, Device]:
        return {k: device for device in self.all() for k in device.keys}


DATA_CACHE: HassKey[Cache] = HassKey(DOMAIN)


@dataclass
class Speaker:
    """A speaker as given in an action call, and what it was resolved to."""

    requested: str
    device: Device
    # True when the name was resolved from an earlier scan, which may be out of date.
    from_cache: bool = False
    # True when an entity was resolved by its device's network address, which may not be the AirPlay id;
    # if it does not become an output, the entity's name is tried instead.
    by_address: bool = False


def get_cache(hass: HomeAssistant) -> Cache:
    return hass.data.setdefault(DATA_CACHE, Cache())


@callback
def async_add_listener(hass: HomeAssistant, listener: Callable[[], None]) -> Callable[[], None]:
    """Call the listener after every scan; return a function that removes it."""
    cache = get_cache(hass)
    cache.listeners.append(listener)
    return lambda: cache.listeners.remove(listener)


async def _scan(hass: HomeAssistant, cache: Cache) -> None:
    """Find the AirPlay speakers on the network."""
    # Imported here: pyatv is installed by the Apple TV integration.
    from pyatv import scan
    from pyatv.const import Protocol

    aiozc = await zeroconf.async_get_async_instance(hass)
    devices: dict[str, list[Device]] = {}
    for conf in await scan(hass.loop, timeout=SCAN_TIMEOUT, aiozc=aiozc):
        # The main id of a HomePod or Apple TV is its MRP id; the outputs use the AirPlay one.
        identifier = None
        for protocol in (Protocol.AirPlay, Protocol.RAOP):
            service = conf.get_service(protocol)
            if service is not None and service.identifier:
                identifier = service.identifier
                break
        identifier = identifier or conf.identifier
        if not identifier or not conf.name:
            continue
        keys = frozenset(key(i) for i in [identifier, *conf.all_identifiers])
        same_name = devices.setdefault(conf.name.casefold(), [])
        if not any(d.keys & keys for d in same_name):
            same_name.append(Device(conf.name, identifier, keys))

    # A speaker can miss a scan (asleep, slow to answer): keep what earlier scans found, unless the
    # speaker was found again (perhaps renamed) or its name now belongs to a speaker just found.
    seen = frozenset().union(*(d.keys for ds in devices.values() for d in ds))
    for name, old in cache.devices.items():
        for device in old:
            if not device.keys & seen and name not in devices:
                devices.setdefault(name, []).append(device)
    cache.devices = devices
    cache.scanned_at = time.monotonic()
    _LOGGER.debug("Found AirPlay speakers: %s", devices)
    for listener in list(cache.listeners):
        listener()


async def async_scan(hass: HomeAssistant, *, force: bool = True) -> Cache:
    """Scan, unless another call scanned while this one waited (or the cache is fresh and not forced)."""
    cache = get_cache(hass)
    started = cache.scanned_at
    async with cache.lock:
        if cache.scanned_at == started and (force or cache.expired):
            await _scan(hass, cache)
    return cache


@callback
def async_start_background_scans(hass: HomeAssistant) -> Callable[[], None]:
    """Scan now and then shortly before the speakers found expire, so calls by name need not wait."""

    async def refresh(_now: object = None) -> None:
        try:
            await async_scan(hass)
        except Exception as err:
            _LOGGER.debug("Background scan for AirPlay speakers failed: %s", err)

    hass.async_create_background_task(refresh(), f"{DOMAIN} first scan")
    return async_track_time_interval(hass, refresh, timedelta(seconds=CACHE_TTL * 0.9), name=f"{DOMAIN} scan")


def _entity_address(hass: HomeAssistant, entity_id: str) -> str | None:
    """Return the MAC address of an entity's device, if its integration registered one."""
    entry = er.async_get(hass).async_get(entity_id)
    device = dr.async_get(hass).async_get(entry.device_id) if entry and entry.device_id else None
    # Only a main device has connections; a child device (Home Assistant 2026.9 and newer) has none.
    for kind, value in device.connections if isinstance(device, dr.DeviceEntry) else ():
        if kind == dr.CONNECTION_NETWORK_MAC and is_id(value):
            return canonical(value)
    return None


async def async_resolve(
    hass: HomeAssistant, speakers: list[str], *, rescan: bool = False, by_address: bool = True
) -> list[Speaker]:
    """Turn AirPlay ids, speaker names and media player entities into speakers."""
    cache = get_cache(hass)
    # (as given, the name or id to look up, whether it is an entity's network address)
    wanted: list[tuple[str, str, bool]] = []
    for speaker in speakers:
        text = speaker.strip()
        address = False
        if text.startswith(f"{MEDIA_PLAYER_DOMAIN}."):
            if (state := hass.states.get(text)) is None:
                raise error(ServiceValidationError, "unknown_speaker_entity", entity_id=text)
            mac = _entity_address(hass, text) if by_address else None
            text, address = (mac, True) if mac else (state.name, False)
        wanted.append((speaker, text, address))

    scanned = False
    if rescan or any(
        not is_id(name) and (cache.expired or name.casefold() not in cache.devices) for _, name, _ in wanted
    ):
        await async_scan(hass)
        scanned = True

    known = cache.by_key()
    result = []
    for speaker, name, address in wanted:
        if is_id(name):
            identifier = canonical(name)
            if (device := known.get(key(identifier))) is not None:
                # Any of a speaker's ids may have been given (an MRP id, say): send its AirPlay id.
                result.append(Speaker(speaker, device, by_address=address))
            else:
                result.append(
                    Speaker(speaker, Device(name, identifier, frozenset({key(identifier)})), by_address=address)
                )
            continue
        matches = cache.devices.get(name.casefold(), [])
        source = "" if speaker.strip() == name else f" (from {speaker.strip()})"
        if not matches:
            raise error(ServiceValidationError, "speaker_not_found", name=name, source=source, found=cache.names())
        if len(matches) > 1:
            ids = ", ".join(d.identifier for d in matches)
            raise error(ServiceValidationError, "speaker_ambiguous", name=name, source=source, ids=ids)
        result.append(Speaker(speaker, matches[0], from_cache=not scanned))
    return result
