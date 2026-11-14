"""Diagnostics for Apple TV Audio Output, to attach to bug reports."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .defaults import default_speakers
from .speakers import get_cache

if TYPE_CHECKING:
    from . import AppleTVOutputConfigEntry

# AirPlay ids are MAC addresses or unique ids of the user's devices.
TO_REDACT = {"identifier"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: AppleTVOutputConfigEntry) -> dict[str, Any]:
    integration = await async_get_integration(hass, DOMAIN)
    try:
        pyatv_version = version("pyatv")
    except PackageNotFoundError:
        pyatv_version = None
    cache = get_cache(hass)
    data = {
        "versions": {"integration": str(integration.version), "home_assistant": HA_VERSION, "pyatv": pyatv_version},
        "default_speakers": default_speakers(hass, entry),
        "speakers_found": [{"name": d.name, "identifier": d.identifier} for d in cache.all()],
        "apple_tvs": [
            {
                "entity_id": tracker.entity_id,
                "connected": tracker.outputs is not None,
                "outputs": tracker.outputs,
            }
            for tracker in entry.runtime_data.trackers
        ],
    }
    return async_redact_data(data, TO_REDACT)
