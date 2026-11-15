"""Base class for the entities of Apple TV Audio Output."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .tracker import OutputTracker


class AppleTVOutputEntity(Entity):
    """An entity of one Apple TV, shown on the Apple TV's device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, tracker: OutputTracker, suffix: str) -> None:
        self.tracker = tracker
        self._attr_unique_id = f"{tracker.unique_id}_{suffix}"
        self._attr_translation_key = suffix
        info = DeviceInfo(
            identifiers={(DOMAIN, tracker.unique_id)},
            name=tracker.device_name or tracker.entity_id,
            model="AirPlay audio output",
        )
        if "via_device_id" in DeviceInfo.__annotations__:
            # Home Assistant 2026.8 and newer link devices by id; via_device is removed in 2027.8.
            if tracker.via_device_id:
                info["via_device_id"] = tracker.via_device_id  # type: ignore[typeddict-unknown-key,unused-ignore]
        elif tracker.via_device:
            info["via_device"] = tracker.via_device  # type: ignore[typeddict-unknown-key,unused-ignore]
        self._attr_device_info = info
        self._update_from_tracker()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.tracker.async_add_listener(self._handle_update))
        self._update_from_tracker()

    @property
    def available(self) -> bool:
        return self.tracker.outputs is not None

    @callback
    def _handle_update(self) -> None:
        self._update_from_tracker()
        self.async_write_ha_state()

    @callback
    def _update_from_tracker(self) -> None:
        """Update the entity's attributes from the tracker."""
