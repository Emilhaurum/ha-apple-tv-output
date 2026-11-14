"""Actions for Apple TV Audio Output."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
import time
from typing import Any

from homeassistant.components import zeroconf
from homeassistant.components.media_player import DATA_COMPONENT, DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.util.hass_dict import HassKey
from homeassistant.util.json import JsonValueType
import voluptuous as vol

from .const import (
    APPLE_TV_DOMAIN,
    ATTR_FORCE,
    ATTR_SPEAKERS,
    CACHE_TTL,
    DOMAIN,
    SCAN_TIMEOUT,
    SERVICE_ADD_OUTPUT,
    SERVICE_GET_OUTPUTS,
    SERVICE_REMOVE_OUTPUT,
    SERVICE_SET_OUTPUT,
)

try:
    from homeassistant.helpers.target import TargetSelection, async_extract_referenced_entity_ids
except ImportError:  # Older Home Assistant releases
    TargetSelection = None  # type: ignore[assignment,misc]
    from homeassistant.helpers.service import (  # type: ignore[attr-defined,unused-ignore]
        async_extract_referenced_entity_ids as _legacy_extract,
    )

_LOGGER = logging.getLogger(__name__)

ISSUE_URL = "https://github.com/Emilhaurum/ha-apple-tv-output/issues"

# AirPlay ids: a MAC address (with colons, dashes or nothing between the bytes) or a UUID.
_MAC = re.compile(r"^[0-9A-F]{2}(?:([:-]?)[0-9A-F]{2})(?:\1[0-9A-F]{2}){4}$", re.I)
_UUID = re.compile(r"^[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}$", re.I)

_SPEAKERS = {vol.Required(ATTR_SPEAKERS): vol.All(cv.ensure_list, [cv.string], vol.Length(min=1))}
MODIFY_SCHEMA = cv.make_entity_service_schema({**_SPEAKERS, vol.Optional(ATTR_FORCE, default=False): cv.boolean})
REMOVE_SCHEMA = cv.make_entity_service_schema(_SPEAKERS)
GET_SCHEMA = cv.make_entity_service_schema({})


@dataclass(frozen=True)
class _Device:
    """An AirPlay speaker."""

    name: str
    # The id sent to the Apple TV.
    identifier: str
    # Every id the speaker is known by, as _key() forms; any of them can show up in the outputs.
    keys: frozenset[str]


@dataclass
class _Cache:
    """Speakers found by the last network scan, by case-folded name."""

    devices: dict[str, list[_Device]] = field(default_factory=dict)
    scanned_at: float | None = None

    @property
    def expired(self) -> bool:
        return self.scanned_at is None or time.monotonic() - self.scanned_at > CACHE_TTL

    def names(self) -> str:
        return ", ".join(sorted({d.name for ds in self.devices.values() for d in ds}, key=str.casefold)) or "none"


DATA_CACHE: HassKey[_Cache] = HassKey(DOMAIN)


@dataclass
class _Speaker:
    """A speaker as given in an action call, and what it was resolved to."""

    requested: str
    device: _Device
    # True when the name was resolved from an earlier scan, which may be out of date.
    from_cache: bool = False


@dataclass
class _AppleTV:
    """An Apple TV targeted by an action call."""

    entity_id: str
    atv: Any
    # Ids (as _key() forms) and names by which the Apple TV itself can appear in its own outputs.
    own_keys: frozenset[str]
    own_names: frozenset[str]


def _key(identifier: str) -> str:
    """Return a form of an id that compares equal however it is written."""
    return re.sub(r"[^0-9a-z]", "", identifier.casefold())


def _is_id(text: str) -> bool:
    return bool(_MAC.match(text) or _UUID.match(text))


def _canonical(identifier: str) -> str:
    """Write a MAC address the way the Apple TV reports it: upper case with colons."""
    if _MAC.match(identifier):
        digits = _key(identifier).upper()
        return ":".join(digits[i : i + 2] for i in range(0, 12, 2))
    return identifier


def _error(cls: type[HomeAssistantError], key: str, **placeholders: str) -> HomeAssistantError:
    return cls(translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders)


def _apple_tv(hass: HomeAssistant, entity_id: str) -> _AppleTV:
    """Return the Apple TV integration's live pyatv connection for a media player."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != APPLE_TV_DOMAIN or entry.domain != MEDIA_PLAYER_DOMAIN:
        raise _error(ServiceValidationError, "not_apple_tv", entity_id=entity_id)

    component = hass.data.get(DATA_COMPONENT)
    entity = component.get_entity(entity_id) if component else None
    config_entry = hass.config_entries.async_get_entry(entry.config_entry_id) if entry.config_entry_id else None
    manager = getattr(config_entry, "runtime_data", None)

    if (entity is not None or manager is not None) and not hasattr(entity, "atv") and not hasattr(manager, "atv"):
        # This relies on internals of the Apple TV integration; say clearly when they have changed.
        _LOGGER.error(
            "The Apple TV integration in Home Assistant %s no longer exposes its pyatv connection "
            "(%s has no 'atv' attribute), so %s cannot be controlled. Please report this at %s",
            HA_VERSION,
            type(entity if entity is not None else manager).__name__,
            entity_id,
            ISSUE_URL,
        )
        raise _error(HomeAssistantError, "unsupported_version", version=HA_VERSION)

    atv = getattr(entity, "atv", None) or getattr(manager, "atv", None)
    if atv is None:
        raise _error(HomeAssistantError, "not_connected", entity_id=entity_id)

    own_ids: list[str] = []
    own_names: list[str] = []
    if config_entry is not None:
        own_ids += [config_entry.unique_id or "", *config_entry.data.get("identifiers", [])]
        own_names += [config_entry.title, config_entry.data.get("name", "")]
    device_info = getattr(atv, "device_info", None)
    own_ids += [getattr(device_info, "output_device_id", None) or "", getattr(device_info, "mac", None) or ""]
    return _AppleTV(
        entity_id,
        atv,
        frozenset(_key(i) for i in own_ids if i),
        frozenset(n.casefold() for n in own_names if n),
    )


