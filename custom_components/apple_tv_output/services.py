"""Actions for Apple TV Audio Output."""

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.components import zeroconf
from homeassistant.components.media_player import DATA_COMPONENT
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import (
    ATTR_FORCE,
    ATTR_SPEAKERS,
    DOMAIN,
    SCAN_TIMEOUT,
    SERVICE_ADD_OUTPUT,
    SERVICE_GET_OUTPUTS,
    SERVICE_REMOVE_OUTPUT,
    SERVICE_SET_OUTPUT,
)

_LOGGER = logging.getLogger(__name__)

APPLE_TV_DOMAIN = "apple_tv"
# AirPlay ids: a MAC address (with or without colons) or a UUID.
_ID = re.compile(r"^(?:[0-9A-F]{2}(?::[0-9A-F]{2}){5}|[0-9A-F]{12}|[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12})$", re.I)

_TARGET = {vol.Required("entity_id"): cv.entity_ids}
_SPEAKERS = {vol.Required(ATTR_SPEAKERS): vol.All(cv.ensure_list, [cv.string], vol.Length(min=1))}
MODIFY_SCHEMA = vol.Schema({**_TARGET, **_SPEAKERS, vol.Optional(ATTR_FORCE, default=False): cv.boolean})
REMOVE_SCHEMA = vol.Schema({**_TARGET, **_SPEAKERS})
GET_SCHEMA = vol.Schema(_TARGET)


def _connection(hass: HomeAssistant, entity_id: str) -> Any:
    """Return the Apple TV integration's live pyatv connection for a media player."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != APPLE_TV_DOMAIN:
        raise ServiceValidationError(f"{entity_id} is not an Apple TV media player")
    component = hass.data.get(DATA_COMPONENT)
    entity = component.get_entity(entity_id) if component else None
    atv = getattr(entity, "atv", None)
    if atv is None and entry.config_entry_id:
        # Fall back to the config entry's connection manager.
        config_entry = hass.config_entries.async_get_entry(entry.config_entry_id)
        atv = getattr(getattr(config_entry, "runtime_data", None), "atv", None)
    if atv is None:
        raise HomeAssistantError(f"{entity_id} is not connected")
    return atv


async def _speaker_ids(hass: HomeAssistant, speakers: list[str]) -> list[str]:
    """Turn AirPlay ids, speaker names and media player entities into AirPlay ids."""
    cache: dict[str, str] = hass.data.setdefault(DOMAIN, {})
    wanted: list[tuple[str, str]] = []
    for speaker in speakers:
        name = speaker.strip()
        if name.startswith("media_player."):
            if (state := hass.states.get(name)) is None:
                raise ServiceValidationError(f"Unknown speaker entity {name}")
            name = state.name
        wanted.append((speaker, name))

    if any(not _ID.match(name) and name.casefold() not in cache for _, name in wanted):
        # Imported here: pyatv is installed by the Apple TV integration.
        from pyatv import scan  # noqa: PLC0415

        aiozc = await zeroconf.async_get_async_instance(hass)
        for conf in await scan(hass.loop, timeout=SCAN_TIMEOUT, aiozc=aiozc):
            if conf.identifier:
                cache[conf.name.casefold()] = conf.identifier

    ids = []
    for speaker, name in wanted:
        if _ID.match(name):
            ids.append(name)
        elif (found := cache.get(name.casefold())) is not None:
            ids.append(found)
        else:
            source = "" if speaker == name else f" (from {speaker})"
            raise HomeAssistantError(
                f'No AirPlay speaker named "{name}"{source} was found. Found: {", ".join(sorted(cache)) or "none"}'
            )
    return ids


def _outputs(atv: Any) -> list[dict[str, str | None]]:
    return [{"name": device.name, "identifier": device.identifier} for device in atv.audio.output_devices]


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""

    async def modify(call: ServiceCall) -> None:
        ids = await _speaker_ids(hass, call.data[ATTR_SPEAKERS])
        for entity_id in call.data["entity_id"]:
            atv = _connection(hass, entity_id)
            current = {(device.identifier or "").casefold() for device in atv.audio.output_devices}
            present = [speaker.casefold() in current for speaker in ids]
            try:
                if call.service == SERVICE_REMOVE_OUTPUT:
                    if any(present):
                        await atv.audio.remove_output_devices(*ids)
                elif all(present) and not call.data[ATTR_FORCE]:
                    # Already playing there: sending it again could interrupt the sound.
                    continue
                elif call.service == SERVICE_ADD_OUTPUT:
                    await atv.audio.add_output_devices(*ids)
                else:
                    await atv.audio.set_output_devices(*ids)
            except Exception as err:
                raise HomeAssistantError(f"Could not change the audio output of {entity_id}: {err}") from err
            _LOGGER.debug("Output of %s is now %s", entity_id, _outputs(atv))

    async def get_outputs(call: ServiceCall) -> ServiceResponse:
        return {entity_id: {"outputs": _outputs(_connection(hass, entity_id))} for entity_id in call.data["entity_id"]}

    hass.services.async_register(DOMAIN, SERVICE_SET_OUTPUT, modify, schema=MODIFY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_ADD_OUTPUT, modify, schema=MODIFY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REMOVE_OUTPUT, modify, schema=REMOVE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_GET_OUTPUTS, get_outputs, schema=GET_SCHEMA, supports_response=SupportsResponse.ONLY
    )
