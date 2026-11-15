"""Finding Apple TVs and the pyatv connections the Apple TV integration holds for them."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.media_player import DATA_COMPONENT, DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, ENTITY_MATCH_ALL, __version__ as HA_VERSION
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir

from .common import ISSUE_URL, error, key
from .const import APPLE_TV_DOMAIN, DOMAIN, ISSUE_UNSUPPORTED_VERSION

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
    """An Apple TV and its live connection."""

    entity_id: str
    atv: Any
    # Ids (as key() forms) and names by which the Apple TV itself can appear in its own outputs.
    own_keys: frozenset[str]
    own_names: frozenset[str]

    def is_self(self, device: Any) -> bool:
        """Return whether an output device is the Apple TV itself."""
        return key(device.identifier or "") in self.own_keys or (device.name or "").casefold() in self.own_names


def get_apple_tv(hass: HomeAssistant, entity_id: str, *, log: bool = True) -> AppleTV:
    """Return the Apple TV integration's live pyatv connection for a media player."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != APPLE_TV_DOMAIN or entry.domain != MEDIA_PLAYER_DOMAIN:
        raise error(ServiceValidationError, "not_apple_tv", entity_id=entity_id)

    component = hass.data.get(DATA_COMPONENT)
    entity = component.get_entity(entity_id) if component else None
    config_entry = hass.config_entries.async_get_entry(entry.config_entry_id) if entry.config_entry_id else None
    manager = getattr(config_entry, "runtime_data", None)

    if (entity is not None or manager is not None) and not hasattr(entity, "atv") and not hasattr(manager, "atv"):
        # This relies on internals of the Apple TV integration; say clearly when they have changed.
        if log:
            _LOGGER.error(
                "The Apple TV integration in Home Assistant %s no longer exposes its pyatv connection "
                "(%s has no 'atv' attribute), so %s cannot be controlled. Please report this at %s",
                HA_VERSION,
                type(entity if entity is not None else manager).__name__,
                entity_id,
                ISSUE_URL,
            )
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_UNSUPPORTED_VERSION,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_UNSUPPORTED_VERSION,
            translation_placeholders={"version": HA_VERSION, "url": ISSUE_URL},
            learn_more_url=ISSUE_URL,
        )
        raise error(HomeAssistantError, "unsupported_version", version=HA_VERSION)
    ir.async_delete_issue(hass, DOMAIN, ISSUE_UNSUPPORTED_VERSION)

    atv = getattr(entity, "atv", None) or getattr(manager, "atv", None)
    if atv is None:
        raise error(HomeAssistantError, "not_connected", entity_id=entity_id)

    own_ids: list[str] = []
    own_names: list[str] = []
    if config_entry is not None:
        own_ids += [config_entry.unique_id or "", *config_entry.data.get("identifiers", [])]
        own_names += [config_entry.title, config_entry.data.get("name", "")]
    device_info = getattr(atv, "device_info", None)
    own_ids += [getattr(device_info, "output_device_id", None) or "", getattr(device_info, "mac", None) or ""]
    return AppleTV(
        entity_id,
        atv,
        frozenset(key(i) for i in own_ids if i),
        frozenset(n.casefold() for n in own_names if n),
    )


def is_apple_tv_player(hass: HomeAssistant, entry: er.RegistryEntry | None) -> bool:
    """Return whether a registry entry is the media player of an Apple TV (not of a HomePod)."""
    if entry is None or entry.platform != APPLE_TV_DOMAIN or entry.domain != MEDIA_PLAYER_DOMAIN:
        return False
    device = dr.async_get(hass).async_get(entry.device_id) if entry.device_id else None
    # Only a main device has a model; a child device (Home Assistant 2026.9 and newer) has none.
    model = device.model if isinstance(device, dr.DeviceEntry) else None
    return "homepod" not in (model or "").casefold()


def apple_tv_players(hass: HomeAssistant) -> list[er.RegistryEntry]:
    """Return the registry entries of every Apple TV media player, sorted by entity id."""
    registry = er.async_get(hass)
    return sorted(
        (e for e in registry.entities.values() if is_apple_tv_player(hass, e) and not e.disabled),
        key=lambda e: e.entity_id,
    )


def targets(hass: HomeAssistant, call: ServiceCall) -> list[AppleTV]:
    """Return the Apple TVs a call targets.

    An entity named directly must be a connected Apple TV. Of the entities an area, a device or
    `all` brings in, the Apple TV media players are used, and those that cannot be are skipped.
    """
    registry = er.async_get(hass)
    if call.data.get(ATTR_ENTITY_ID) == ENTITY_MATCH_ALL:
        direct: set[str] = set()
        indirect = set(registry.entities)
    else:
        if TargetSelection is not None:
            selected = async_extract_referenced_entity_ids(hass, TargetSelection(call.data))
        else:
            selected = _legacy_extract(hass, call)
        direct = set(selected.referenced)
        indirect = set(selected.indirectly_referenced) - direct
    indirect = {entity_id for entity_id in indirect if is_apple_tv_player(hass, registry.async_get(entity_id))}

    # Check every Apple TV before changing any, so a bad target cannot leave a half-done change.
    apple_tvs = [get_apple_tv(hass, entity_id) for entity_id in sorted(direct)]
    skipped: list[HomeAssistantError] = []
    for entity_id in sorted(indirect):
        try:
            apple_tvs.append(get_apple_tv(hass, entity_id))
        except HomeAssistantError as err:
            _LOGGER.debug("Skipping %s: %s", entity_id, err)
            skipped.append(err)
    if not apple_tvs:
        raise skipped[0] if skipped else error(ServiceValidationError, "no_apple_tv")
    return apple_tvs
