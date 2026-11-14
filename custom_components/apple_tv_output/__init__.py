"""Send an Apple TV's sound to AirPlay speakers.

The core Apple TV integration does not expose pyatv's output-device control. This integration adds
actions and entities for it, reusing the connection the Apple TV integration already holds.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .apple_tv import apple_tv_players
from .const import APPLE_TV_DOMAIN, DOMAIN
from .defaults import async_setup_defaults
from .services import async_setup_services
from .speakers import async_start_background_scans
from .tracker import OutputTracker

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.SELECT, Platform.SENSOR]


@dataclass
class RuntimeData:
    """What the config entry holds while it is loaded."""

    trackers: list[OutputTracker] = field(default_factory=list)


type AppleTVOutputConfigEntry = ConfigEntry[RuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AppleTVOutputConfigEntry) -> bool:
    """Follow each Apple TV's outputs, scan for speakers, and apply the default speakers."""
    trackers = [OutputTracker(hass, registry_entry) for registry_entry in apple_tv_players(hass)]
    entry.runtime_data = RuntimeData(trackers)
    for tracker in trackers:
        entry.async_on_unload(tracker.async_start())
    entry.async_on_unload(async_start_background_scans(hass))
    entry.async_on_unload(async_setup_defaults(hass, entry))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    @callback
    def registry_updated(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        # An Apple TV was added or removed: set up again, so its entities follow.
        if event.data["action"] in ("create", "remove"):
            hass.config_entries.async_schedule_reload(entry.entry_id)

    @callback
    def is_apple_tv_player(event_data: er.EventEntityRegistryUpdatedData) -> bool:
        entity_id = event_data["entity_id"]
        if not entity_id.startswith("media_player."):
            return False
        if event_data["action"] == "remove":
            return any(t.entity_id == entity_id for t in trackers)
        registry_entry = er.async_get(hass).async_get(entity_id)
        return registry_entry is not None and registry_entry.platform == APPLE_TV_DOMAIN

    entry.async_on_unload(
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, registry_updated, event_filter=is_apple_tv_player)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: AppleTVOutputConfigEntry) -> None:
    """Set up again with the new default speakers."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AppleTVOutputConfigEntry) -> bool:
    """Unload the entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
