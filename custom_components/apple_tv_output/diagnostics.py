"""Diagnostics for Apple TV Audio Output, to attach to bug reports."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .apple_tv import is_device_entry
from .common import is_id
from .const import CONF_ADDRESS, CONF_CREDENTIALS, CONF_IDENTIFIERS, DOMAIN
from .defaults import default_speakers
from .outputs import outputs
from .speakers import get_cache

if TYPE_CHECKING:
    from . import AppleTVOutputConfigEntry

# Pairing credentials, addresses and AirPlay ids identify the user's devices or give access to them.
TO_REDACT = {"identifier", CONF_ADDRESS, CONF_CREDENTIALS, CONF_IDENTIFIERS}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: AppleTVOutputConfigEntry) -> dict[str, Any]:
    integration = await async_get_integration(hass, DOMAIN)
    try:
        pyatv_version = version("pyatv")
    except PackageNotFoundError:
        pyatv_version = None
    data: dict[str, Any] = {
        "versions": {"integration": str(integration.version), "home_assistant": HA_VERSION, "pyatv": pyatv_version},
        "entry": {"data": dict(entry.data), "paired_protocols": sorted(entry.data.get(CONF_CREDENTIALS, {}))},
    }
    if is_device_entry(entry):
        connection = entry.runtime_data
        atv = connection.atv
        device_info = getattr(atv, "device_info", None)
        data.update(
            {
                # Speakers can be typed in as AirPlay ids; redact those, keep names.
                "default_speakers": [REDACTED if is_id(s.strip()) else s for s in default_speakers(entry)],
                "connected": atv is not None,
                "power_on": connection.power_on,
                "device": {
                    "model": getattr(device_info, "model_str", None),
                    "os_version": getattr(device_info, "version", None),
                },
                "outputs": outputs(atv) if atv is not None else None,
            }
        )
    data["speakers_found"] = [{"name": d.name, "identifier": d.identifier} for d in get_cache(hass).all()]
    return async_redact_data(data, TO_REDACT)
