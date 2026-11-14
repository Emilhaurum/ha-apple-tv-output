"""Sending each Apple TV's sound to its default speakers whenever it wakes up."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_STANDBY, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from . import const
from .apple_tv import get_apple_tv
from .outputs import Mode, async_change
from .speakers import async_resolve

_LOGGER = logging.getLogger(__name__)

# States in which the Apple TV is asleep or not connected; leaving them means it woke up.
ASLEEP = {STATE_OFF, STATE_STANDBY, STATE_UNAVAILABLE, STATE_UNKNOWN}


def _awake(state: State | None) -> bool:
    return state is not None and state.state not in ASLEEP


def default_speakers(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, list[str]]:
    """Return the default speakers by Apple TV entity id (the options store them by registry id)."""
    registry = er.async_get(hass)
    result = {}
    for registry_id, speakers in entry.options.get(const.CONF_DEFAULT_SPEAKERS, {}).items():
        if speakers and (registry_entry := registry.async_get(registry_id)) is not None:
            result[registry_entry.entity_id] = list(speakers)
    return result


async def async_apply(hass: HomeAssistant, entity_id: str, speakers: list[str]) -> None:
    """Send the Apple TV's sound to the speakers, waiting for its connection after it wakes."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + const.CONNECT_WAIT
    while True:
        try:
            tv = get_apple_tv(hass, entity_id)
            break
        except HomeAssistantError as err:
            if loop.time() >= deadline:
                _LOGGER.warning("Could not send %s to its default speakers: %s", entity_id, err)
                return
            await asyncio.sleep(const.RETRY_DELAY)
    try:
        resolved = await async_resolve(hass, speakers)
        await async_change(hass, tv, resolved, Mode.SET, retries=const.DEFAULT_SPEAKERS_RETRIES)
    except HomeAssistantError as err:
        _LOGGER.warning("Could not send %s to its default speakers: %s", entity_id, err)


@callback
def async_setup_defaults(hass: HomeAssistant, entry: ConfigEntry) -> Callable[[], None]:
    """Apply the default speakers when an Apple TV wakes up, and now for those already awake."""
    defaults = default_speakers(hass, entry)
    running: dict[str, asyncio.Task[None]] = {}

    @callback
    def start(entity_id: str) -> None:
        if (task := running.get(entity_id)) is not None and not task.done():
            return
        running[entity_id] = entry.async_create_background_task(
            hass, async_apply(hass, entity_id, defaults[entity_id]), f"{const.DOMAIN} defaults {entity_id}"
        )

    @callback
    def state_changed(event: Event[EventStateChangedData]) -> None:
        if not _awake(event.data["old_state"]) and _awake(event.data["new_state"]):
            start(event.data["entity_id"])

    for entity_id in defaults:
        if _awake(hass.states.get(entity_id)):
            start(entity_id)
    return async_track_state_change_event(hass, list(defaults), state_changed)
