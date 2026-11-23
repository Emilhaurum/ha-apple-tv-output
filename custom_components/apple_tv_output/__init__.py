"""Send an Apple TV's sound to AirPlay speakers.

Each paired Apple TV is a config entry with its own pyatv connection. The actions and entities change
the Apple TV's audio outputs through that connection.
"""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.hass_dict import HassKey

from .apple_tv import is_device_entry
from .connection import AppleTVConnection
from .const import DOMAIN, ISSUE_LEGACY_ENTRY
from .defaults import async_setup_defaults
from .services import async_setup_services
from .speakers import async_start_background_scans

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.SELECT, Platform.SENSOR]

type AppleTVOutputConfigEntry = ConfigEntry[AppleTVConnection]

# The background scans for speakers run while any Apple TV is set up: (number of entries, stop function).
DATA_SCANS: HassKey[tuple[int, Callable[[], None]]] = HassKey(f"{DOMAIN}_scans")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AppleTVOutputConfigEntry) -> bool:
    """Connect to the Apple TV, and apply its default speakers when it wakes up."""
    if not is_device_entry(entry):
        # Version 1 had a single entry that borrowed the Apple TV integration's connection. It does
        # nothing now; the repair notice asks to add each Apple TV.
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_LEGACY_ENTRY,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_LEGACY_ENTRY,
        )
        return True

    connection = AppleTVConnection(hass, entry)
    entry.runtime_data = connection
    _start_scans(hass, entry)
    entry.async_on_unload(async_setup_defaults(hass, connection))
    options = dict(entry.options)

    async def entry_updated(hass: HomeAssistant, entry: AppleTVOutputConfigEntry) -> None:
        # The connection also updates the entry when the Apple TV's address changes; only new options
        # (default speakers) need a new setup.
        if dict(entry.options) != options:
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(entry_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    connection.async_start()
    return True


def _start_scans(hass: HomeAssistant, entry: ConfigEntry) -> None:
    count, stop = hass.data.get(DATA_SCANS, (0, lambda: None))
    if count == 0:
        stop = async_start_background_scans(hass, entry)
    hass.data[DATA_SCANS] = (count + 1, stop)

    def release() -> None:
        count, stop = hass.data.pop(DATA_SCANS, (1, lambda: None))
        if count <= 1:
            stop()
        else:
            hass.data[DATA_SCANS] = (count - 1, stop)

    entry.async_on_unload(release)


async def async_unload_entry(hass: HomeAssistant, entry: AppleTVOutputConfigEntry) -> bool:
    """Unload the entry, and close the connection."""
    if not is_device_entry(entry):
        return True
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the repair notice with the last entry left over from version 1."""
    if not is_device_entry(entry) and not any(
        not is_device_entry(e) for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id
    ):
        ir.async_delete_issue(hass, DOMAIN, ISSUE_LEGACY_ENTRY)
