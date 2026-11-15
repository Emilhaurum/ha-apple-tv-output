"""Send an Apple TV's sound to AirPlay speakers.

The core Apple TV integration does not expose pyatv's output-device control. This integration adds
actions and entities for it, reusing the connection the Apple TV integration already holds.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .apple_tv import apple_tv_players, is_apple_tv_player
from .const import DOMAIN
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
    entry.async_on_unload(async_start_background_scans(hass, entry))
    entry.async_on_unload(async_setup_defaults(hass, entry))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    tracked = {t.entity_id for t in trackers}

    @callback
    def affects_apple_tvs(event_data: er.EventEntityRegistryUpdatedData) -> bool:
        """Return whether an Apple TV was added, removed, renamed, enabled or disabled."""
        action = event_data["action"]
        if action == "update":
            changes: Mapping[str, Any] = event_data.get("changes") or {}  # type: ignore[assignment]
            if "entity_id" not in changes and "disabled_by" not in changes:
                return False
        if event_data["entity_id"] in tracked:
            return True
        if action == "remove":
            return False
        registry_entry = er.async_get(hass).async_get(event_data["entity_id"])
        return is_apple_tv_player(hass, registry_entry) and not registry_entry.disabled  # type: ignore[union-attr]

    @callback
    def registry_updated(_event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        # Set up again, so the entities and the default speakers follow.
        hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, registry_updated, event_filter=affects_apple_tvs)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: AppleTVOutputConfigEntry) -> None:
    """Set up again with the new default speakers."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AppleTVOutputConfigEntry) -> bool:
    """Unload the entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
