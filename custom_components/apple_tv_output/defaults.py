"""Sending each Apple TV's sound to its default speakers whenever it wakes up."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_STANDBY, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util.hass_dict import HassKey

from . import const
from .apple_tv import get_apple_tv
from .outputs import Mode, async_change
from .speakers import async_resolve

_LOGGER = logging.getLogger(__name__)

ASLEEP = {STATE_OFF, STATE_STANDBY}
# While the state is unknown (Home Assistant starting, connection lost), whether the Apple TV slept is
# not known; such a gap is not counted as a wake-up.
UNKNOWN = {STATE_UNAVAILABLE, STATE_UNKNOWN}

# The default speakers applied by the previous setup, to tell a changed option from a reload.
DATA_PREVIOUS: HassKey[dict[str, list[str]]] = HassKey(f"{const.DOMAIN}_default_speakers")


def default_speakers(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, list[str]]:
    """Return the default speakers by Apple TV entity id (the options store them by registry id)."""
    registry = er.async_get(hass)
    result = {}
    for registry_id, speakers in entry.options.get(const.CONF_DEFAULT_SPEAKERS, {}).items():
        if speakers and (registry_entry := registry.async_get(registry_id)) is not None:
            result[registry_entry.entity_id] = list(speakers)
    return result


def _awake(state: State | None) -> bool | None:
    """Return whether the Apple TV is awake, or None when its state is not known."""
    if state is None or state.state in UNKNOWN:
        return None
    return state.state not in ASLEEP


async def async_apply(hass: HomeAssistant, entity_id: str, speakers: list[str]) -> None:
    """Send the Apple TV's sound to the speakers, waiting for its connection after it wakes."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + const.CONNECT_WAIT
    try:
        while True:
            try:
                tv = get_apple_tv(hass, entity_id, log=False)
                break
            except ServiceValidationError:
                raise
            except HomeAssistantError as err:
                # Only a missing connection can still come; any other error will not go away by waiting.
                if err.translation_key != "not_connected" or loop.time() >= deadline:
                    raise
                await asyncio.sleep(const.RETRY_DELAY)
        resolved = await async_resolve(hass, speakers)
        await async_change(hass, tv, resolved, Mode.SET, retries=const.DEFAULT_SPEAKERS_RETRIES)
    except Exception as err:
        _LOGGER.warning("Could not send %s to its default speakers: %s", entity_id, err)


@callback
def async_setup_defaults(hass: HomeAssistant, entry: ConfigEntry) -> Callable[[], None]:
    """Apply the default speakers when an Apple TV wakes up.

    An Apple TV that is already awake is left alone, unless its default speakers have just been
    changed: then they are applied at once.
    """
    defaults = default_speakers(hass, entry)
    previous = hass.data.get(DATA_PREVIOUS)
    hass.data[DATA_PREVIOUS] = defaults
    running: dict[str, asyncio.Task[None]] = {}
    # Whether each Apple TV was last seen awake, ignoring gaps in which its state was not known.
    last_awake = {entity_id: _awake(hass.states.get(entity_id)) for entity_id in defaults}

    @callback
    def start(entity_id: str) -> None:
        if (task := running.get(entity_id)) is not None and not task.done():
            return
        running[entity_id] = entry.async_create_background_task(
            hass, async_apply(hass, entity_id, defaults[entity_id]), f"{const.DOMAIN} defaults {entity_id}"
        )

    @callback
    def state_changed(event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        if (awake := _awake(event.data["new_state"])) is None:
            return
        woke = awake and last_awake.get(entity_id) is False
        last_awake[entity_id] = awake
        if woke:
            start(entity_id)

    if previous is not None:
        for entity_id, speakers in defaults.items():
            if last_awake[entity_id] and previous.get(entity_id) != speakers:
                start(entity_id)

    unsubscribe = async_track_state_change_event(hass, list(defaults), state_changed)

    def stop() -> None:
        unsubscribe()
        if not hass.config_entries.async_get_entry(entry.entry_id):
            hass.data.pop(DATA_PREVIOUS, None)

    return stop
