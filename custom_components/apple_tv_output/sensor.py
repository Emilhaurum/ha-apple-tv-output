"""Sensor showing each Apple TV's current audio outputs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import AppleTVOutputEntity

if TYPE_CHECKING:
    from . import AppleTVOutputConfigEntry

# Home Assistant limits states to 255 characters.
MAX_STATE = 255


async def async_setup_entry(
    hass: HomeAssistant, entry: AppleTVOutputConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([OutputsSensor(entry.runtime_data, "outputs")])


class OutputsSensor(AppleTVOutputEntity, SensorEntity):
    """The names of the outputs the Apple TV plays to; the details are attributes."""

    @callback
    def _update_from_connection(self) -> None:
        outputs = self.outputs
        names = ", ".join(o["name"] for o in outputs if o.get("name"))
        self._attr_native_value = (names[: MAX_STATE - 1] + "…" if len(names) > MAX_STATE else names) or None
        attributes: dict[str, Any] = {"outputs": outputs, "speakers": self.speaker_names}
        self._attr_extra_state_attributes = attributes
