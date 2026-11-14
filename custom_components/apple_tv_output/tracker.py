"""Following the audio outputs of one Apple TV, for the entities."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval

from .apple_tv import AppleTV, get_apple_tv
from .const import DOMAIN, POLL_INTERVAL
from .outputs import outputs


class OutputTracker:
    """The current outputs of one Apple TV, read from its connection.

    The Apple TV integration owns pyatv's listener for output changes, so the outputs are read from
    memory every few seconds (no network traffic) and whenever the Apple TV's state changes.
    """

    def __init__(self, hass: HomeAssistant, entry: er.RegistryEntry) -> None:
        self.hass = hass
        self.entity_id = entry.entity_id
        self.unique_id = entry.unique_id
        device = dr.async_get(hass).async_get(entry.device_id) if entry.device_id else None
        # The entities get a device of their own, named like the Apple TV and connected via its device
        # (a device belongs to one integration, so they cannot join the Apple TV integration's device).
        self.device_name: str | None = (device.name_by_user or device.name) if device else None
        self.via_device_id: str | None = device.id if device else None
        self.via_device: tuple[str, str] | None = next(iter(sorted(device.identifiers)), None) if device else None
        self.tv: AppleTV | None = None
        # None while the Apple TV is not connected.
        self.outputs: list[dict[str, Any]] | None = None
        self._listeners: list[Callable[[], None]] = []

    @property
    def speaker_names(self) -> list[str]:
        """Return the names of the current outputs, not counting the Apple TV itself."""
        if self.tv is None:
            return []
        return [d.name for d in self.tv.atv.audio.output_devices if d.name and not self.tv.is_self(d)]

    @callback
    def async_refresh(self, _now: Any = None) -> None:
        try:
            tv: AppleTV | None = get_apple_tv(self.hass, self.entity_id, log=False)
        except HomeAssistantError:
            tv = None
        new = outputs(tv.atv) if tv is not None else None
        changed = new != self.outputs or (tv is None) != (self.tv is None)
        self.tv, self.outputs = tv, new
        if changed:
            for listener in list(self._listeners):
                listener()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def async_start(self) -> Callable[[], None]:
        """Start following the outputs; return a function that stops it."""

        @callback
        def state_changed(_event: Event[EventStateChangedData]) -> None:
            self.async_refresh()

        self.async_refresh()
        stop_poll = async_track_time_interval(
            self.hass, self.async_refresh, timedelta(seconds=POLL_INTERVAL), name=f"{DOMAIN} {self.entity_id}"
        )
        stop_state = async_track_state_change_event(self.hass, [self.entity_id], state_changed)

        def stop() -> None:
            stop_poll()
            stop_state()

        return stop