def _targets(hass: HomeAssistant, call: ServiceCall) -> list[_AppleTV]:
    """Return the Apple TVs a call targets.

    An entity named directly must be an Apple TV; of the entities an area or device brings in, the
    Apple TV media players are kept and the rest ignored.
    """
    if TargetSelection is not None:
        selected = async_extract_referenced_entity_ids(hass, TargetSelection(call.data))
    else:
        selected = _legacy_extract(hass, call)
    registry = er.async_get(hass)
    entity_ids = set(selected.referenced)
    for entity_id in selected.indirectly_referenced:
        entry = registry.async_get(entity_id)
        if entry and entry.platform == APPLE_TV_DOMAIN and entry.domain == MEDIA_PLAYER_DOMAIN:
            entity_ids.add(entity_id)
    if not entity_ids:
        raise _error(ServiceValidationError, "no_apple_tv")
    # Check every Apple TV before changing any, so a bad target cannot leave a half-done change.
    return [_apple_tv(hass, entity_id) for entity_id in sorted(entity_ids)]


async def _scan(hass: HomeAssistant, cache: _Cache) -> None:
    """Find the AirPlay speakers on the network."""
    # Imported here: pyatv is installed by the Apple TV integration.
    from pyatv import scan
    from pyatv.const import Protocol

    aiozc = await zeroconf.async_get_async_instance(hass)
    devices: dict[str, list[_Device]] = {}
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
        keys = frozenset(_key(i) for i in [identifier, *conf.all_identifiers])
        same_name = devices.setdefault(conf.name.casefold(), [])
        if not any(d.keys & keys for d in same_name):
            same_name.append(_Device(conf.name, identifier, keys))
    cache.devices = devices
    cache.scanned_at = time.monotonic()
    _LOGGER.debug("Found AirPlay speakers: %s", devices)


async def _resolve(hass: HomeAssistant, speakers: list[str], *, rescan: bool = False) -> list[_Speaker]:
    """Turn AirPlay ids, speaker names and media player entities into speakers."""
    cache = hass.data.setdefault(DATA_CACHE, _Cache())
    wanted: list[tuple[str, str]] = []
    for speaker in speakers:
        text = speaker.strip()
        if text.startswith(f"{MEDIA_PLAYER_DOMAIN}."):
            if (state := hass.states.get(text)) is None:
                raise _error(ServiceValidationError, "unknown_speaker_entity", entity_id=text)
            text = state.name
        wanted.append((speaker, text))

    scanned = False
    if rescan or any(
        not _is_id(name) and (cache.expired or name.casefold() not in cache.devices) for _, name in wanted
    ):
        await _scan(hass, cache)
        scanned = True

    known = {key: device for ds in cache.devices.values() for device in ds for key in device.keys}
    result = []
    for speaker, name in wanted:
        if _is_id(name):
            identifier = _canonical(name)
            device = known.get(_key(identifier))
            keys = frozenset({_key(identifier)} | (device.keys if device else set()))
            result.append(_Speaker(speaker, _Device(device.name if device else name, identifier, keys)))
            continue
        matches = cache.devices.get(name.casefold(), [])
        source = "" if speaker.strip() == name else f" (from {speaker.strip()})"
        if not matches:
            raise _error(ServiceValidationError, "speaker_not_found", name=name, source=source, found=cache.names())
        if len(matches) > 1:
            ids = ", ".join(d.identifier for d in matches)
            raise _error(ServiceValidationError, "speaker_ambiguous", name=name, source=source, ids=ids)
        result.append(_Speaker(speaker, matches[0], from_cache=not scanned))
    return result


