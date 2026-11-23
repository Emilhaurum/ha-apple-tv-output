"""Sending an Apple TV's sound to its default speakers whenever it wakes up."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.util.hass_dict import HassKey

from . import const
from .apple_tv import connected
from .outputs import Mode, async_change
from .speakers import async_resolve

if TYPE_CHECKING:
    from .connection import AppleTVConnection

_LOGGER = logging.getLogger(__name__)

# The default speakers each entry applied at its previous setup, to tell a changed option from a reload.
DATA_PREVIOUS: HassKey[dict[str, list[str]]] = HassKey(f"{const.DOMAIN}_default_speakers")


def default_speakers(entry: ConfigEntry) -> list[str]:
    return [s for s in entry.options.get(const.CONF_DEFAULT_SPEAKERS, []) if isinstance(s, str) and s.strip()]


async def async_apply(hass: HomeAssistant, connection: AppleTVConnection, speakers: list[str]) -> None:
    """Send the Apple TV's sound to the speakers."""
    try:
        tv = connected(connection)
        resolved = await async_resolve(hass, speakers)
        await async_change(hass, tv, resolved, Mode.SET, retries=const.DEFAULT_SPEAKERS_RETRIES)
    except Exception as err:
        _LOGGER.warning("Could not send %s to its default speakers: %s", connection.name, err)


@callback
def async_setup_defaults(hass: HomeAssistant, connection: AppleTVConnection) -> Callable[[], None]:
    """Apply the default speakers when the Apple TV wakes up.

    An Apple TV that is already on is left alone, unless its default speakers have just been changed:
    then they are applied at once (or as soon as it is connected).
    """
    entry = connection.entry
    speakers = default_speakers(entry)
    previous = hass.data.setdefault(DATA_PREVIOUS, {})
    changed = entry.entry_id in previous and previous[entry.entry_id] != speakers
    previous[entry.entry_id] = speakers
    task: asyncio.Task[None] | None = None

    @callback
    def start() -> None:
        nonlocal task
        if not speakers or (task is not None and not task.done()):
            return
        task = entry.async_create_background_task(
            hass, async_apply(hass, connection, speakers), f"{const.DOMAIN} defaults {connection.name}"
        )

    removers = [connection.async_add_wake_listener(start)]
    if changed and speakers:
        if connection.atv is not None and connection.power_on:
            start()
        elif connection.atv is None:
            # Not connected yet (the entry was just reloaded): apply once connected, if it is on.
            waiting = True

            @callback
            def first_connect() -> None:
                nonlocal waiting
                if waiting and connection.atv is not None:
                    waiting = False
                    if connection.power_on:
                        start()

            removers.append(connection.async_add_listener(first_connect))

    def stop() -> None:
        for remove in removers:
            remove()
        if hass.config_entries.async_get_entry(entry.entry_id) is None:
            previous.pop(entry.entry_id, None)

    return stop
