"""Reading and changing the audio outputs of an Apple TV."""

from __future__ import annotations

import asyncio
from enum import StrEnum
import inspect
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from . import const
from .apple_tv import AppleTV
from .common import error, key
from .speakers import Speaker, async_resolve

_LOGGER = logging.getLogger(__name__)


class Mode(StrEnum):
    """How a change treats the current outputs."""

    SET = "set"
    ADD = "add"
    REMOVE = "remove"


def outputs(atv: Any) -> list[dict[str, Any]]:
    """Return the current outputs as response data."""
    result = []
    for device in atv.audio.output_devices:
        item: dict[str, Any] = {"name": device.name, "identifier": device.identifier}
        # pyatv reports volume as 0-100; Home Assistant uses 0-1. Older pyatv has no volume per output.
        if (volume := getattr(device, "volume", None)) is not None:
            item["volume_level"] = round(volume / 100, 2)
        result.append(item)
    return result


def current(atv: Any) -> dict[str, str]:
    """Return the current outputs, as a map from key() form to the id the Apple TV reports."""
    return {key(d.identifier): d.identifier for d in atv.audio.output_devices if d.identifier}


def is_only_output(tv: AppleTV, speakers: list[Speaker]) -> bool:
    """Return whether the speakers are the only outputs, not counting the Apple TV itself."""
    wanted = frozenset().union(*(s.device.keys for s in speakers))
    return all(key(d.identifier or "") in wanted or tv.is_self(d) for d in tv.atv.audio.output_devices)


async def _send(tv: AppleTV, method: Any, identifiers: list[str]) -> None:
    try:
        await method(*identifiers)
    except Exception as err:
        raise error(HomeAssistantError, "command_failed", entity_id=tv.entity_id, error=str(err) or repr(err)) from err


async def _missing(tv: AppleTV, speakers: list[Speaker]) -> list[Speaker]:
    """Return the speakers that are not an output, giving the Apple TV a moment to report them."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + const.OUTPUT_SETTLE_TIME
    while True:
        now = current(tv.atv)
        missing = [s for s in speakers if not s.device.keys & now.keys()]
        if not missing or loop.time() >= deadline:
            return missing
        await asyncio.sleep(0.25)


async def async_change(
    hass: HomeAssistant,
    tv: AppleTV,
    speakers: list[Speaker],
    mode: Mode,
    *,
    force: bool = False,
    retries: int = 0,
    fail_if_not_applied: bool = False,
) -> list[Speaker]:
    """Change the outputs of one Apple TV; return the speakers, which a rescan may have updated."""
    audio = tv.atv.audio
    now = current(tv.atv)
    present = [next((now[k] for k in s.device.keys if k in now), None) for s in speakers]

    if mode is Mode.REMOVE:
        # Send the ids as the Apple TV reports them.
        if found := [identifier for identifier in present if identifier is not None]:
            await _send(tv, audio.remove_output_devices, found)
            _LOGGER.debug("Outputs of %s are now %s", tv.entity_id, outputs(tv.atv))
        return speakers

    # Already playing there: sending it again could interrupt the sound.
    if not force and all(present) and (mode is Mode.ADD or is_only_output(tv, speakers)):
        return speakers

    method = audio.add_output_devices if mode is Mode.ADD else audio.set_output_devices
    await _send(tv, method, [s.device.identifier for s in speakers])

    if await _missing(tv, speakers) and any(s.from_cache or s.by_address for s in speakers):
        # A speaker may have changed since the last scan (renamed, or a new id), or an entity's network
        # address may not be its AirPlay id: look again by name, and if any speaker now resolves to
        # another one, send the command once more.
        _LOGGER.debug("Not all speakers became an output of %s; looking them up again", tv.entity_id)
        try:
            fresh = await async_resolve(hass, [s.requested for s in speakers], rescan=True, by_address=False)
        except Exception as err:
            # The command has been sent; whatever the new scan could not place is reported below.
            _LOGGER.debug("Looking the speakers up again did not help: %s", err)
        else:
            changed = [new for new, old in zip(fresh, speakers, strict=True) if new.device != old.device]
            if changed:
                # add_output resends only the changed speakers, not to interrupt those already added.
                again = changed if mode is Mode.ADD else fresh
                await _send(tv, method, [s.device.identifier for s in again])
            speakers = fresh

    missing = await _missing(tv, speakers)
    for attempt in range(retries):
        if not missing:
            break
        # Right after the Apple TV wakes, the speaker or the AirPlay connection may not be ready yet.
        _LOGGER.debug("Retrying %s for %s (attempt %s of %s)", mode, tv.entity_id, attempt + 1, retries)
        await asyncio.sleep(const.RETRY_DELAY)
        again = missing if mode is Mode.ADD else speakers
        await _send(tv, method, [s.device.identifier for s in again])
        missing = await _missing(tv, speakers)

    if missing:
        names = ", ".join(s.device.name for s in missing)
        if fail_if_not_applied:
            raise error(HomeAssistantError, "not_applied", entity_id=tv.entity_id, speakers=names)
        _LOGGER.warning(
            "%s did not report %s as an output. If the Apple TV shows 'Could not connect', it cannot reach "
            "the speaker over AirPlay; see the troubleshooting section of the documentation",
            tv.entity_id,
            names,
        )
    _LOGGER.debug("Outputs of %s are now %s", tv.entity_id, outputs(tv.atv))
    return speakers


async def async_set_volume(tv: AppleTV, speaker: Speaker, level: float) -> None:
    """Set the volume (0-1) of one output speaker."""
    set_volume = tv.atv.audio.set_volume
    if "output_device" not in inspect.signature(set_volume).parameters:
        raise error(HomeAssistantError, "volume_not_supported")
    device = next((d for d in tv.atv.audio.output_devices if key(d.identifier or "") in speaker.device.keys), None)
    if device is None:
        raise error(ServiceValidationError, "speaker_not_output", entity_id=tv.entity_id, name=speaker.device.name)
    try:
        await set_volume(level * 100, output_device=device)
    except Exception as err:
        raise error(HomeAssistantError, "command_failed", entity_id=tv.entity_id, error=str(err) or repr(err)) from err
