"""Actions for Apple TV Audio Output."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.helpers import config_validation as cv

from .apple_tv import targets
from .const import (
    ATTR_FAIL_IF_NOT_APPLIED,
    ATTR_FORCE,
    ATTR_RESCAN,
    ATTR_RETRIES,
    ATTR_SPEAKER,
    ATTR_SPEAKERS,
    ATTR_VOLUME_LEVEL,
    DOMAIN,
    MAX_RETRIES,
    SERVICE_ADD_OUTPUT,
    SERVICE_GET_OUTPUTS,
    SERVICE_GET_SPEAKERS,
    SERVICE_REMOVE_OUTPUT,
    SERVICE_SET_OUTPUT,
    SERVICE_SET_VOLUME,
)
from .outputs import Mode, async_change, async_set_volume, outputs
from .speakers import async_resolve, async_scan, get_cache

try:
    import probatio as vol  # Home Assistant 2026.10 and newer
except ImportError:
    import voluptuous as vol  # type: ignore[no-redef]

_SPEAKERS = {vol.Required(ATTR_SPEAKERS): vol.All(cv.ensure_list, [cv.string], vol.Length(min=1))}
MODIFY_SCHEMA = cv.make_entity_service_schema(
    {
        **_SPEAKERS,
        vol.Optional(ATTR_FORCE, default=False): cv.boolean,
        vol.Optional(ATTR_RETRIES, default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_RETRIES)),
        vol.Optional(ATTR_FAIL_IF_NOT_APPLIED, default=False): cv.boolean,
    }
)
REMOVE_SCHEMA = cv.make_entity_service_schema(_SPEAKERS)
GET_SCHEMA = cv.make_entity_service_schema({})
VOLUME_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_SPEAKER): cv.string,
        vol.Required(ATTR_VOLUME_LEVEL): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
    }
)
SPEAKERS_SCHEMA = vol.Schema({vol.Optional(ATTR_RESCAN, default=False): cv.boolean})

_MODES = {SERVICE_SET_OUTPUT: Mode.SET, SERVICE_ADD_OUTPUT: Mode.ADD, SERVICE_REMOVE_OUTPUT: Mode.REMOVE}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""

    async def modify(call: ServiceCall) -> ServiceResponse:
        apple_tvs = targets(hass, call)
        speakers = await async_resolve(hass, call.data[ATTR_SPEAKERS])
        response: dict[str, Any] = {}
        for tv in apple_tvs:
            previous = outputs(tv.atv)
            speakers = await async_change(
                hass,
                tv,
                speakers,
                _MODES[call.service],
                force=call.data.get(ATTR_FORCE, False),
                retries=call.data.get(ATTR_RETRIES, 0),
                fail_if_not_applied=call.data.get(ATTR_FAIL_IF_NOT_APPLIED, False),
            )
            response[tv.entity_id] = {"previous_outputs": previous, "outputs": outputs(tv.atv)}
        return response if call.return_response else None

    async def get_outputs(call: ServiceCall) -> ServiceResponse:
        response: dict[str, Any] = {tv.entity_id: {"outputs": outputs(tv.atv)} for tv in targets(hass, call)}
        return response

    async def get_speakers(call: ServiceCall) -> ServiceResponse:
        cache = get_cache(hass)
        if call.data[ATTR_RESCAN] or cache.scanned_at is None:
            cache = await async_scan(hass)
        return {"speakers": [{"name": d.name, "identifier": d.identifier} for d in cache.all()]}

    async def set_volume(call: ServiceCall) -> None:
        apple_tvs = targets(hass, call)
        (speaker,) = await async_resolve(hass, [call.data[ATTR_SPEAKER]])
        for tv in apple_tvs:
            await async_set_volume(hass, tv, speaker, call.data[ATTR_VOLUME_LEVEL])

    for service in (SERVICE_SET_OUTPUT, SERVICE_ADD_OUTPUT):
        hass.services.async_register(
            DOMAIN, service, modify, schema=MODIFY_SCHEMA, supports_response=SupportsResponse.OPTIONAL
        )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_OUTPUT, modify, schema=REMOVE_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN, SERVICE_GET_OUTPUTS, get_outputs, schema=GET_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN, SERVICE_GET_SPEAKERS, get_speakers, schema=SPEAKERS_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(DOMAIN, SERVICE_SET_VOLUME, set_volume, schema=VOLUME_SCHEMA)