def _outputs(atv: Any) -> list[JsonValueType]:
    return [{"name": device.name, "identifier": device.identifier} for device in atv.audio.output_devices]


def _current(atv: Any) -> dict[str, str]:
    """Return the current outputs, as a map from _key() form to the id the Apple TV reports."""
    return {_key(d.identifier): d.identifier for d in atv.audio.output_devices if d.identifier}


def _is_only_output(tv: _AppleTV, speakers: list[_Speaker]) -> bool:
    """Return whether the speakers are the only outputs, not counting the Apple TV itself."""
    wanted = frozenset().union(*(s.device.keys for s in speakers))
    for device in tv.atv.audio.output_devices:
        key = _key(device.identifier or "")
        if key in wanted or key in tv.own_keys:
            continue
        if (device.name or "").casefold() in tv.own_names:
            continue
        return False
    return True


async def _send(tv: _AppleTV, method: Any, identifiers: list[str]) -> None:
    try:
        await method(*identifiers)
    except Exception as err:
        raise _error(HomeAssistantError, "command_failed", entity_id=tv.entity_id, error=str(err) or repr(err)) from err


async def _modify(hass: HomeAssistant, call: ServiceCall, tv: _AppleTV, speakers: list[_Speaker]) -> list[_Speaker]:
    """Change the outputs of one Apple TV; return the speakers, which a rescan may have updated."""
    audio = tv.atv.audio
    current = _current(tv.atv)
    present = [next((current[k] for k in s.device.keys if k in current), None) for s in speakers]

    if call.service == SERVICE_REMOVE_OUTPUT:
        # Send the ids as the Apple TV reports them.
        if found := [identifier for identifier in present if identifier is not None]:
            await _send(tv, audio.remove_output_devices, found)
            _LOGGER.debug("Outputs of %s are now %s", tv.entity_id, _outputs(tv.atv))
        return speakers

    # Already playing there: sending it again could interrupt the sound.
    if (
        not call.data[ATTR_FORCE]
        and all(present)
        and (call.service == SERVICE_ADD_OUTPUT or _is_only_output(tv, speakers))
    ):
        return speakers

    method = audio.add_output_devices if call.service == SERVICE_ADD_OUTPUT else audio.set_output_devices
    await _send(tv, method, [s.device.identifier for s in speakers])

    if _missing(tv, speakers) and any(s.from_cache for s in speakers):
        # A speaker may have changed since the last scan (renamed, or a new id): look again, and if any
        # name now leads to another speaker, send the command once more.
        _LOGGER.debug("Not all speakers became an output of %s; scanning again", tv.entity_id)
        try:
            fresh = await _resolve(hass, [s.requested for s in speakers], rescan=True)
        except ServiceValidationError as err:
            # The command has been sent; a speaker the new scan cannot place is reported below.
            _LOGGER.debug("Scanning again did not help: %s", err)
        else:
            if [s.device.identifier for s in fresh] != [s.device.identifier for s in speakers]:
                await _send(tv, method, [s.device.identifier for s in fresh])
            speakers = fresh

    if missing := _missing(tv, speakers):
        _LOGGER.warning(
            "%s did not report %s as an output. If the Apple TV shows 'Could not connect', it cannot reach "
            "the speaker over AirPlay; see the troubleshooting section of the documentation",
            tv.entity_id,
            ", ".join(s.device.name for s in missing),
        )
    _LOGGER.debug("Outputs of %s are now %s", tv.entity_id, _outputs(tv.atv))
    return speakers


def _missing(tv: _AppleTV, speakers: list[_Speaker]) -> list[_Speaker]:
    current = _current(tv.atv)
    return [s for s in speakers if not s.device.keys & current.keys()]


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""

    async def modify(call: ServiceCall) -> None:
        apple_tvs = _targets(hass, call)
        speakers = await _resolve(hass, call.data[ATTR_SPEAKERS])
        for tv in apple_tvs:
            speakers = await _modify(hass, call, tv, speakers)

    async def get_outputs(call: ServiceCall) -> ServiceResponse:
        return {tv.entity_id: {"outputs": _outputs(tv.atv)} for tv in _targets(hass, call)}

    hass.services.async_register(DOMAIN, SERVICE_SET_OUTPUT, modify, schema=MODIFY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_ADD_OUTPUT, modify, schema=MODIFY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REMOVE_OUTPUT, modify, schema=REMOVE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_GET_OUTPUTS, get_outputs, schema=GET_SCHEMA, supports_response=SupportsResponse.ONLY
    )
