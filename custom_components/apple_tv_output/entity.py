"""Base class for the entities of Apple TV Audio Output."""

from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .apple_tv import AppleTV, connected
from .connection import AppleTVConnection
from .const import DOMAIN
from .outputs import outputs


class AppleTVOutputEntity(Entity):
    """An entity of one paired Apple TV, updated whenever its connection reports a change."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, connection: AppleTVConnection, suffix: str) -> None:
        self.connection = connection
        unique_id = connection.entry.unique_id
        self._attr_unique_id = f"{unique_id}_{suffix}"
        self._attr_translation_key = suffix
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(unique_id))}, name=connection.name, manufacturer="Apple"
        )
        self._update_from_connection()

    @property
    def tv(self) -> AppleTV | None:
        return connected(self.connection) if self.connection.atv is not None else None

    @property
    def outputs(self) -> list[dict[str, Any]]:
        return outputs(self.connection.atv) if self.connection.atv is not None else []

    @property
    def speaker_names(self) -> list[str]:
        """Return the names of the current outputs, not counting the Apple TV itself."""
        if (tv := self.tv) is None:
            return []
        return [d.name for d in tv.atv.audio.output_devices if d.name and not tv.is_self(d)]

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.connection.async_add_listener(self._handle_update))
        self._update_from_connection()

    @property
    def available(self) -> bool:
        return self.connection.atv is not None

    @callback
    def _handle_update(self) -> None:
        self._update_from_connection()
        self.async_write_ha_state()

    @callback
    def _update_from_connection(self) -> None:
        """Update the entity's attributes from the connection."""
