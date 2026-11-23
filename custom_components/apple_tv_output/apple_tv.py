"""Finding the paired Apple TVs, and the ones an action call targets."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, ENTITY_MATCH_ALL
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .common import error, key
from .const import APPLE_TV_DOMAIN, CONF_IDENTIFIERS, DOMAIN

if TYPE_CHECKING:
    from .connection import AppleTVConnection

try:
    from homeassistant.helpers.target import TargetSelection, async_extract_referenced_entity_ids
except ImportError:  # Older Home Assistant releases
    TargetSelection = None  # type: ignore[assignment,misc]
    from homeassistant.helpers.service import (  # type: ignore[attr-defined,unused-ignore]
        async_extract_referenced_entity_ids as _legacy_extract,
    )

_LOGGER = logging.getLogger(__name__)


@dataclass
class AppleTV:
    """A connected Apple TV."""

    # How the Apple TV is named in responses and messages: the entity the call targeted, or its name.
    entity_id: str
    atv: Any
    # Ids (as key() forms) and names by which the Apple TV itself can appear in its own outputs.
    own_keys: frozenset[str]
    own_names: frozenset[str]

    def is_self(self, device: Any) -> bool:
        """Return whether an output device is the Apple TV itself."""
        return key(device.identifier or "") in self.own_keys or (device.name or "").casefold() in self.own_names


def is_device_entry(entry: ConfigEntry) -> bool:
    """Return whether a config entry is a paired Apple TV (not an entry left over from version 1)."""
    return bool(entry.data.get(CONF_IDENTIFIERS))


def connections(hass: HomeAssistant) -> list[AppleTVConnection]:
    """Return the connections of the loaded Apple TV entries."""
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if is_device_entry(entry) and entry.state is ConfigEntryState.LOADED
    ]


def connected(connection: AppleTVConnection, label: str | None = None) -> AppleTV:
    """Return the Apple TV of a connection, or raise when it is not connected."""
    label = label or connection.name
    if connection.atv is None:
        raise error(HomeAssistantError, "not_connected", entity_id=label)
    device_info = getattr(connection.atv, "device_info", None)
    own_ids = [getattr(device_info, "output_device_id", None) or "", getattr(device_info, "mac", None) or ""]
    return AppleTV(
        label,
        connection.atv,
        connection.identifiers | frozenset(key(i) for i in own_ids if i),
        frozenset({connection.name.casefold()}),
    )


def connection_for_entity(hass: HomeAssistant, entity_id: str) -> AppleTVConnection | None:
    """Return the Apple TV an entity belongs to.

    That is one of this integration's entities, or the Apple TV integration's media player of a paired
    Apple TV, matched by the ids in the entity registry, so automations written for that media player
    keep working.
    """
    registry_entry = er.async_get(hass).async_get(entity_id)
    if registry_entry is None:
        return None
    for connection in connections(hass):
        if registry_entry.platform == DOMAIN and registry_entry.config_entry_id == connection.entry.entry_id:
            return connection
        if (
            registry_entry.platform == APPLE_TV_DOMAIN
            and registry_entry.domain == MEDIA_PLAYER_DOMAIN
            and key(registry_entry.unique_id) in connection.identifiers
        ):
            return connection
    return None


def targets(hass: HomeAssistant, call: ServiceCall) -> list[AppleTV]:
    """Return the Apple TVs a call targets.

    An entity named directly must belong to a connected Apple TV. Of the entities an area, a device or
    `all` brings in, those of Apple TVs are used, and those that cannot be are skipped.
    """
    if call.data.get(ATTR_ENTITY_ID) == ENTITY_MATCH_ALL:
        direct: set[str] = set()
        indirect: set[str] = set()
        everything = True
    else:
        if TargetSelection is not None:
            selected = async_extract_referenced_entity_ids(hass, TargetSelection(call.data))
        else:
            selected = _legacy_extract(hass, call)
        direct = set(selected.referenced)
        indirect = set(selected.indirectly_referenced) - direct
        everything = False

    # Check every Apple TV before changing any, so a bad target cannot leave a half-done change.
    apple_tvs: dict[str, AppleTV] = {}
    for entity_id in sorted(direct):
        if (connection := connection_for_entity(hass, entity_id)) is None:
            raise error(ServiceValidationError, "not_apple_tv", entity_id=entity_id)
        apple_tvs.setdefault(connection.entry.entry_id, connected(connection, entity_id))

    found: list[tuple[AppleTVConnection, str | None]] = []
    if everything:
        found = [(connection, None) for connection in connections(hass)]
    # Media players first, so a response is keyed by the Apple TV's media player where there is one.
    for entity_id in sorted(indirect, key=lambda e: (not e.startswith(f"{MEDIA_PLAYER_DOMAIN}."), e)):
        if (connection := connection_for_entity(hass, entity_id)) is not None:
            found.append((connection, entity_id if entity_id.startswith(f"{MEDIA_PLAYER_DOMAIN}.") else None))
    skipped: list[HomeAssistantError] = []
    for connection, label in found:
        if connection.entry.entry_id in apple_tvs:
            continue
        try:
            apple_tvs[connection.entry.entry_id] = connected(connection, label)
        except HomeAssistantError as err:
            _LOGGER.debug("Skipping %s: %s", connection.name, err)
            skipped.append(err)
    if not apple_tvs:
        raise skipped[0] if skipped else error(ServiceValidationError, "no_apple_tv")
    return list(apple_tvs.values())
